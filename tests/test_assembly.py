"""Assembly import, joint definition and interference tests.

The placement tests use a generated assembly whose transforms are known exactly rather
than a reference file whose "correct" answer is itself a measurement. The requirement
is 0.01 mm; what is asserted below is six orders of magnitude tighter than that,
because an exactly known input deserves an exactly checkable output.

This does not substitute for checking a SolidWorks export -- see the docstring of
``scripts/make_reference_assembly.py``. It tests the reader, which is the half of the
chain that lives in this repository.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from barnes_ui.core.assembly.interference import (
    minimum_clearance,
    pair_interference,
    rotate_shape,
    sweep_interference,
)
from barnes_ui.core.assembly.joint import (
    AxisCandidate,
    Joint,
    JointError,
    UnconfirmedAxisError,
    axis_from_two_points,
    find_axis_candidates,
)
from barnes_ui.core.assembly.loader import load_step_assembly
from barnes_ui.core.assembly.model import Assembly, Placement
from barnes_ui.core.mechanics.curved_beam import JointAxis

from conftest import requires_kernel

#: Must match scripts/make_reference_assembly.py. Duplicated rather than imported so
#: that a change to the generator breaks a test instead of silently changing both
#: sides of the comparison.
PROXIMAL_SIZE = (12.0, 20.0, 10.0)
DISTAL_SIZE = (12.0, 18.0, 10.0)
STRAP_SIZE = (8.0, 10.0, 1.0)
JOINT_GAP = 6.0
DISTAL_FLEXION_DEG = 15.0

REFERENCE_ASSEMBLY = (
    Path(__file__).resolve().parents[1] / "reference_parts" / "pip_joint_assembly.step"
)

requires_reference_assembly = pytest.mark.skipif(
    not REFERENCE_ASSEMBLY.is_file(),
    reason="run scripts/make_reference_assembly.py to generate the reference assembly",
)


# ---------------------------------------------------------------- Placement maths


class TestPlacement:
    def test_identity_round_trip(self) -> None:
        identity = Placement.identity()
        assert identity.is_identity
        assert identity.apply_point((1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)

    def test_compose_matches_matrix_product(self) -> None:
        a = _rotation_placement(30.0, (0.0, 0.0, 1.0), (1.0, 2.0, 3.0))
        b = _rotation_placement(-12.0, (1.0, 0.0, 0.0), (-4.0, 0.5, 2.0))
        composed = a.compose(b)
        np.testing.assert_allclose(composed.matrix, a.matrix @ b.matrix, atol=1e-12)

    def test_inverse_undoes_the_placement(self) -> None:
        placement = _rotation_placement(47.0, (0.3, -0.5, 1.0), (7.0, -2.0, 11.0))
        point = (3.0, -1.0, 4.0)
        moved = placement.apply_point(point)
        back = placement.inverse().apply_point(moved)
        np.testing.assert_allclose(back, point, atol=1e-12)

    def test_refuses_a_scaled_transform(self) -> None:
        """A scaled instance is a different part, with a different stiffness."""
        matrix = np.eye(4)
        matrix[:3, :3] *= 1.5
        with pytest.raises(ValueError, match="scale or shear"):
            Placement.from_matrix(matrix)

    def test_refuses_a_mirrored_transform(self) -> None:
        matrix = np.eye(4)
        matrix[0, 0] = -1.0
        with pytest.raises(ValueError, match="mirror"):
            Placement.from_matrix(matrix)

    def test_max_point_deviation_catches_a_pure_rotation_error(self) -> None:
        """Comparing translations alone would call these two placements identical."""
        exact = Placement.identity()
        skewed = _rotation_placement(1.0, (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
        assert np.allclose(exact.translation, skewed.translation)
        # One degree over a 50 mm radius is about 0.87 mm.
        deviation = exact.max_point_deviation(skewed, radius=50.0)
        assert 0.5 < deviation < 1.5


def _rotation_placement(angle_deg: float, axis, translation) -> Placement:
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    angle = math.radians(angle_deg)
    cross = np.array([
        [0.0, -axis[2], axis[1]],
        [axis[2], 0.0, -axis[0]],
        [-axis[1], axis[0], 0.0],
    ])
    rotation = (
        np.eye(3) * math.cos(angle)
        + math.sin(angle) * cross
        + (1 - math.cos(angle)) * np.outer(axis, axis)
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = translation
    return Placement.from_matrix(matrix)


# ------------------------------------------------------------------ Import


@requires_kernel
@requires_reference_assembly
class TestAssemblyImport:
    @pytest.fixture(scope="class")
    def assembly(self) -> Assembly:
        return load_step_assembly(REFERENCE_ASSEMBLY)

    def test_component_tree_is_preserved(self, assembly: Assembly) -> None:
        names = {c.name for c in assembly.parts()}
        assert names == {"proximal_phalanx", "distal_phalanx", "flexure_strap"}
        assert assembly.part_count == 3
        assert len(assembly.roots) == 1
        assert assembly.roots[0].name == "pip_joint"

    def test_each_component_has_its_own_volume(self, assembly: Assembly) -> None:
        """Phase 4 criterion 1's other half: components are separate, not merged."""
        volumes = {c.name: c.volume for c in assembly.parts()}
        assert volumes["proximal_phalanx"] == pytest.approx(math.prod(PROXIMAL_SIZE), rel=1e-9)
        assert volumes["distal_phalanx"] == pytest.approx(math.prod(DISTAL_SIZE), rel=1e-9)
        assert volumes["flexure_strap"] == pytest.approx(math.prod(STRAP_SIZE), rel=1e-9)

    def test_placement_survives_the_round_trip(self, assembly: Assembly) -> None:
        """Phase 4 criterion 1: placement accurate to better than 0.01 mm.

        Asserted against the exact transform the generator wrote, over a 50 mm radius
        so that a rotation error cannot hide behind a matching translation.
        """
        axis_point = (0.0, PROXIMAL_SIZE[1] + 0.5 * JOINT_GAP, 0.5 * PROXIMAL_SIZE[2])
        expected = _about_axis(
            DISTAL_FLEXION_DEG, (1.0, 0.0, 0.0), axis_point,
            then_translate=(0.0, PROXIMAL_SIZE[1] + JOINT_GAP, 0.0),
        )
        distal = assembly.find("pip_joint/distal_phalanx")
        assert distal is not None
        deviation = distal.placement.max_point_deviation(expected, radius=50.0)
        assert deviation < 1.0e-5, (
            f"placement deviates by {deviation:.3e} mm over a 50 mm radius"
        )

    def test_units_are_declared_not_assumed(self, assembly: Assembly) -> None:
        assert assembly.unit.symbol == "mm"
        assert assembly.unit_confidence.is_trustworthy

    def test_a_single_part_file_loads_as_a_one_component_assembly(
        self, box_step: Path
    ) -> None:
        single = load_step_assembly(box_step)
        assert single.part_count == 1


