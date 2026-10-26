"""Reduced-order curved-beam tests.

These are the Phase 2 acceptance criteria. Three kinds of check are made:

1. **Closed form.** A straight fixed-fixed member under pure imposed end rotation has a
   stiffness of 4EI/L by slope-deflection. That is an exact result and the solver must
   reproduce it.
2. **Scaling.** Stiffness must scale with the cube of section depth and linearly with
   modulus. A cubic dependence implemented as a square would still produce a smooth
   plausible curve, so it is checked explicitly.
3. **Independent method.** The curved case has no convenient closed form, so it is
   cross-checked against a direct-stiffness 2D frame assembly implemented here from
   scratch. Castigliano's unit-load method and direct stiffness are genuinely different
   routes to the same answer, so agreement is meaningful rather than circular.
"""

from __future__ import annotations

import numpy as np
import pytest

from barnes_ui.core.flexure.centerline import CenterlineStation, Member
from barnes_ui.core.flexure.section import CrossSection
from barnes_ui.core.material.models import HyperelasticModel, MaterialModelKind
from barnes_ui.core.mechanics.curved_beam import (
    CAVEAT_LINEAR_KINEMATICS,
    JointAxis,
    analyse_joint_flexure,
    suggest_joint_axis_from_collars,
)
from barnes_ui.core.provenance import CAVEAT_SMALL_STRAIN, Provenance

E_TEST = 100.0


def _material(youngs_modulus: float = E_TEST) -> HyperelasticModel:
    return HyperelasticModel(
        kind=MaterialModelKind.LINEAR_ELASTIC,
        parameters=(youngs_modulus, 0.3),
        name="test material",
        provenance=Provenance.ANALYTICAL_ESTIMATE,
        caveats=(),
    )


