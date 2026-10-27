"""Phase 5: kinematics, joint springs and the Mode 1 / Mode 2 separation.

Criterion 1 is tested structurally -- the Mode 1 result type has nowhere to put a
torque -- rather than by inspecting rendered text, because a label can be forgotten
and a missing field cannot.

Criterion 2 is tested against a torque-angle law whose exact form is known, so the
fit's residual can be compared with arithmetic instead of with recorded output.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from barnes_ui.core.assembly.joint import Joint
from barnes_ui.core.kinematics.chain import (
    ChainError,
    OutOfRangeError,
    SerialChain,
    rotation_placement,
)
from barnes_ui.core.kinematics.comparison import (
    ComparisonError,
    DesignComparison,
    DesignCurve,
)
from barnes_ui.core.kinematics.modes import (
    KinematicPose,
    ModeError,
    SimulationMode,
    require_mode,
)
from barnes_ui.core.kinematics.profiles import (
    ConstantAngle,
    LinearRamp,
    ProfileError,
    SinusoidalCycle,
    TrapezoidalProfile,
    sample_profiles,
)
from barnes_ui.core.kinematics.simulate import (
    SimulationError,
    preview_kinematics,
    simulate_reduced_order,
)
from barnes_ui.core.kinematics.spring import (
    ExtrapolationError,
    SpringFitError,
    SpringFitKind,
    fit_joint_spring,
)
from barnes_ui.core.mechanics.curved_beam import JointAxis
from barnes_ui.core.provenance import Provenance

from conftest import requires_kernel


def _confirmed_joint(name, proximal, distal, origin, direction=(1.0, 0.0, 0.0),
                     maximum=math.radians(100.0)) -> Joint:
    joint = Joint(
        name=name, proximal=tuple(proximal), distal=tuple(distal),
        minimum_angle=0.0, maximum_angle=maximum,
    )
    joint.set_axis(JointAxis(origin, direction), source="fixture")
    joint.confirm(by="test")
    return joint


def _finger() -> SerialChain:
    """Three links on a straight line along Y, two joints at Y = 20 and Y = 36."""
    mcp = _confirmed_joint("MCP", [0], [1, 2], (0.0, 20.0, 0.0))
    pip = _confirmed_joint("PIP", [1], [2], (0.0, 36.0, 0.0))
    return SerialChain(name="index", joints=[mcp, pip])


# ------------------------------------------------------------------- Mode 1


class TestModeSeparation:
    def test_a_kinematic_pose_cannot_be_relabelled(self) -> None:
        """Criterion 1, structurally: there is nowhere to put a torque."""
        with pytest.raises(ModeError, match="cannot be relabelled"):
            KinematicPose(angles={"PIP": 0.0}, mode=SimulationMode.REDUCED_ORDER)

    def test_kinematic_pose_has_no_force_field_at_all(self) -> None:
        pose = KinematicPose(angles={"PIP": 0.0})
        for forbidden in ("torque", "force", "stress", "energy", "moment"):
            assert not hasattr(pose, forbidden)

    def test_preview_mode_reports_no_force(self) -> None:
        assert SimulationMode.KINEMATIC_PREVIEW.reports_force is False
        assert SimulationMode.REDUCED_ORDER.reports_force is True

    def test_the_banner_says_what_the_mode_cannot_do(self) -> None:
        text = SimulationMode.KINEMATIC_PREVIEW.banner
        assert "not" in text.lower() and "force" in text.lower()

    def test_require_mode_refuses_the_wrong_mode(self) -> None:
        with pytest.raises(ModeError, match="no material in it"):
            require_mode(
                SimulationMode.KINEMATIC_PREVIEW, SimulationMode.REDUCED_ORDER
            )

    def test_preview_returns_poses_not_responses(self) -> None:
        chain = _finger()
        poses = preview_kinematics(chain, [(0.0, {"MCP": 0.0, "PIP": 0.0})])
        assert all(isinstance(p, KinematicPose) for p in poses)


# -------------------------------------------------------- Forward kinematics


class TestForwardKinematics:
    def test_rotation_happens_about_the_axis_not_the_origin(self) -> None:
        """The p - Rp term. Without it the finger orbits the world origin."""
        axis = JointAxis((0.0, 20.0, 0.0), (1.0, 0.0, 0.0))
        placement = rotation_placement(axis, math.radians(90.0))
        np.testing.assert_allclose(
            placement.apply_point((0.0, 20.0, 0.0)), (0.0, 20.0, 0.0), atol=1e-12
        )

    def test_a_point_on_the_axis_is_a_fixed_point(self) -> None:
        axis = JointAxis((1.0, 2.0, 3.0), (0.0, 0.0, 1.0))
        placement = rotation_placement(axis, 0.73)
        np.testing.assert_allclose(
            placement.apply_point((1.0, 2.0, 9.0)), (1.0, 2.0, 9.0), atol=1e-12
        )

    def test_distal_link_rotation_composes_down_the_chain(self) -> None:
        """Flexing both joints 90 degrees folds the finger back on itself.

        Link 2's tip starts at (0, 52, 0). The MCP at (0, 20, 0) rotating +90 about
        X sends it to (0, 20, 32). The PIP axis travels with link 1, arriving at
        (0, 20, 16); rotating +90 about it maps (0, 20, 32) to (0, 4, 16).
        """
        chain = _finger()
        placements = chain.placements(
            {"MCP": math.radians(90.0), "PIP": math.radians(90.0)}
        )
        tip = placements[2].apply_point((0.0, 52.0, 0.0))
        np.testing.assert_allclose(tip, (0.0, 4.0, 16.0), atol=1e-9)

    def test_rotating_only_the_distal_joint_leaves_the_middle_link_alone(self) -> None:
        chain = _finger()
        placements = chain.placements({"MCP": 0.0, "PIP": math.radians(45.0)})
        assert placements[1].is_identity
        assert not placements[2].is_identity

    def test_zero_angles_give_the_identity_everywhere(self) -> None:
        chain = _finger()
        for placement in chain.placements({"MCP": 0.0, "PIP": 0.0}).values():
            assert placement.is_identity

    def test_an_unconfirmed_axis_cannot_reach_an_animation(self) -> None:
        joint = Joint(name="PIP", proximal=(0,), distal=(1,))
        joint.set_axis(JointAxis((0, 0, 0), (1, 0, 0)), source="guess")
        with pytest.raises(ChainError, match="unconfirmed"):
            SerialChain(name="bad", joints=[joint])

    def test_a_non_serial_ordering_is_refused(self) -> None:
        """Listing the joints tip-first produces plausible motion of the wrong parts."""
        mcp = _confirmed_joint("MCP", [0], [1, 2], (0.0, 20.0, 0.0))
        pip = _confirmed_joint("PIP", [1], [2], (0.0, 36.0, 0.0))
        with pytest.raises(ChainError, match="not serial"):
            SerialChain(name="reversed", joints=[pip, mcp])

    def test_a_missing_angle_is_an_error_not_a_default(self) -> None:
        chain = _finger()
        with pytest.raises(ChainError, match="No angle given"):
            chain.placements({"MCP": 0.0})

    def test_an_angle_outside_the_range_is_refused(self) -> None:
        chain = _finger()
        with pytest.raises(OutOfRangeError, match="outside its stated range"):
            chain.placements({"MCP": math.radians(150.0), "PIP": 0.0})

    def test_sweeping_one_joint_covers_its_whole_range(self) -> None:
        chain = _finger()
        poses = chain.sweep_one_joint("PIP", steps=11)
        assert poses[0].angles["PIP"] == pytest.approx(0.0)
        assert poses[-1].angles["PIP"] == pytest.approx(math.radians(100.0))
        assert all(p.angles["MCP"] == 0.0 for p in poses)


# ------------------------------------------------------------------ Profiles


class TestProfiles:
    def test_linear_ramp_endpoints_and_midpoint(self) -> None:
        ramp = LinearRamp(start=0.0, end=1.0, duration=2.0)
        assert ramp.angle_at(0.0) == 0.0
        assert ramp.angle_at(1.0) == pytest.approx(0.5)
        assert ramp.angle_at(2.0) == pytest.approx(1.0)
        assert ramp.angle_at(99.0) == pytest.approx(1.0)  # held, not extrapolated

    def test_sinusoid_returns_to_its_start(self) -> None:
        cycle = SinusoidalCycle(start=0.1, end=0.9, duration=1.0)
        assert cycle.angle_at(0.0) == pytest.approx(0.1)
        assert cycle.angle_at(0.5) == pytest.approx(0.9)
        assert cycle.angle_at(1.0) == pytest.approx(0.1)

    def test_trapezoid_holds_in_the_middle(self) -> None:
        profile = TrapezoidalProfile(0.0, 1.0, duration=1.0, ramp_fraction=0.25)
        assert profile.angle_at(0.25) == pytest.approx(1.0)
        assert profile.angle_at(0.5) == pytest.approx(1.0)
        assert profile.angle_at(0.75) == pytest.approx(1.0)
        assert profile.angle_at(0.125) == pytest.approx(0.5)

    def test_an_over_long_ramp_is_refused(self) -> None:
        with pytest.raises(ProfileError, match="ramp_fraction"):
            TrapezoidalProfile(0.0, 1.0, ramp_fraction=0.75)

    def test_sampling_uses_the_longest_duration(self) -> None:
        schedule = sample_profiles(
            {
                "MCP": LinearRamp(0.0, 1.0, duration=2.0),
                "PIP": ConstantAngle(0.3, duration=0.5),
            },
            steps=5,
        )
        assert schedule[-1][0] == pytest.approx(2.0)
        assert schedule[-1][1]["MCP"] == pytest.approx(1.0)
        assert schedule[-1][1]["PIP"] == pytest.approx(0.3)


# ------------------------------------------------------------- Joint springs


def _reference_law(angle):
    """A plausible stiffening torque-angle law, exactly known.

    ``6.1 * x + 3.0 * x^3`` N.mm with x in radians: linear near neutral at roughly
    the A3 flexure's measured 6.1 N.mm/rad, stiffening as the angle grows.
    """
    return 6.1 * angle + 3.0 * angle ** 3


class TestJointSpringFit:
    def _samples(self, n=7, top=math.radians(90.0)):
        angles = np.linspace(0.0, top, n)
        return angles, _reference_law(angles)

    def test_interpolating_fit_reproduces_its_data_exactly(self) -> None:
        """Criterion 2's necessary condition, at the sample points."""
        angles, torques = self._samples()
        spring = fit_joint_spring(angles, torques, source="synthetic")
        assert spring.max_relative_residual < 1.0e-12

    def test_interpolating_fit_is_accurate_between_the_samples(self) -> None:
        """The condition that matters: the fit is evaluated between the FEA points.

        Checked against the exact law at angles that are not sample points.
        """
        angles, torques = self._samples(n=9)
        spring = fit_joint_spring(angles, torques, source="synthetic")
        probes = np.linspace(0.02, math.radians(89.0), 41)
        fitted = np.array([spring.torque(a).value for a in probes])
        exact = _reference_law(probes)
        worst = np.max(np.abs(fitted - exact)) / np.max(np.abs(torques))
        assert worst < 0.01, f"worst interpolation error {worst * 100:.3f} % of full scale"

    def test_odd_polynomial_recovers_the_exact_coefficients(self) -> None:
        """The reference law is odd with two terms, so a two-term odd fit is exact."""
        angles = np.linspace(-math.radians(90.0), math.radians(90.0), 11)
        spring = fit_joint_spring(
            angles, _reference_law(angles), source="synthetic",
            kind=SpringFitKind.ODD_POLYNOMIAL, polynomial_terms=2,
        )
        np.testing.assert_allclose(spring._coefficients, [6.1, 3.0], atol=1e-9)
        assert spring.max_relative_residual < 1.0e-12

    def test_a_fit_that_misses_its_own_data_is_refused(self) -> None:
        """A one-term odd fit cannot follow a cubic, and must not be used."""
        angles = np.linspace(0.0, math.radians(120.0), 9)
        with pytest.raises(SpringFitError, match="misses its own FEA data"):
            fit_joint_spring(
                angles, _reference_law(angles), source="synthetic",
                kind=SpringFitKind.ODD_POLYNOMIAL, polynomial_terms=1,
            )

    def test_fewer_than_three_points_is_refused(self) -> None:
        with pytest.raises(SpringFitError, match="at least three"):
            fit_joint_spring([0.0, 1.0], [0.0, 6.1], source="two points")

    def test_duplicate_angles_are_refused(self) -> None:
        with pytest.raises(SpringFitError, match="share an angle"):
            fit_joint_spring([0.0, 0.5, 0.5], [0.0, 3.0, 3.1], source="duplicated")

    def test_the_spring_is_never_stronger_than_a_reduced_order_prediction(self) -> None:
        angles, torques = self._samples()
        spring = fit_joint_spring(
            angles, torques, source="synthetic", provenance=Provenance.FEA_RESULT
        )
        assert spring.provenance is Provenance.REDUCED_ORDER_PREDICTION

    def test_every_value_carries_the_reduced_order_caveats(self) -> None:
        """Criterion 5."""
        angles, torques = self._samples()
        spring = fit_joint_spring(angles, torques, source="synthetic")
        keys = {c.key for c in spring.torque(0.5).caveats}
        assert {"no_contact_state_change", "quasi_static", "rigid_links",
                "no_viscoelasticity", "fitted_joint_spring"} <= keys