def _about_axis(angle_deg, axis_dir, axis_point, then_translate) -> Placement:
    rotate = _rotation_placement(angle_deg, axis_dir, (0.0, 0.0, 0.0))
    point = np.asarray(axis_point, dtype=float)
    rotation = np.asarray(rotate.rotation, dtype=float)
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = point - rotation @ point + np.asarray(then_translate, dtype=float)
    return Placement.from_matrix(matrix)


# ------------------------------------------------------------------- Joints


class TestJointDefinition:
    def _joint(self, **kwargs) -> Joint:
        defaults = dict(name="PIP", proximal=(0,), distal=(1,))
        defaults.update(kwargs)
        return Joint(**defaults)

    def test_refuses_a_component_on_both_sides(self) -> None:
        with pytest.raises(JointError, match="both sides"):
            Joint(name="PIP", proximal=(0, 1), distal=(1,))

    def test_refuses_an_empty_range(self) -> None:
        with pytest.raises(JointError, match="empty range"):
            self._joint(minimum_angle=1.0, maximum_angle=0.5)

    def test_axis_is_unusable_until_confirmed(self) -> None:
        """The central rule: a suggested axis is a guess, and guesses need a human."""
        joint = self._joint()
        with pytest.raises(UnconfirmedAxisError, match="no axis"):
            joint.require_axis()

        joint.set_axis(JointAxis((0, 0, 0), (1, 0, 0)), source="typed from the drawing")
        with pytest.raises(UnconfirmedAxisError, match="unconfirmed"):
            joint.require_axis()

        joint.confirm(by="test")
        assert joint.require_axis().direction == (1, 0, 0)
        assert joint.caveats() == ()

    def test_an_unconfirmed_joint_carries_a_caveat(self) -> None:
        joint = self._joint()
        joint.set_axis(JointAxis((0, 0, 0), (1, 0, 0)), source="guessed")
        assert any(c.key == "unconfirmed_axis" for c in joint.caveats())

    def test_axis_source_must_say_something(self) -> None:
        joint = self._joint()
        with pytest.raises(JointError, match="stated source"):
            joint.set_axis(JointAxis((0, 0, 0), (1, 0, 0)), source="   ")

    def test_proposing_a_candidate_leaves_it_unconfirmed(self) -> None:
        joint = self._joint()
        joint.propose(
            AxisCandidate(
                origin=(1.0, 2.0, 3.0), direction=(0.0, 0.0, 1.0),
                supporting_area=50.0, face_count=2, radii=(2.5,), axial_extent=8.0,
            )
        )
        assert joint.axis is not None
        assert not joint.confirmed
        assert "suggested from geometry" in joint.axis_source

    def test_two_points_define_an_axis(self) -> None:
        axis = axis_from_two_points((0.0, 0.0, 0.0), (0.0, 0.0, 4.0))
        assert axis.direction == pytest.approx((0.0, 0.0, 1.0))

    def test_coincident_points_are_refused(self) -> None:
        with pytest.raises(JointError, match="coincident"):
            axis_from_two_points((1.0, 1.0, 1.0), (1.0, 1.0, 1.0))

    def test_clamp_and_contains(self) -> None:
        joint = self._joint(minimum_angle=0.0, maximum_angle=math.radians(90.0))
        assert joint.clamp(-1.0) == 0.0
        assert joint.clamp(10.0) == pytest.approx(math.radians(90.0))
        assert joint.contains(math.radians(45.0))
        assert not joint.contains(math.radians(91.0))


