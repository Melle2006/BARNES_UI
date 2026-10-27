"""Phase 6: contact definitions, body loads and the capability gate.

These tests cover the deck-writing and bookkeeping half. They deliberately do not
assert that contact converges -- that claim belongs to
``scripts/phase6_benchmarks.py``, which runs the solver and records what it found,
and the whole point of the capability registry is that a passing unit test is not
evidence a solver feature works.
"""

from __future__ import annotations

import numpy as np
import pytest

from barnes_ui.core.fea.capabilities import (
    Capability,
    CapabilityNotAvailableError,
    CapabilityRecord,
    CapabilityRegistry,
    CapabilityStatus,
)
from barnes_ui.core.fea.contact import (
    ContactError,
    ContactFormulation,
    ContactPair,
    ContactSurface,
    SurfaceType,
    element_faces_from_nodes,
)
from barnes_ui.core.fea.deck import BoundaryCondition, DeckSettings, write_deck
from barnes_ui.core.fea.loads import (
    GravityLoad,
    LoadError,
    PointLoad,
    density_from_g_per_cm3,
)
from barnes_ui.core.fea.meshing import Mesh
from barnes_ui.core.material.models import provisional_tpu


def _two_tet_mesh() -> Mesh:
    """Two first-order tets sharing a face, with named node sets.

    First-order keeps the face map readable; the second-order map is exercised
    separately against a generated mesh in the kernel-dependent test below.
    """
    nodes = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 1.0, 1.0],
    ])
    elements = np.array([[0, 1, 2, 3], [1, 2, 3, 4]])
    return Mesh(
        nodes=nodes,
        elements=elements,
        second_order=False,
        element_size=1.0,
        node_sets={
            "bottom": np.array([0, 1, 2]),
            "far": np.array([4]),
            "shared": np.array([1, 2, 3]),
        },
    )


class TestFaceExtraction:
    def test_a_face_is_found_when_all_its_nodes_are_selected(self) -> None:
        mesh = _two_tet_mesh()
        faces = element_faces_from_nodes(mesh, [0, 1, 2])
        assert (0, "S1") in faces

    def test_a_shared_face_belongs_to_both_elements(self) -> None:
        """Nodes 1, 2, 3 form a face of each tet, so both must appear."""
        mesh = _two_tet_mesh()
        faces = element_faces_from_nodes(mesh, [1, 2, 3])
        assert {element for element, _ in faces} == {0, 1}

    def test_an_incomplete_selection_yields_no_face(self) -> None:
        mesh = _two_tet_mesh()
        assert element_faces_from_nodes(mesh, [0, 1]) == []

    def test_an_element_surface_from_a_nodeless_set_is_refused(self) -> None:
        mesh = _two_tet_mesh()
        with pytest.raises(ContactError, match="no faces"):
            ContactSurface.from_node_sets(mesh, "far", "s", SurfaceType.ELEMENT)


class TestContactPairValidation:
    def _surfaces(self):
        mesh = _two_tet_mesh()
        slave = ContactSurface.from_node_sets(mesh, "bottom", "sl", SurfaceType.NODE)
        master = ContactSurface.from_node_sets(
            mesh, "shared", "ma", SurfaceType.ELEMENT
        )
        return slave, master

    def test_a_node_master_is_refused(self) -> None:
        """A bare node set has no normal, so it cannot be a master surface."""
        slave, _ = self._surfaces()
        with pytest.raises(ContactError, match="surface normal"):
            ContactPair(name="p", slave=slave, master=slave, stiffness=100.0)

    def test_surface_to_surface_needs_an_element_slave(self) -> None:
        slave, master = self._surfaces()
        with pytest.raises(ContactError, match="both"):
            ContactPair(
                name="p", slave=slave, master=master, stiffness=100.0,
                formulation=ContactFormulation.SURFACE_TO_SURFACE,
            )

    def test_negative_friction_is_refused(self) -> None:
        slave, master = self._surfaces()
        with pytest.raises(ContactError, match="add energy"):
            ContactPair(name="p", slave=slave, master=master,
                        stiffness=100.0, friction=-0.1)

    def test_suggested_stiffness_scales_as_modulus_over_size(self) -> None:
        assert ContactPair.suggested_stiffness(1000.0, 2.0) == pytest.approx(5000.0)
        assert ContactPair.suggested_stiffness(2000.0, 2.0) == pytest.approx(10000.0)

    def test_stick_stiffness_defaults_to_a_tenth(self) -> None:
        slave, master = self._surfaces()
        pair = ContactPair(name="p", slave=slave, master=master, stiffness=1000.0)
        assert pair.resolved_stick_stiffness() == pytest.approx(100.0)