class TestExtrapolation:
    def _spring(self):
        angles = np.linspace(0.0, math.radians(60.0), 7)
        return fit_joint_spring(angles, _reference_law(angles), source="synthetic")

    def test_outside_the_fitted_range_it_refuses(self) -> None:
        """Criterion 2's second half."""
        spring = self._spring()
        with pytest.raises(ExtrapolationError, match="fitted over"):
            spring.torque(math.radians(90.0))

    def test_opting_in_attaches_a_caveat_to_the_value(self) -> None:
        spring = self._spring()
        value = spring.torque(math.radians(90.0), allow_extrapolation=True)
        assert any(c.key == "extrapolated_spring" for c in value.caveats)

    def test_stiffness_and_energy_also_refuse(self) -> None:
        spring = self._spring()
        with pytest.raises(ExtrapolationError):
            spring.tangent_stiffness(math.radians(90.0))
        with pytest.raises(ExtrapolationError):
            spring.strain_energy(math.radians(90.0))

    def test_tangent_stiffness_is_accurate_inside_and_weaker_at_the_endpoint(
        self
    ) -> None:
        """A shape-preserving interpolant is exact at its nodes and only
        approximately differentiable at the ends.

        PCHIP estimates the endpoint slope from a one-sided three-point formula, so
        on this 7-point grid the stiffness at the neutral angle comes out about 3 per
        cent low against the exact 6.1 N.mm/rad, while an interior point is an order
        of magnitude better. Worth knowing before quoting a neutral-position
        stiffness off a fitted spring: sample the FEA on both sides of neutral, or
        read the stiffness from the FEA run itself.
        """
        spring = self._spring()
        at_neutral = spring.tangent_stiffness(0.0).value
        assert at_neutral == pytest.approx(6.1, rel=0.05)

        angle = math.radians(30.0)
        exact_interior = 6.1 + 9.0 * angle ** 2
        interior = spring.tangent_stiffness(angle).value
        assert interior == pytest.approx(exact_interior, rel=0.01)
        assert abs(interior - exact_interior) / exact_interior <             abs(at_neutral - 6.1) / 6.1

    def test_energy_matches_the_closed_form(self) -> None:
        spring = self._spring()
        angle = math.radians(45.0)
        exact = 6.1 * angle ** 2 / 2.0 + 3.0 * angle ** 4 / 4.0
        assert spring.strain_energy(angle).value == pytest.approx(exact, rel=1e-3)


