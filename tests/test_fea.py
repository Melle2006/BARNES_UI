"""Phase 3 finite element tests.

Covers the Phase 3 acceptance criteria that can be checked without a CalculiX binary,
which is most of them. The two that cannot are noted explicitly in the module docstring
rather than silently skipped:

* criterion 2, the hyperelastic single-element uniaxial test, needs a finite-strain
  solver. The material law itself is verified against closed form in ``test_material``;
  what is missing is confirmation that CalculiX integrates it correctly.
* criterion 7, the reduced-order versus FEA discrepancy on the real flexure, needs a
  production run.

Criterion 6 -- FEA disabled with an installation message and no fallback when CalculiX
is absent -- is tested here against the *actual current state* of the machine, which is
the strongest form of that test available.
"""

from __future__ import annotations

import numpy as np
import pytest

from barnes_ui.core.fea.convergence import ConvergenceStudy, run_mesh_convergence
from barnes_ui.core.fea.deck import (
    BoundaryCondition,
    DeckError,
    DeckSettings,
    write_deck,
)
from barnes_ui.core.fea.meshing import MeshSettings, MeshingError, generate_mesh
from barnes_ui.core.fea.results import (
    CAVEAT_NOT_CONVERGED,
    CAVEAT_NO_MESH_STUDY,
    ConvergenceReport,
    FeaResult,
    parse_convergence,
    parse_dat_reactions,
)
from barnes_ui.core.fea.solver import (
    SolverNotAvailableError,
    find_solver,
    installation_instructions,
)
from barnes_ui.core.material.models import (
    HyperelasticModel,
    MaterialModelKind,
    provisional_tpu,
)
from barnes_ui.core.provenance import Provenance

from conftest import requires_kernel

CANTILEVER = (40.0, 4.0, 2.0)   # length, width, height in mm
E_TEST, NU_TEST, FORCE = 200.0, 0.3, 0.5
TOL = 1.0e-6


def _box(dx: float, dy: float, dz: float):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), dx, dy, dz).Shape()


@pytest.fixture(scope="module")
def cantilever_shape():
    pytest.importorskip("OCP")
    return _box(*CANTILEVER)


@pytest.fixture(scope="module")
def coarse_mesh(cantilever_shape):
    pytest.importorskip("gmsh")
    return generate_mesh(cantilever_shape, MeshSettings(elements_through_thickness=2))


# ---------------------------------------------------------------------------
# Solver discovery -- Phase 3 criterion 6
# ---------------------------------------------------------------------------

class TestSolverDiscovery:
    def test_missing_solver_returns_none_rather_than_raising(self) -> None:
        """Absence is a normal state the UI must present, not an exception."""
        result = find_solver("/definitely/not/a/real/path/ccx")
        assert result is None

    def test_installation_instructions_are_actionable(self) -> None:
        """'Install CalculiX' is not actionable to someone who has not done it."""
        text = installation_instructions()
        assert "FreeCAD" in text
        assert "BARNES_UI_CCX" in text
        assert "ccx" in text

    def test_instructions_state_that_nothing_is_substituted(self) -> None:
        """Criterion 6: no silent fallback to the reduced-order model."""
        text = installation_instructions().lower()
        assert "reduced-order" in text
        assert "not substitute" in text or "will not" in text

    def test_run_without_a_solver_raises_with_instructions(self) -> None:
        from barnes_ui.core.fea.runner import run_analysis

        with pytest.raises(SolverNotAvailableError, match="FreeCAD"):
            run_analysis("** empty deck", mesh=None, material=provisional_tpu(),
                         solver=None)


# ---------------------------------------------------------------------------
# Meshing
# ---------------------------------------------------------------------------