def _member_from_path(
    points: np.ndarray, width: float, depth: float, index: int = 0
) -> Member:
    """Build a Member directly from a polyline and a constant rectangular section.

    Bypasses the CAD kernel so these tests run anywhere. ``width`` is along X, the
    bending axis; ``depth`` is in the plane of curvature.
    """
    area = width * depth
    i_uu = width * depth**3 / 12.0
    i_vv = depth * width**3 / 12.0

    tangents = np.zeros_like(points)
    n = len(points)
    for i in range(n):
        if i == 0:
            delta = points[1] - points[0]
        elif i == n - 1:
            delta = points[-1] - points[-2]
        else:
            delta = points[i + 1] - points[i - 1]
        tangents[i] = delta / np.linalg.norm(delta)

    arc = np.concatenate(
        [[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    )

    stations = [
        CenterlineStation(
            s=float(arc[i]),
            position=tuple(float(v) for v in points[i]),
            tangent=tuple(float(v) for v in tangents[i]),
            section=CrossSection(
                area=area,
                centroid=tuple(float(v) for v in points[i]),
                width_u=width, width_v=depth,
                i_uu=i_uu, i_vv=i_vv,
                normal=tuple(float(v) for v in tangents[i]),
                u_axis=(1.0, 0.0, 0.0), v_axis=(0.0, 0.0, 1.0),
            ),
        )
        for i in range(n)
    ]
    return Member(index=index, stations=stations)


def _straight_member(length: float, width: float, depth: float, samples: int = 400) -> Member:
    y = np.linspace(0.0, length, samples)
    points = np.column_stack([np.zeros_like(y), y, np.zeros_like(y)])
    return _member_from_path(points, width, depth)


def _arch_member(span: float, rise: float, width: float, depth: float,
                 samples: int = 400) -> Member:
    """A circular-ish arch: parabolic rise over a span along Y, curving in Z."""
    y = np.linspace(0.0, span, samples)
    z = rise * (1.0 - ((2.0 * y / span) - 1.0) ** 2)
    points = np.column_stack([np.zeros_like(y), y, z])
    return _member_from_path(points, width, depth)


# ---------------------------------------------------------------------------
# Independent reference implementation
# ---------------------------------------------------------------------------

def _frame_fe_rotational_stiffness(
    points_2d: np.ndarray, area: float, inertia: float, youngs_modulus: float,
    joint_2d: np.ndarray,
) -> float:
    """Direct-stiffness 2D frame solution, as an independent cross-check.

    Euler-Bernoulli elements with axial and bending stiffness, no shear. Both ends are
    fully fixed; the distal end is given a unit rigid rotation about ``joint_2d``. The
    restoring moment about that point is returned.

    Deliberately written from first principles rather than reusing anything from the
    module under test, so that agreement between the two means something.
    """
    n = len(points_2d)
    ndof = 3 * n
    K = np.zeros((ndof, ndof))

    for e in range(n - 1):
        p0, p1 = points_2d[e], points_2d[e + 1]
        d = p1 - p0
        L = float(np.linalg.norm(d))
        c, s = d[0] / L, d[1] / L
        ea = youngs_modulus * area / L
        ei = youngs_modulus * inertia
        k_local = np.array([
            [ea, 0, 0, -ea, 0, 0],
            [0, 12 * ei / L**3, 6 * ei / L**2, 0, -12 * ei / L**3, 6 * ei / L**2],
            [0, 6 * ei / L**2, 4 * ei / L, 0, -6 * ei / L**2, 2 * ei / L],
            [-ea, 0, 0, ea, 0, 0],
            [0, -12 * ei / L**3, -6 * ei / L**2, 0, 12 * ei / L**3, -6 * ei / L**2],
            [0, 6 * ei / L**2, 2 * ei / L, 0, -6 * ei / L**2, 4 * ei / L],
        ])
        T = np.array([
            [c, s, 0, 0, 0, 0],
            [-s, c, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0],
            [0, 0, 0, c, s, 0],
            [0, 0, 0, -s, c, 0],
            [0, 0, 0, 0, 0, 1],
        ])
        idx = [3 * e, 3 * e + 1, 3 * e + 2, 3 * e + 3, 3 * e + 4, 3 * e + 5]
        K[np.ix_(idx, idx)] += T.T @ k_local @ T

    r = points_2d[-1] - joint_2d
    prescribed = {
        0: 0.0, 1: 0.0, 2: 0.0,
        ndof - 3: -r[1], ndof - 2: r[0], ndof - 1: 1.0,
    }
    free = [i for i in range(ndof) if i not in prescribed]

    u = np.zeros(ndof)
    for dof, value in prescribed.items():
        u[dof] = value

    rhs = -K[np.ix_(free, list(prescribed))] @ np.array(list(prescribed.values()))
    u[free] = np.linalg.solve(K[np.ix_(free, free)], rhs)

    reactions = K @ u
    rx, rz, rm = reactions[ndof - 3], reactions[ndof - 2], reactions[ndof - 1]
    return abs(rm + r[0] * rz - r[1] * rx)


# ---------------------------------------------------------------------------
# Closed-form benchmarks
# ---------------------------------------------------------------------------

class TestClosedForm:
    def test_straight_member_pure_rotation_matches_four_ei_over_l(self) -> None:
        """Phase 2 criterion: exact slope-deflection result 4EI/L.

        Placing the joint axis at the member's far end makes the imposed motion a pure
        relative rotation with no translation, which is the standard fixed-fixed case.
        """
        length, width, depth = 50.0, 2.0, 1.0
        inertia = width * depth**3 / 12.0
        member = _straight_member(length, width, depth)
        joint = JointAxis(origin=(0.0, length, 0.0), direction=(1.0, 0.0, 0.0))

        _, stiffness = analyse_joint_flexure(
            [member], _material(), joint, max_angle_rad=0.01, steps=3,
            include_shear=False, include_axial=True,
        )
        expected = 4.0 * E_TEST * inertia / length
        assert stiffness.rotational_stiffness == pytest.approx(expected, rel=1e-3)

    def test_straight_member_without_axial_reports_why_it_is_singular(self) -> None:
        """A straight member needs axial flexibility, and the error must say so.

        With no axial term the axial redundant generates no moment anywhere and has no
        stiffness either, so the flexibility matrix really is singular. Correct physics,
        and the message should explain it rather than blaming the joint axis.
        """
        member = _straight_member(50.0, 2.0, 1.0)
        joint = JointAxis(origin=(0.0, 50.0, 0.0), direction=(1.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="straight.*axial flexibility is disabled"):
            analyse_joint_flexure(
                [member], _material(), joint, 0.01, 3,
                include_shear=False, include_axial=False,
            )


class TestScaling:
    def test_stiffness_scales_with_the_cube_of_depth(self) -> None:
        """Doubling depth must multiply bending stiffness by 8.0.

        A cubic dependence implemented as a square would still plot smoothly, so this
        is checked directly rather than assumed from the formula being written down.
        """
        joint = JointAxis(origin=(0.0, 50.0, 0.0), direction=(1.0, 0.0, 0.0))
        results = []
        for depth in (1.0, 2.0):
            _, stiffness = analyse_joint_flexure(
                [_straight_member(50.0, 2.0, depth)], _material(), joint, 0.01, 3,
                include_shear=False, include_axial=True,
            )
            results.append(stiffness.rotational_stiffness)
        assert results[1] / results[0] == pytest.approx(8.0, abs=0.1)

    def test_stiffness_scales_linearly_with_modulus(self) -> None:
        joint = JointAxis(origin=(0.0, 50.0, 0.0), direction=(1.0, 0.0, 0.0))
        member = _straight_member(50.0, 2.0, 1.0)
        results = []
        for modulus in (100.0, 250.0):
            _, stiffness = analyse_joint_flexure(
                [member], _material(modulus), joint, 0.01, 3,
                include_shear=False, include_axial=True,
            )
            results.append(stiffness.rotational_stiffness)
        assert results[1] / results[0] == pytest.approx(2.5, rel=1e-6)

    def test_identical_parallel_members_add_exactly(self) -> None:
        """The twin-strap case: two identical straps give exactly twice the stiffness."""
        joint = JointAxis(origin=(0.0, 50.0, 0.0), direction=(1.0, 0.0, 0.0))
        one = _straight_member(50.0, 2.0, 1.0)
        two = [_straight_member(50.0, 2.0, 1.0), _straight_member(50.0, 2.0, 1.0)]

        _, single = analyse_joint_flexure(
            [one], _material(), joint, 0.01, 3, include_shear=False, include_axial=True
        )
        _, double = analyse_joint_flexure(
            two, _material(), joint, 0.01, 3, include_shear=False, include_axial=True
        )
        assert double.rotational_stiffness == pytest.approx(
            2.0 * single.rotational_stiffness, rel=1e-9
        )
        assert len(double.member_stiffness) == 2

    def test_longer_member_is_more_compliant(self) -> None:
        joint_short = JointAxis(origin=(0.0, 30.0, 0.0), direction=(1.0, 0.0, 0.0))
        joint_long = JointAxis(origin=(0.0, 60.0, 0.0), direction=(1.0, 0.0, 0.0))
        _, short = analyse_joint_flexure(
            [_straight_member(30.0, 2.0, 1.0)], _material(), joint_short, 0.01, 3,
            include_shear=False, include_axial=True,
        )
        _, long_ = analyse_joint_flexure(
            [_straight_member(60.0, 2.0, 1.0)], _material(), joint_long, 0.01, 3,
            include_shear=False, include_axial=True,
        )
        assert long_.rotational_stiffness < short.rotational_stiffness


class TestIndependentMethodAgreement:
    """Castigliano against direct stiffness, on geometry with no closed form."""

    def test_arch_agrees_with_frame_fe(self) -> None:
        span, rise, width, depth = 28.0, 4.0, 2.0, 1.0
        member = _arch_member(span, rise, width, depth, samples=200)
        joint_origin = np.array([0.0, span / 2.0, -5.0])
        joint = JointAxis(
            origin=tuple(float(v) for v in joint_origin), direction=(1.0, 0.0, 0.0)
        )

        _, stiffness = analyse_joint_flexure(
            [member], _material(), joint, 0.01, 3,
            include_shear=False, include_axial=True,
        )

        # Project into the same plane basis the module uses for an X joint axis:
        # e1 = +Z, e2 = -Y.
        relative = member.positions() - joint_origin
        points_2d = np.column_stack([relative[:, 2], -relative[:, 1]])
        reference = _frame_fe_rotational_stiffness(
            points_2d,
            area=width * depth,
            inertia=width * depth**3 / 12.0,
            youngs_modulus=E_TEST,
            joint_2d=np.array([0.0, 0.0]),
        )

        assert stiffness.rotational_stiffness == pytest.approx(reference, rel=0.01)

    def test_straight_member_agrees_with_frame_fe_offset_from_the_axis(self) -> None:
        """Offset from the axis means translation as well as rotation is imposed."""
        length, width, depth = 40.0, 2.0, 1.0
        member = _straight_member(length, width, depth, samples=200)
        joint_origin = np.array([0.0, length / 2.0, -6.0])
        joint = JointAxis(
            origin=tuple(float(v) for v in joint_origin), direction=(1.0, 0.0, 0.0)
        )

        _, stiffness = analyse_joint_flexure(
            [member], _material(), joint, 0.01, 3,
            include_shear=False, include_axial=True,
        )

        relative = member.positions() - joint_origin
        points_2d = np.column_stack([relative[:, 2], -relative[:, 1]])
        reference = _frame_fe_rotational_stiffness(
            points_2d, width * depth, width * depth**3 / 12.0, E_TEST,
            np.array([0.0, 0.0]),
        )
        assert stiffness.rotational_stiffness == pytest.approx(reference, rel=0.01)

    def test_shear_makes_the_member_more_compliant(self) -> None:
        """Including shear can only reduce stiffness; it never stiffens a structure."""
        member = _arch_member(28.0, 4.0, 2.0, 1.0, samples=200)
        joint = JointAxis(origin=(0.0, 14.0, -5.0), direction=(1.0, 0.0, 0.0))
        _, with_shear = analyse_joint_flexure(
            [member], _material(), joint, 0.01, 3, include_shear=True, include_axial=True
        )
        _, without_shear = analyse_joint_flexure(
            [member], _material(), joint, 0.01, 3, include_shear=False, include_axial=True
        )
        assert with_shear.rotational_stiffness < without_shear.rotational_stiffness


class TestCurveAndProvenance:
    def test_curve_passes_through_the_origin(self) -> None:
        member = _arch_member(28.0, 4.0, 2.0, 1.0, samples=100)
        joint = JointAxis(origin=(0.0, 14.0, -5.0), direction=(1.0, 0.0, 0.0))
        curve, _ = analyse_joint_flexure([member], _material(), joint, 1.0, 20)
        assert curve.torques[0] == pytest.approx(0.0)
        assert curve.peak_strains[0] == pytest.approx(0.0)

    def test_secant_equals_tangent_for_a_linear_model(self) -> None:
        """The linear model must be internally consistent, and visibly linear."""
        member = _arch_member(28.0, 4.0, 2.0, 1.0, samples=100)
        joint = JointAxis(origin=(0.0, 14.0, -5.0), direction=(1.0, 0.0, 0.0))
        curve, stiffness = analyse_joint_flexure([member], _material(), joint, 1.0, 20)
        assert curve.secant_stiffness(0.5) == pytest.approx(
            stiffness.rotational_stiffness, rel=1e-9
        )
        assert np.allclose(
            curve.tangent_stiffness(), stiffness.rotational_stiffness, rtol=1e-9
        )

    def test_results_are_tagged_reduced_order_at_best(self) -> None:
        """Even with a perfectly known material, a beam model is still a beam model."""
        member = _arch_member(28.0, 4.0, 2.0, 1.0, samples=100)
        joint = JointAxis(origin=(0.0, 14.0, -5.0), direction=(1.0, 0.0, 0.0))
        curve, _ = analyse_joint_flexure([member], _material(), joint, 1.0, 20)
        assert curve.provenance <= Provenance.REDUCED_ORDER_PREDICTION

    def test_assumed_material_drags_the_result_down_further(self) -> None:
        from barnes_ui.core.material.models import provisional_tpu

        member = _arch_member(28.0, 4.0, 2.0, 1.0, samples=100)
        joint = JointAxis(origin=(0.0, 14.0, -5.0), direction=(1.0, 0.0, 0.0))
        curve, _ = analyse_joint_flexure([member], provisional_tpu(), joint, 1.0, 20)
        assert curve.provenance is Provenance.UNVALIDATED_ASSUMPTION

    def test_limiting_caveats_are_always_attached(self) -> None:
        """The assumptions panel must never be empty for a reduced-order result."""
        member = _arch_member(28.0, 4.0, 2.0, 1.0, samples=100)
        joint = JointAxis(origin=(0.0, 14.0, -5.0), direction=(1.0, 0.0, 0.0))
        curve, _ = analyse_joint_flexure([member], _material(), joint, 1.0, 20)
        assert CAVEAT_SMALL_STRAIN in curve.caveats
        assert CAVEAT_LINEAR_KINEMATICS in curve.caveats

    def test_export_rows_carry_units_in_their_names(self) -> None:
        member = _arch_member(28.0, 4.0, 2.0, 1.0, samples=100)
        joint = JointAxis(origin=(0.0, 14.0, -5.0), direction=(1.0, 0.0, 0.0))
        curve, _ = analyse_joint_flexure([member], _material(), joint, 1.0, 5)
        row = curve.as_rows()[0]
        assert "restoring_torque_Nmm" in row
        assert "angle_deg" in row

    def test_rejects_an_empty_member_list(self) -> None:
        joint = JointAxis(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="At least one member"):
            analyse_joint_flexure([], _material(), joint, 1.0, 10)


class TestJointAxis:
    def test_zero_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="zero length"):
            JointAxis(origin=(0, 0, 0), direction=(0, 0, 0)).as_arrays()

    def test_direction_is_normalised(self) -> None:
        _, direction = JointAxis(origin=(0, 0, 0), direction=(3, 0, 0)).as_arrays()
        assert np.linalg.norm(direction) == pytest.approx(1.0)

    def test_suggestion_sits_midway_between_the_collars(self) -> None:
        axis = suggest_joint_axis_from_collars(
            [(6.09, 29.0, 5.44), (6.09, 60.86, 5.44)], (1.0, 0.0, 0.0)
        )
        assert axis.origin[1] == pytest.approx(44.93)
        assert axis.origin[2] == pytest.approx(5.44)

    def test_suggestion_requires_exactly_two_collars(self) -> None:
        with pytest.raises(ValueError, match="two collar centres"):
            suggest_joint_axis_from_collars([(0, 0, 0)], (1, 0, 0))