# ---------------------------------------------------------------- Mode 2 run


class TestReducedOrderSimulation:
    def _springs(self, top=math.radians(100.0)):
        angles = np.linspace(0.0, top, 9)
        return {
            name: fit_joint_spring(
                angles, _reference_law(angles), source="synthetic", name=name
            )
            for name in ("MCP", "PIP")
        }

    def test_a_missing_spring_is_an_error_not_a_skipped_joint(self) -> None:
        chain = _finger()
        springs = self._springs()
        del springs["PIP"]
        with pytest.raises(SimulationError, match="partial torque total"):
            simulate_reduced_order(chain, springs, [(0.0, {"MCP": 0.0, "PIP": 0.0})])

    def test_torque_follows_the_prescribed_angles(self) -> None:
        chain = _finger()
        schedule = sample_profiles(
            {
                "MCP": LinearRamp(0.0, math.radians(60.0)),
                "PIP": LinearRamp(0.0, math.radians(90.0)),
            },
            steps=21,
        )
        result = simulate_reduced_order(chain, self._springs(), schedule)
        torques = result.torques("PIP")
        assert torques[0] == pytest.approx(0.0, abs=1e-9)
        assert np.all(np.diff(torques) > 0.0)  # monotonically stiffening
        assert result.peak_torque("PIP").value == pytest.approx(
            _reference_law(math.radians(90.0)), rel=1e-3
        )

    def test_a_trajectory_beyond_the_fitted_range_is_refused(self) -> None:
        chain = _finger()
        springs = self._springs(top=math.radians(40.0))
        schedule = sample_profiles(
            {"MCP": ConstantAngle(0.0), "PIP": LinearRamp(0.0, math.radians(90.0))},
            steps=11,
        )
        with pytest.raises(ExtrapolationError, match="full range of motion"):
            simulate_reduced_order(chain, springs, schedule)

    def test_opting_in_records_where_it_extrapolated(self) -> None:
        chain = _finger()
        springs = self._springs(top=math.radians(40.0))
        schedule = sample_profiles(
            {"MCP": ConstantAngle(0.0), "PIP": LinearRamp(0.0, math.radians(90.0))},
            steps=11,
        )
        result = simulate_reduced_order(
            chain, springs, schedule, allow_extrapolation=True
        )
        assert result.extrapolated_at
        assert "beyond the fitted range" in " ".join(result.notes)

    def test_an_out_and_back_profile_does_no_net_work(self) -> None:
        """True of this model, and false of a real TPU part. The test documents
        which of those the application is reporting."""
        chain = _finger()
        schedule = sample_profiles(
            {
                "MCP": ConstantAngle(0.0),
                "PIP": SinusoidalCycle(0.0, math.radians(90.0)),
            },
            steps=201,
        )
        result = simulate_reduced_order(chain, self._springs(), schedule)
        assert result.work_done("PIP").value == pytest.approx(0.0, abs=1e-6)

    def test_the_result_carries_caveats_and_a_banner(self) -> None:
        chain = _finger()
        result = simulate_reduced_order(
            chain, self._springs(), [(0.0, {"MCP": 0.0, "PIP": 0.1})]
        )
        assert result.caveats()
        assert "REDUCED-ORDER" in result.banner
        assert "caveat:" in result.summary()

    def test_rows_export_carries_the_provenance_label(self) -> None:
        chain = _finger()
        result = simulate_reduced_order(
            chain, self._springs(), [(0.0, {"MCP": 0.0, "PIP": 0.1})]
        )
        rows = result.as_rows()
        assert rows and rows[0]["provenance"] == "Reduced-order"