@requires_kernel
class TestMeshing:
    def test_produces_second_order_tetrahedra_by_default(self, coarse_mesh) -> None:
        """C3D10, because first-order tets lock in a near-incompressible material."""
        assert coarse_mesh.second_order
        assert coarse_mesh.calculix_element_type == "C3D10"
        assert coarse_mesh.elements.shape[1] == 10

    def test_nodes_stay_inside_the_geometry(self, coarse_mesh) -> None:
        low = coarse_mesh.nodes.min(axis=0)
        high = coarse_mesh.nodes.max(axis=0)
        assert np.allclose(low, [0.0, 0.0, 0.0], atol=1e-6)
        assert np.allclose(high, list(CANTILEVER), atol=1e-6)

    def test_connectivity_indices_are_in_range(self, coarse_mesh) -> None:
        assert coarse_mesh.elements.min() >= 0
        assert coarse_mesh.elements.max() < coarse_mesh.node_count

    def test_no_inverted_elements(self, coarse_mesh) -> None:
        """An inverted element either stops the solver or poisons the result."""
        assert coarse_mesh.quality["negative_volume_count"] == 0.0

    def test_mesh_volume_matches_the_solid(self, coarse_mesh) -> None:
        corners = coarse_mesh.elements[:, :4]
        p0, p1, p2, p3 = (coarse_mesh.nodes[corners[:, i]] for i in range(4))
        volumes = np.einsum("ij,ij->i", p1 - p0, np.cross(p2 - p0, p3 - p0)) / 6.0
        expected = CANTILEVER[0] * CANTILEVER[1] * CANTILEVER[2]
        assert abs(volumes.sum()) == pytest.approx(expected, rel=1e-6)

    def test_element_size_follows_the_thickness_rule(self, cantilever_shape) -> None:
        mesh = generate_mesh(
            cantilever_shape, MeshSettings(elements_through_thickness=4)
        )
        assert mesh.element_size == pytest.approx(CANTILEVER[2] / 4.0)

    def test_refinement_increases_element_count(self, cantilever_shape) -> None:
        coarse = generate_mesh(cantilever_shape, MeshSettings(elements_through_thickness=2))
        fine = generate_mesh(cantilever_shape, MeshSettings(elements_through_thickness=4))
        assert fine.element_count > coarse.element_count

    def test_first_order_carries_a_locking_warning(self, cantilever_shape) -> None:
        """If someone switches it on, the mesh must say what it costs."""
        mesh = generate_mesh(
            cantilever_shape,
            MeshSettings(elements_through_thickness=2, second_order=False),
        )
        assert mesh.calculix_element_type == "C3D4"
        assert any("lock" in note.lower() for note in mesh.notes)

    def test_surface_node_sets_are_produced(self, coarse_mesh) -> None:
        """A box has six faces, each of which must be selectable for a BC."""
        assert len(coarse_mesh.node_sets) == 6


# ---------------------------------------------------------------------------
# Deck generation
# ---------------------------------------------------------------------------