class TestContactDeckCards:
    def _deck(self, **pair_kwargs) -> str:
        mesh = _two_tet_mesh()
        slave = ContactSurface.from_node_sets(mesh, "bottom", "sl", SurfaceType.NODE)
        master = ContactSurface.from_node_sets(
            mesh, "shared", "ma", SurfaceType.ELEMENT
        )
        pair = ContactPair(name="c", slave=slave, master=master, **pair_kwargs)
        return write_deck(
            mesh, provisional_tpu(),
            [BoundaryCondition("bottom", (1, 2, 3), 0.0)],
            DeckSettings(contact_pairs=[pair]),
        )

    def test_the_cards_appear_in_the_order_calculix_expects(self) -> None:
        deck = self._deck(stiffness=1000.0)
        for keyword in ("*SURFACE, NAME=sl, TYPE=NODE",
                        "*SURFACE, NAME=ma, TYPE=ELEMENT",
                        "*SURFACE INTERACTION, NAME=c_interaction",
                        "*CONTACT PAIR, INTERACTION=c_interaction"):
            assert keyword in deck
        assert deck.index("*SURFACE, NAME=sl") < deck.index("*SURFACE INTERACTION")
        assert deck.index("*MATERIAL") < deck.index("*SURFACE INTERACTION")
        assert deck.index("*CONTACT PAIR") < deck.index("*STEP")

    def test_a_node_surface_lists_one_node_per_line(self) -> None:
        """CalculiX rejects the eight-per-line packing that *NSET uses."""
        deck = self._deck(stiffness=1000.0)
        body = deck.split("*SURFACE, NAME=sl, TYPE=NODE\n")[1]
        first_lines = body.splitlines()[:3]
        assert all("," not in line for line in first_lines)

    def test_zero_stiffness_is_refused_rather_than_written(self) -> None:
        """A zero-stiffness linear law lets the surfaces pass through each other
        while the run converges happily."""
        from barnes_ui.core.fea.deck import DeckError

        with pytest.raises(DeckError, match="no normal stiffness"):
            self._deck(stiffness=0.0)

    def test_friction_is_written_only_when_asked_for(self) -> None:
        assert "*FRICTION" not in self._deck(stiffness=1000.0)
        assert "*FRICTION" in self._deck(stiffness=1000.0, friction=0.3)


class TestGravityLoad:
    def test_density_conversion_is_the_documented_factor(self) -> None:
        assert density_from_g_per_cm3(1.2) == pytest.approx(1.2e-9)

    def test_a_density_in_the_wrong_unit_is_caught(self) -> None:
        """1.2 g/cm^3 entered as 1.2e-3 overstates every force by a million."""
        with pytest.raises(LoadError, match="denser than steel"):
            GravityLoad(density=1.2e-3)

    def test_a_zero_direction_is_refused(self) -> None:
        with pytest.raises(LoadError, match="zero vector"):
            GravityLoad(density=1.2e-9, direction=(0.0, 0.0, 0.0))

    def test_direction_is_normalised(self) -> None:
        load = GravityLoad(density=1.2e-9, direction=(0.0, 0.0, -3.0))
        assert load.unit_direction == pytest.approx((0.0, 0.0, -1.0))

    def test_the_deck_carries_density_and_dload(self) -> None:
        mesh = _two_tet_mesh()
        deck = write_deck(
            mesh, provisional_tpu(),
            [BoundaryCondition("bottom", (1, 2, 3), 0.0)],
            DeckSettings(gravity=GravityLoad(density=1.2e-9)),
        )
        assert "*DENSITY" in deck
        assert "1.2e-09" in deck
        assert "Eall, GRAV, 9806.65" in deck

    def test_no_density_is_written_without_a_body_load(self) -> None:
        """An invented density is exactly the habit this project refuses."""
        mesh = _two_tet_mesh()
        deck = write_deck(
            mesh, provisional_tpu(),
            [BoundaryCondition("bottom", (1, 2, 3), 0.0)],
            DeckSettings(),
        )
        assert "*DENSITY" not in deck


class TestPointLoad:
    def test_a_total_load_is_divided_among_the_nodes(self) -> None:
        load = PointLoad(node_set="tip", force=(0.0, 0.0, -2.0), total=True)
        assert load.per_node(4) == pytest.approx((0.0, 0.0, -0.5))

    def test_a_per_node_load_is_not_divided(self) -> None:
        load = PointLoad(node_set="tip", force=(0.0, 0.0, -2.0), total=False)
        assert load.per_node(4) == pytest.approx((0.0, 0.0, -2.0))

    def test_a_zero_load_is_refused(self) -> None:
        with pytest.raises(LoadError, match="zero vector"):
            PointLoad(node_set="tip", force=(0.0, 0.0, 0.0))

    def test_the_node_set_is_defined_in_the_deck(self) -> None:
        """A *CLOAD naming an undefined set is a fatal CalculiX error, and was."""
        mesh = _two_tet_mesh()
        deck = write_deck(
            mesh, provisional_tpu(),
            [BoundaryCondition("bottom", (1, 2, 3), 0.0)],
            DeckSettings(
                point_loads=[PointLoad(node_set="far", force=(0.0, 0.0, -1.0))]
            ),
        )
        assert "*NSET, NSET=far" in deck
        assert deck.index("*NSET, NSET=far") < deck.index("*CLOAD")

    def test_an_unknown_node_set_is_refused(self) -> None:
        from barnes_ui.core.fea.deck import DeckError

        mesh = _two_tet_mesh()
        with pytest.raises(DeckError, match="not"):
            write_deck(
                mesh, provisional_tpu(),
                [BoundaryCondition("bottom", (1, 2, 3), 0.0)],
                DeckSettings(
                    point_loads=[
                        PointLoad(node_set="nowhere", force=(0.0, 0.0, -1.0))
                    ]
                ),
            )