# -------------------------------------------------------- Design comparison


class TestDesignComparison:
    def _curve(self, name, scale, provenance=Provenance.REDUCED_ORDER_PREDICTION):
        angles = np.linspace(0.0, math.radians(90.0), 21)
        return DesignCurve(
            name=name, angles=angles, torques=scale * _reference_law(angles),
            provenance=provenance, source=f"{name} run",
        )

    def test_legend_text_carries_the_provenance(self) -> None:
        """Criterion 4: the tag is in the legend, not in a tooltip."""
        comparison = DesignComparison()
        comparison.add(self._curve("A8-4turn", 1.0))
        comparison.add(self._curve("A8-6turn", 0.6))
        assert comparison.legend_entries() == [
            "A8-4turn [Reduced-order]", "A8-6turn [Reduced-order]"
        ]

    def test_ranking_orders_softest_first(self) -> None:
        comparison = DesignComparison()
        comparison.add(self._curve("stiff", 1.0))
        comparison.add(self._curve("soft", 0.4))
        ranked = comparison.rank_at(math.radians(45.0))
        assert [name for name, _ in ranked] == ["soft", "stiff"]

    def test_ranking_across_methods_is_refused(self) -> None:
        comparison = DesignComparison()
        comparison.add(self._curve("rom", 1.0, Provenance.REDUCED_ORDER_PREDICTION))
        comparison.add(self._curve("fea", 0.8, Provenance.FEA_RESULT))
        with pytest.raises(ComparisonError, match="different methods"):
            comparison.rank_at(math.radians(45.0))

    def test_the_cross_method_ratio_is_available_and_weakly_tagged(self) -> None:
        """Phase 3 criterion 7 is exactly this quantity, so it must be computable."""
        comparison = DesignComparison()
        comparison.add(self._curve("fea", 1.0, Provenance.FEA_RESULT))
        comparison.add(self._curve("rom", 1.238, Provenance.REDUCED_ORDER_PREDICTION))
        ratio = comparison.stiffness_ratio("fea", "rom", math.radians(45.0))
        assert ratio.value == pytest.approx(1.238, rel=1e-9)
        assert ratio.provenance is Provenance.REDUCED_ORDER_PREDICTION

    def test_non_overlapping_curves_cannot_be_compared(self) -> None:
        comparison = DesignComparison()
        comparison.add(
            DesignCurve("a", np.linspace(0.0, 0.5, 5), np.linspace(0.0, 3.0, 5),
                        Provenance.FEA_RESULT)
        )
        comparison.add(
            DesignCurve("b", np.linspace(1.0, 1.5, 5), np.linspace(6.0, 9.0, 5),
                        Provenance.FEA_RESULT)
        )
        with pytest.raises(ComparisonError, match="do not overlap"):
            comparison.overlap

    def test_duplicate_names_are_refused(self) -> None:
        comparison = DesignComparison()
        comparison.add(self._curve("a", 1.0))
        with pytest.raises(ComparisonError, match="Duplicate"):
            comparison.add(self._curve("a", 2.0))