@requires_kernel
class TestDeckGeneration:
    def _deck(self, mesh, material=None, settings=None):
        sets = sorted(mesh.node_sets)
        return write_deck(
            mesh,
            material or provisional_tpu(12.0),
            [
                BoundaryCondition(sets[0], (1, 2, 3), 0.0, "fixed root"),
                BoundaryCondition(sets[1], (3,), -0.5, "prescribed"),
            ],
            settings or DeckSettings(reaction_sets=[sets[0]]),
        )

    def test_contains_the_required_keywords(self, coarse_mesh) -> None:
        deck = self._deck(coarse_mesh)
        for keyword in ("*NODE", "*ELEMENT", "*MATERIAL", "*SOLID SECTION",
                        "*STEP", "*STATIC", "*BOUNDARY", "*END STEP"):
            assert keyword in deck, f"{keyword} missing from the deck"

    def test_nlgeom_is_requested_for_finite_strain(self, coarse_mesh) -> None:
        assert "*STEP, NLGEOM" in self._deck(coarse_mesh)

    def test_nlgeom_can_be_turned_off_for_the_linear_benchmark(self, coarse_mesh) -> None:
        sets = sorted(coarse_mesh.node_sets)
        deck = self._deck(
            coarse_mesh,
            settings=DeckSettings(nlgeom=False, reaction_sets=[sets[0]]),
        )
        assert "NLGEOM" not in deck

    def test_node_and_element_numbering_is_one_based(self, coarse_mesh) -> None:
        """CalculiX numbers from 1; the mesh stores zero-based indices."""
        deck = self._deck(coarse_mesh)
        lines = deck.splitlines()
        node_start = lines.index("*NODE, NSET=Nall") + 1
        assert lines[node_start].split(",")[0].strip() == "1"

    def test_every_node_appears(self, coarse_mesh) -> None:
        deck = self._deck(coarse_mesh)
        lines = deck.splitlines()
        node_start = lines.index("*NODE, NSET=Nall") + 1
        count = 0
        for line in lines[node_start:]:
            if line.startswith("*"):
                break
            count += 1
        assert count == coarse_mesh.node_count

    def test_reaction_print_is_requested(self, coarse_mesh) -> None:
        """Without it the run yields a deformed shape and no force at all."""
        deck = self._deck(coarse_mesh)
        assert "*NODE PRINT" in deck
        assert "RF" in deck

    def test_material_provenance_is_recorded_in_the_deck(self, coarse_mesh) -> None:
        """The archived deck must carry how trustworthy its material was."""
        deck = self._deck(coarse_mesh)
        assert "Material provenance: Assumption" in deck
        assert "CAVEAT:" in deck

    def test_neo_hookean_writes_c10_and_d1(self, coarse_mesh) -> None:
        deck = self._deck(coarse_mesh)
        assert "*HYPERELASTIC, NEO HOOKE" in deck

    def test_compressibility_parameter_matches_the_poisson_ratio(self, coarse_mesh) -> None:
        """D1 = 2/K with K = mu*(2+2nu)/(3-6nu). Checked by hand here.

        For the provisional 12 MPa material: mu0 = 4.0013 MPa, nu = 0.4995, so
        K = 4.0013 * 999.667 = 4000.0 MPa and D1 = 2/4000 = 0.0005.
        """
        material = provisional_tpu(12.0)
        deck = self._deck(coarse_mesh, material=material)
        line = next(line for line in deck.splitlines() if "D1 =" in line)
        reported = float(line.split("D1 =")[1].split("corresponds")[0].strip())

        nu = material.poisson_ratio
        bulk = material.initial_shear_modulus * (2 + 2 * nu) / (3 - 6 * nu)
        assert reported == pytest.approx(2.0 / bulk, rel=1e-9)
        assert reported == pytest.approx(0.0005, rel=1e-3)

    def test_mooney_rivlin_writes_three_constants(self, coarse_mesh) -> None:
        material = HyperelasticModel(
            MaterialModelKind.MOONEY_RIVLIN, (1.0, 0.25),
            provenance=Provenance.ANALYTICAL_ESTIMATE, caveats=(),
        )
        deck = self._deck(coarse_mesh, material=material)
        assert "*HYPERELASTIC, MOONEY-RIVLIN" in deck

    def test_linear_elastic_writes_elastic_not_hyperelastic(self, coarse_mesh) -> None:
        material = HyperelasticModel(
            MaterialModelKind.LINEAR_ELASTIC, (200.0, 0.3),
            provenance=Provenance.ANALYTICAL_ESTIMATE, caveats=(),
        )
        deck = self._deck(coarse_mesh, material=material)
        assert "*ELASTIC" in deck
        assert "*HYPERELASTIC" not in deck

    def test_incompressible_poisson_ratio_is_refused(self, coarse_mesh) -> None:
        """nu = 0.5 implies an infinite bulk modulus and a zero D1."""
        material = HyperelasticModel(
            MaterialModelKind.NEO_HOOKEAN, (2.0,), poisson_ratio=0.5,
            provenance=Provenance.ANALYTICAL_ESTIMATE, caveats=(),
        )
        with pytest.raises(DeckError, match="infinite bulk modulus"):
            self._deck(coarse_mesh, material=material)

    def test_unconstrained_model_is_refused(self, coarse_mesh) -> None:
        with pytest.raises(DeckError, match="No boundary conditions"):
            write_deck(coarse_mesh, provisional_tpu(), [], DeckSettings())

    def test_unknown_node_set_is_refused(self, coarse_mesh) -> None:
        with pytest.raises(DeckError, match="not in the mesh"):
            write_deck(
                coarse_mesh, provisional_tpu(),
                [BoundaryCondition("no_such_set", (1, 2, 3))], DeckSettings(),
            )

    def test_tet10_nodes_are_reordered_for_calculix(self, coarse_mesh) -> None:
        """Gmsh and CalculiX disagree on mid-side node positions 8 and 9.

        Regression for the first real submission, which failed on every element with
        "*ERROR in e_c3d: nonpositive jacobian" despite all corner volumes being
        positive. A 10-node tet's Jacobian depends on all ten nodes, so two swapped
        mid-edge nodes fold the element.
        """
        from barnes_ui.core.fea.deck import _GMSH_TO_CALCULIX_TET10

        assert _GMSH_TO_CALCULIX_TET10 == (0, 1, 2, 3, 4, 5, 6, 7, 9, 8)

        deck = self._deck(coarse_mesh)
        lines = deck.splitlines()
        start = next(
            i for i, line in enumerate(lines) if line.startswith("*ELEMENT")
        ) + 1
        # Each C3D10 row spans two lines: 8 ids then 2.
        first = [v.strip() for v in lines[start].rstrip(",").split(",")][1:]
        second = [v.strip() for v in lines[start + 1].split(",")]
        written = [int(v) - 1 for v in first + second]

        expected = [
            int(coarse_mesh.elements[0][i]) for i in _GMSH_TO_CALCULIX_TET10
        ]
        assert written == expected

    def test_first_order_elements_are_not_reordered(self, cantilever_shape) -> None:
        """The permutation applies to C3D10 only; C3D4 has no mid-side nodes."""
        mesh = generate_mesh(
            cantilever_shape,
            MeshSettings(elements_through_thickness=2, second_order=False),
        )
        sets = sorted(mesh.node_sets)
        deck = write_deck(
            mesh, provisional_tpu(),
            [BoundaryCondition(sets[0], (1, 2, 3), 0.0)],
            DeckSettings(),
        )
        lines = deck.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("*ELEMENT")) + 1
        written = [int(v) - 1 for v in lines[start].split(",")[1:]]
        assert written == [int(v) for v in mesh.elements[0]]