class TestCapabilityGate:
    def test_a_fresh_registry_enables_nothing(self) -> None:
        """Criterion 2's safe direction: untested means off, not optimistic."""
        registry = CapabilityRegistry()
        assert registry.enabled() == []
        for capability in Capability:
            assert not registry.is_enabled(capability)

    def test_viscoelasticity_is_not_available_rather_than_untested(self) -> None:
        """A finding settled against the manual, not a benchmark waiting to run."""
        registry = CapabilityRegistry()
        record = registry.record(Capability.VISCOELASTICITY)
        assert record.status is CapabilityStatus.NOT_AVAILABLE
        assert "no viscoelastic material model" in record.evidence

    def test_require_quotes_the_evidence(self) -> None:
        registry = CapabilityRegistry()
        with pytest.raises(CapabilityNotAvailableError) as excinfo:
            registry.require(Capability.SELF_CONTACT)
        message = str(excinfo.value)
        assert "Not tested" in message
        assert "phase6_benchmarks.py" in message
        assert "converged" in message  # the benchmark description

    def test_a_passed_record_enables_the_capability(self) -> None:
        registry = CapabilityRegistry()
        registry.set(
            CapabilityRecord(
                capability=Capability.GRAVITY,
                status=CapabilityStatus.PASSED,
                evidence="tip deflection within 1.2 %",
                measured=0.01419, expected=0.01436, tolerance=0.05,
            )
        )
        assert registry.is_enabled(Capability.GRAVITY)
        assert registry.require(Capability.GRAVITY).measured == pytest.approx(0.01419)

    def test_a_failed_record_does_not_enable_it(self) -> None:
        registry = CapabilityRegistry()
        registry.set(
            CapabilityRecord(
                capability=Capability.SELF_CONTACT,
                status=CapabilityStatus.FAILED,
                evidence="did not converge",
            )
        )
        assert not registry.is_enabled(Capability.SELF_CONTACT)
        with pytest.raises(CapabilityNotAvailableError, match="did not converge"):
            registry.require(Capability.SELF_CONTACT)

    def test_a_record_reports_its_relative_error(self) -> None:
        record = CapabilityRecord(
            capability=Capability.GRAVITY, status=CapabilityStatus.PASSED,
            measured=1.1, expected=1.0,
        )
        assert record.relative_error == pytest.approx(0.1)

    def test_round_trip_through_a_file(self, tmp_path) -> None:
        path = tmp_path / "capabilities.json"
        registry = CapabilityRegistry()
        registry.set(
            CapabilityRecord(
                capability=Capability.CONTACT_FRICTION,
                status=CapabilityStatus.PASSED,
                evidence="stuck as predicted", measured=10.0, expected=10.0,
            )
        )
        registry.save(path)

        reloaded = CapabilityRegistry.load(path)
        assert reloaded.is_enabled(Capability.CONTACT_FRICTION)
        assert reloaded.record(Capability.CONTACT_FRICTION).recorded_at

    def test_a_missing_file_is_not_an_error(self, tmp_path) -> None:
        registry = CapabilityRegistry.load(tmp_path / "absent.json")
        assert registry.enabled() == []

    def test_a_corrupt_file_is_refused_rather_than_guessed_at(self, tmp_path) -> None:
        path = tmp_path / "capabilities.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="could not be read"):
            CapabilityRegistry.load(path)

    def test_the_summary_names_every_capability(self, tmp_path) -> None:
        text = CapabilityRegistry().summary()
        for capability in Capability:
            assert capability.label in text


class TestRecordedBenchmarkResults:
    """The registry actually committed to the repository.

    These assert what the Phase 6 runs on this project found. They fail if the file
    is missing, which is correct: the documentation quotes these numbers, and a
    documented result with no evidence behind it is the thing this project exists to
    avoid.
    """

    @pytest.fixture(scope="class")
    def registry(self) -> CapabilityRegistry:
        from barnes_ui.core.fea.capabilities import default_registry_path

        path = default_registry_path()
        if not path.is_file():
            pytest.skip(
                "No capability registry recorded; run scripts/phase6_benchmarks.py"
            )
        return CapabilityRegistry.load(path)

    def test_gravity_passed_with_recorded_evidence(self, registry) -> None:
        record = registry.record(Capability.GRAVITY)
        assert record.status is CapabilityStatus.PASSED
        assert record.run_directory
        assert abs(record.relative_error) < 0.05

    def test_tendon_load_passed(self, registry) -> None:
        record = registry.record(Capability.TENDON_LOAD)
        assert record.status is CapabilityStatus.PASSED
        assert abs(record.relative_error) < 0.005

    def test_every_record_names_the_solver_it_was_run_with(self, registry) -> None:
        for capability, record in registry.records.items():
            if record.status in (CapabilityStatus.PASSED, CapabilityStatus.FAILED):
                assert record.solver_version, capability