# ------------------------------------------------------- Trajectory clashes


@requires_kernel
class TestTrajectoryInterference:
    """Phase 5 criterion 3, on a chain whose collision angle is arithmetic."""

    def _shapes(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt

        # Link 0 is a fixed block. Link 1 is an arm reaching along +Y from the joint,
        # which swings down into the block as the joint flexes.
        block = BRepPrimAPI_MakeBox(gp_Pnt(-5.0, -10.0, -12.0), 10.0, 10.0, 12.0).Shape()
        arm = BRepPrimAPI_MakeBox(gp_Pnt(-2.0, 1.0, -1.0), 4.0, 14.0, 2.0).Shape()
        return {0: block, 1: arm}

    def _chain(self) -> SerialChain:
        joint = _confirmed_joint(
            "PIP", [0], [1], (0.0, 0.0, 0.0), maximum=math.radians(170.0)
        )
        return SerialChain(name="swing", joints=[joint])

    def test_a_clear_part_of_the_range_is_reported_clear(self) -> None:
        from barnes_ui.core.kinematics.collision import check_trajectory

        chain = self._chain()
        poses = [
            chain.pose({"PIP": math.radians(a)}, time=a / 100.0)
            for a in (0, 10, 20, 30)
        ]
        report = check_trajectory(poses, self._shapes())
        assert report.is_clear
        assert report.tightest_clearance == pytest.approx(1.0, abs=1e-6)

    def test_the_colliding_part_of_the_range_is_located(self) -> None:
        from barnes_ui.core.kinematics.collision import check_trajectory

        chain = self._chain()
        poses = [
            chain.pose({"PIP": math.radians(a)}, time=float(a))
            for a in range(0, 171, 15)
        ]
        report = check_trajectory(poses, self._shapes())
        assert not report.is_clear
        first = report.first_clash()
        assert first is not None
        # The arm points along +Y and the block occupies -Z and -Y; the arm cannot
        # reach it before it has swung well past the quarter turn.
        assert 60.0 <= first.time <= 180.0
        assert "overlap" in first.describe()

    def test_a_deformable_component_is_skipped_and_said_to_be_skipped(self) -> None:
        from barnes_ui.core.kinematics.collision import check_trajectory

        chain = self._chain()
        poses = [chain.pose({"PIP": math.radians(170.0)}, time=1.0)]
        report = check_trajectory(poses, self._shapes(), deformable=[1])
        assert report.is_clear
        assert report.skipped_components == (1,)
        assert "NOT CHECKED" in report.summary()

    def test_an_ignored_pair_is_not_checked(self) -> None:
        from barnes_ui.core.kinematics.collision import check_trajectory

        chain = self._chain()
        poses = [chain.pose({"PIP": math.radians(170.0)}, time=1.0)]
        report = check_trajectory(poses, self._shapes(), ignore_pairs=[(0, 1)])
        assert report.is_clear
        assert report.pairs_per_pose == 0