@requires_kernel
class TestRigidBodyDriving:
    """Prescribing a joint rotation, and the bug that made it silently do nothing."""

    def _deck_with_body(self, mesh):
        from barnes_ui.core.fea.deck import RigidBody

        sets = sorted(mesh.node_sets)
        body = RigidBody(node_set=sets[1], reference_point=(0.0, 0.0, 0.0), name="distal")
        return write_deck(
            mesh, provisional_tpu(),
            [
                BoundaryCondition(sets[0], (1, 2, 3), 0.0, "fixed"),
                BoundaryCondition("distal_rot", (1,), 0.1, "prescribed rotation"),
            ],
            DeckSettings(rigid_bodies=[body], reaction_sets=["distal_rot"]),
        ), body, sets[1]

    def test_rigid_body_member_set_is_written(self, coarse_mesh) -> None:
        """The bug: the tied set was never defined, so nothing was tied.

        CalculiX only warned, then solved a model with no load and reported CONVERGED
        with every displacement and reaction exactly zero.
        """
        deck, _, member_set = self._deck_with_body(coarse_mesh)
        assert f"*NSET, NSET={member_set}" in deck

    def test_rigid_body_card_is_written_with_both_nodes(self, coarse_mesh) -> None:
        deck, body, member_set = self._deck_with_body(coarse_mesh)
        assert (
            f"*RIGID BODY, NSET={member_set}, REF NODE={body.reference_node}, "
            f"ROT NODE={body.rotation_node}" in deck
        )

    def test_reference_nodes_are_appended_after_the_mesh(self, coarse_mesh) -> None:
        _, body, _ = self._deck_with_body(coarse_mesh)
        assert body.reference_node == coarse_mesh.node_count + 1
        assert body.rotation_node == coarse_mesh.node_count + 2

    def test_generated_sets_are_valid_bc_targets(self, coarse_mesh) -> None:
        """'distal_rot' is not a mesh surface but must still be constrainable."""
        deck, _, _ = self._deck_with_body(coarse_mesh)
        assert "*NSET, NSET=distal_rot" in deck
        assert "distal_rot, 1, 1" in deck

    def test_rigid_body_on_an_unknown_set_is_refused(self, coarse_mesh) -> None:
        from barnes_ui.core.fea.deck import RigidBody

        sets = sorted(coarse_mesh.node_sets)
        with pytest.raises(DeckError, match="not in the mesh"):
            write_deck(
                coarse_mesh, provisional_tpu(),
                [BoundaryCondition(sets[0], (1, 2, 3), 0.0)],
                DeckSettings(
                    rigid_bodies=[
                        RigidBody(node_set="nope", reference_point=(0, 0, 0))
                    ]
                ),
            )