@requires_kernel
class TestAxisCandidates:
    def test_a_bore_is_found_and_ranked_above_a_small_hole(self) -> None:
        """Ranking by supporting area prefers a bearing surface to a fastener hole."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

        block = BRepPrimAPI_MakeBox(gp_Pnt(-10, -10, 0), 20.0, 20.0, 10.0).Shape()
        bore = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(0, 0, -1), gp_Dir(0, 0, 1)), 4.0, 12.0
        ).Shape()
        screw = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(7, 7, -1), gp_Dir(0, 0, 1)), 1.0, 12.0
        ).Shape()
        shape = BRepAlgoAPI_Cut(BRepAlgoAPI_Cut(block, bore).Shape(), screw).Shape()

        candidates = find_axis_candidates([shape])
        assert len(candidates) >= 2
        best = candidates[0]
        assert best.direction == pytest.approx((0.0, 0.0, 1.0)) or \
            best.direction == pytest.approx((0.0, 0.0, -1.0))
        assert best.radii[0] == pytest.approx(4.0, abs=1e-9)
        # The 4 mm bore has sixteen times the circumference-times-height of the 1 mm
        # hole, so area ranking has to put it first.
        assert best.supporting_area > candidates[1].supporting_area

    def test_a_block_with_no_cylinders_yields_no_candidates(self) -> None:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

        assert find_axis_candidates([BRepPrimAPI_MakeBox(5.0, 5.0, 5.0).Shape()]) == []


# ------------------------------------------------------------- Interference


@requires_kernel
class TestInterference:
    def _boxes(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt

        fixed = BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, -5), 10.0, 10.0, 10.0).Shape()
        arm = BRepPrimAPI_MakeBox(gp_Pnt(-1, 5.5, -1), 2.0, 10.0, 2.0).Shape()
        return fixed, arm

    def test_separated_solids_report_zero_overlap_and_a_real_clearance(self) -> None:
        fixed, arm = self._boxes()
        assert pair_interference(fixed, arm) == 0.0
        assert minimum_clearance(fixed, arm) == pytest.approx(0.5, abs=1e-9)

    def test_overlap_volume_is_exact_for_boxes(self) -> None:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt

        a = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
        b = BRepPrimAPI_MakeBox(gp_Pnt(8.0, 0.0, 0.0), 10.0, 10.0, 10.0).Shape()
        assert pair_interference(a, b) == pytest.approx(2.0 * 10.0 * 10.0, rel=1e-9)

    def test_sweep_detects_interference_at_a_known_bad_angle(self) -> None:
        """Phase 4 criterion 4, on a configuration whose answer is arithmetic.

        The arm starts 0.5 mm clear of the block and swings about X through the
        origin. By 90 degrees it has rotated down into the block's own volume, so
        interference is certain; near 0 degrees it is certain there is none.
        """
        fixed, arm = self._boxes()
        axis = JointAxis(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0))
        angles = [math.radians(a) for a in (0.0, 30.0, 60.0, 90.0)]

        report = sweep_interference(
            [("arm", arm)], [("block", fixed)], axis, angles, joint_name="test",
        )
        assert not report.is_clear
        first = report.first_interference()
        assert first is not None
        assert first.angle_degrees > 0.0
        assert report.samples[0].has_interference is False
        assert report.samples[0].tightest_clearance == pytest.approx(0.5, abs=1e-9)

    def test_a_clear_sweep_reports_clear(self) -> None:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt

        block = BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, -5), 10.0, 10.0, 10.0).Shape()
        far = BRepPrimAPI_MakeBox(gp_Pnt(-1, 40.0, -1), 2.0, 5.0, 2.0).Shape()
        axis = JointAxis(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0))
        report = sweep_interference(
            [("arm", far)], [("block", block)], axis,
            [math.radians(a) for a in range(0, 100, 20)],
        )
        assert report.is_clear
        assert report.screened_out > 0  # the cheap test did its job

    def test_sweeping_a_deformable_body_is_refused(self) -> None:
        """A rigid rotation of a flexure is a pose the part never takes."""
        fixed, arm = self._boxes()
        axis = JointAxis(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="marked deformable"):
            sweep_interference(
                [("flexure", arm)], [("block", fixed)], axis, [0.0],
                deformable_labels=["flexure"],
            )

    def test_rotation_preserves_volume(self) -> None:
        """A sanity check on the transform: rotation is rigid."""
        from barnes_ui.core.cad.inspect import volume_properties

        _, arm = self._boxes()
        axis = JointAxis(origin=(1.0, 2.0, 3.0), direction=(0.3, 0.4, 0.5))
        before, _, _ = volume_properties(arm)
        after, _, _ = volume_properties(rotate_shape(arm, axis, 1.1))
        assert after == pytest.approx(before, rel=1e-12)