# ---------------------------------------------------------------------------
# Result handling -- Phase 3 criterion 5
# ---------------------------------------------------------------------------

class TestResultHandling:
    def test_non_converged_run_is_not_trustworthy(self) -> None:
        result = FeaResult(convergence=ConvergenceReport(converged=False))
        assert not result.is_trustworthy

    def test_non_converged_run_refuses_to_report_a_moment(self) -> None:
        """Criterion 5: a failed run displays no result at all.

        Returning a number with a caveat attached would leave it on screen for someone
        to read, so this raises instead.
        """
        result = FeaResult(
            convergence=ConvergenceReport(converged=False),
            reaction_moments={"root": np.array([1.0, 2.0, 3.0])},
        )
        with pytest.raises(ValueError, match="did not converge"):
            result.tagged_moment("root", np.array([1.0, 0.0, 0.0]))

    def test_converged_run_reports_a_tagged_moment(self) -> None:
        result = FeaResult(
            convergence=ConvergenceReport(converged=True, increments_completed=10),
            reaction_moments={"root": np.array([5.0, 0.0, 0.0])},
            material_provenance=Provenance.ANALYTICAL_ESTIMATE,
        )
        tagged = result.tagged_moment("root", np.array([1.0, 0.0, 0.0]))
        assert tagged.value == pytest.approx(5.0)
        assert tagged.unit == "N.mm"

    def test_fea_result_is_never_stronger_than_its_material(self) -> None:
        """An FEA run on assumed material parameters is still an assumption."""
        result = FeaResult(
            convergence=ConvergenceReport(converged=True),
            reaction_moments={"root": np.array([5.0, 0.0, 0.0])},
            material_provenance=Provenance.UNVALIDATED_ASSUMPTION,
        )
        tagged = result.tagged_moment("root", np.array([1.0, 0.0, 0.0]))
        assert tagged.provenance is Provenance.UNVALIDATED_ASSUMPTION

    def test_missing_mesh_study_is_a_caveat(self) -> None:
        result = FeaResult(convergence=ConvergenceReport(converged=True))
        assert CAVEAT_NO_MESH_STUDY in result.caveats()

    def test_non_convergence_is_a_caveat(self) -> None:
        result = FeaResult(convergence=ConvergenceReport(converged=False))
        assert CAVEAT_NOT_CONVERGED in result.caveats()

    def test_convergence_parser_detects_a_clean_finish(self) -> None:
        log = "increment 1\nconvergence\nincrement 2\nconvergence\nJob finished\n"
        report = parse_convergence(log)
        assert report.converged

    def test_convergence_parser_treats_errors_as_failure(self) -> None:
        log = "increment 1\n*ERROR in e_c3d: nonpositive jacobian\nJob finished\n"
        report = parse_convergence(log)
        assert not report.converged
        assert report.errors

    def test_solver_residual_lines_are_not_mistaken_for_errors(self) -> None:
        """CalculiX's linear solver prints residuals on lines reading 'error  1e-09'.

        Regression: matching bare 'error' declared a perfectly healthy run
        non-converged on the strength of its own convergence residuals -- three
        decreasing residuals, a clean 'Job finished', correct reactions, verdict
        failure. The mirror image of the bug this module exists to prevent.
        """
        log = (
            " STEP            1\n"
            "    - iteration 1 :\n"
            "         error                                  9.2425e-09\n"
            "    - iteration 2 :\n"
            "         error                                  3.9084e-11\n"
            "\n Job finished\n"
        )
        report = parse_convergence(log)
        assert report.converged
        assert report.errors == []

    def test_a_linear_run_without_increment_markers_counts_as_one(self) -> None:
        """A linear static prints no 'increment' lines; '0 of 0' would be useless."""
        report = parse_convergence(" STEP 1\n Job finished\n")
        assert report.converged
        assert report.increments_completed >= 1

    def test_null_solution_is_detected(self) -> None:
        """Converged, but nothing happened -- a correct answer to no problem."""
        result = FeaResult(
            convergence=ConvergenceReport(converged=True, increments_completed=8),
            reaction_forces={"driven": np.zeros(3)},
            displacements=np.zeros((100, 3)),
        )
        assert result.is_null_solution
        assert not result.is_trustworthy

    def test_null_solution_refuses_to_report_a_moment(self) -> None:
        result = FeaResult(
            convergence=ConvergenceReport(converged=True),
            reaction_forces={"driven": np.zeros(3)},
            displacements=np.zeros((10, 3)),
            reaction_moments={"driven": np.zeros(3)},
        )
        with pytest.raises(ValueError, match="null problem"):
            result.tagged_moment("driven", np.array([1.0, 0.0, 0.0]))

    def test_a_real_solution_is_not_flagged_as_null(self) -> None:
        result = FeaResult(
            convergence=ConvergenceReport(converged=True),
            reaction_forces={"driven": np.array([0.0, 0.0, 0.5])},
            displacements=np.full((10, 3), 0.01),
        )
        assert not result.is_null_solution
        assert result.is_trustworthy

    def test_convergence_parser_defaults_to_not_converged(self) -> None:
        """An ambiguous log must read as failure, not success.

        Wrongly trusting a bad solve costs far more than re-running a good one.
        """
        assert not parse_convergence("some unrelated output").converged

    def test_dat_parser_returns_empty_for_a_missing_file(self, tmp_path) -> None:
        assert parse_dat_reactions(tmp_path / "absent.dat") == {}

    def test_dat_parser_reads_a_total_force_block(self, tmp_path) -> None:
        path = tmp_path / "job.dat"
        path.write_text(
            "\n total force (fx,fy,fz) for set ROOT and time  0.1000000E+01\n"
            "\n  -1.234000E+00  5.678000E-01  9.000000E+00\n",
            encoding="utf-8",
        )
        reactions = parse_dat_reactions(path)
        assert "ROOT" in reactions
        assert reactions["ROOT"][0] == pytest.approx(-1.234)
        assert reactions["ROOT"][2] == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# Verification backend -- Phase 3 criteria 1 and 4
# ---------------------------------------------------------------------------

@requires_kernel
class TestVerificationBackend:
    """An independently implemented solver, checked against beam theory."""

    @pytest.fixture(scope="class")
    def solution(self, cantilever_shape):
        pytest.importorskip("skfem")
        from barnes_ui.core.fea.verification import solve_linear_elastic

        length = CANTILEVER[0]
        mesh = generate_mesh(cantilever_shape, MeshSettings(elements_through_thickness=3))
        return mesh, solve_linear_elastic(
            mesh, E_TEST, NU_TEST,
            fixed_where=lambda x: x[0] < TOL,
            loaded_where=lambda x: x[0] > length - TOL,
            total_force=(0.0, 0.0, -FORCE),
        )

    def test_tip_deflection_matches_beam_theory(self, solution) -> None:
        """Phase 3 criterion 1: better than 2 per cent.

        The FE model is legitimately *stiffer* than beam theory, because a fully
        clamped end face restrains the Poisson contraction beam theory allows freely.
        Around half a per cent of the difference is that physics, not error.
        """
        from barnes_ui.core.fea.verification import cantilever_tip_deflection

        _, sol = solution
        length, width, height = CANTILEVER
        tip = abs(sol.displacement_at((length, width / 2, height / 2))[2])
        exact = cantilever_tip_deflection(FORCE, length, width, height, E_TEST, NU_TEST)
        assert tip == pytest.approx(exact, rel=0.02)

    def test_global_equilibrium(self, solution) -> None:
        """Phase 3 criterion 4: reaction equals applied load to better than 0.5 %."""
        _, sol = solution
        assert abs(sol.reaction_force[2]) == pytest.approx(FORCE, rel=0.005)

    def test_transverse_reactions_are_negligible(self, solution) -> None:
        """A purely vertical load must not produce in-plane reactions."""
        _, sol = solution
        assert abs(sol.reaction_force[0]) < 0.01 * FORCE
        assert abs(sol.reaction_force[1]) < 0.01 * FORCE

    def test_shear_term_is_included_in_the_reference(self) -> None:
        from barnes_ui.core.fea.verification import cantilever_tip_deflection

        length, width, height = CANTILEVER
        with_shear = cantilever_tip_deflection(
            FORCE, length, width, height, E_TEST, NU_TEST, include_shear=True
        )
        without = cantilever_tip_deflection(
            FORCE, length, width, height, E_TEST, NU_TEST, include_shear=False
        )
        assert with_shear > without

    def test_incompressible_material_is_refused(self, coarse_mesh) -> None:
        from barnes_ui.core.fea.verification import VerificationError, solve_linear_elastic

        with pytest.raises(VerificationError, match="incompressible"):
            solve_linear_elastic(
                coarse_mesh, E_TEST, 0.5,
                fixed_where=lambda x: x[0] < TOL,
                loaded_where=lambda x: x[0] > CANTILEVER[0] - TOL,
                total_force=(0.0, 0.0, -FORCE),
            )

    def test_unconstrained_model_is_refused(self, coarse_mesh) -> None:
        """Regression: an earlier DOF-mapping bug made this silently singular."""
        from barnes_ui.core.fea.verification import VerificationError, solve_linear_elastic

        with pytest.raises(VerificationError, match="rigid-body modes"):
            solve_linear_elastic(
                coarse_mesh, E_TEST, NU_TEST,
                fixed_where=lambda x: x[0] < -1000.0,     # selects nothing
                loaded_where=lambda x: x[0] > CANTILEVER[0] - TOL,
                total_force=(0.0, 0.0, -FORCE),
            )


# ---------------------------------------------------------------------------
# Mesh convergence -- Phase 3 criterion 3
# ---------------------------------------------------------------------------

class TestConvergenceStudy:
    def _study(self, values: list[float]) -> ConvergenceStudy:
        return run_mesh_convergence(
            lambda n: (values[n - 2], 100 * n, 300 * n, 1.0 / n),
            refinements=tuple(range(2, 2 + len(values))),
            quantity="test", unit="mm",
        )

    def test_detects_convergence(self) -> None:
        study = self._study([19.80, 19.89, 19.90, 19.901])
        assert study.is_converged(tolerance=0.02)
        assert study.final_change < 0.02

    def test_detects_non_convergence(self) -> None:
        study = self._study([10.0, 14.0, 18.0, 25.0])
        assert not study.is_converged(tolerance=0.02)
        assert any("NOT CONVERGED" in note for note in study.notes)

    def test_detects_monotonic_refinement(self) -> None:
        assert self._study([19.80, 19.89, 19.90, 19.901]).is_monotonic()

    def test_flags_oscillation(self) -> None:
        """Oscillation suggests mesh artefacts rather than smooth convergence."""
        study = self._study([19.0, 20.0, 19.2, 19.8])
        assert not study.is_monotonic()
        assert any("not monotonic" in note for note in study.notes)

    def test_richardson_extrapolation_on_a_converging_sequence(self) -> None:
        study = self._study([19.80, 19.89, 19.90, 19.901])
        estimate = study.richardson_estimate()
        assert estimate is not None
        assert 19.89 < estimate < 19.95

    def test_richardson_declines_on_a_stalled_sequence(self) -> None:
        """A meaningless extrapolation is worse than none."""
        study = self._study([5.0, 5.0, 5.0])
        assert study.richardson_estimate() is None

    def test_summary_includes_the_numbers(self) -> None:
        text = self._study([19.80, 19.89, 19.90, 19.901]).summary()
        assert "Monotonic" in text
        assert "Final change" in text
