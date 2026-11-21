"""The two-point selection protocol.

No Qt and no VTK here: the controller is deliberately free of both, so the whole of
its behaviour is checked without a display. What these tests are for is the set of
transitions that the original implementation -- a list and two lines inside
``MainWindow`` -- got wrong or did not have at all:

* a point from a session that has been replaced must not be appended to the next one;
* a click that hits nothing must not become a coordinate;
* two coincident points must not define an axis;
* replacing the model must discard points picked on the old one;
* an unconfirmed axis must not be readable as an axis.

The viewport tests in ``test_gui_picking.py`` cover the other half, which is that the
mouse actually reaches this object.
"""

from __future__ import annotations

import math

import pytest

from barnes_ui.gui.viewer.selection import (
    PickOutcome,
    PointSelectionController,
    SelectionPurpose,
    SelectionState,
    TwoPointSelection,
)

A = (0.0, 0.0, 0.0)
B = (3.0, 4.0, 0.0)          # 5 mm from A, by 3-4-5
C = (10.0, 0.0, 0.0)


@pytest.fixture
def controller() -> PointSelectionController:
    return PointSelectionController()


class TestActivation:
    def test_a_fresh_controller_is_idle_and_not_picking(self, controller) -> None:
        assert controller.state is SelectionState.IDLE
        assert not controller.is_picking
        assert controller.purpose is None
        assert controller.result is None

    def test_a_point_offered_while_idle_is_ignored(self, controller) -> None:
        assert controller.add_point(A) is PickOutcome.IGNORED
        assert controller.points == ()

    def test_begin_arms_picking_and_returns_a_token(self, controller) -> None:
        token = controller.begin(SelectionPurpose.MEASUREMENT)
        assert controller.state is SelectionState.AWAITING_FIRST
        assert controller.is_picking
        assert token == controller.generation

    def test_each_begin_issues_a_new_token(self, controller) -> None:
        first = controller.begin(SelectionPurpose.MEASUREMENT)
        second = controller.begin(SelectionPurpose.MEASUREMENT)
        assert second != first

    def test_the_instruction_changes_with_the_state(self, controller) -> None:
        idle = controller.message
        controller.begin(SelectionPurpose.MEASUREMENT)
        armed = controller.message
        controller.add_point(A)
        awaiting_second = controller.message
        controller.add_point(B)
        preview = controller.message
        assert len({idle, armed, awaiting_second, preview}) == 4
        assert "first point" in armed
        assert "second point" in awaiting_second.lower()


class TestCapture:
    def test_the_first_point_is_captured_exactly(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        assert controller.add_point(A) is PickOutcome.FIRST_CAPTURED
        assert controller.state is SelectionState.AWAITING_SECOND
        assert controller.points == (A,)
        assert controller.result is None, "one point is not a result"

    def test_the_second_point_completes_a_preview(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        assert controller.add_point(B) is PickOutcome.SECOND_CAPTURED
        assert controller.state is SelectionState.PREVIEW
        assert controller.points == (A, B)

    def test_coordinates_are_not_altered(self, controller) -> None:
        """No rounding, no conversion. The picker's coordinates are the model's."""
        awkward = (-12.345678901, 0.000123456, 1e4)
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(awkward)
        controller.add_point(C)
        result = controller.result
        assert result is not None
        assert result.first == pytest.approx(awkward, rel=0, abs=0)

    def test_the_distance_is_euclidean(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.add_point(B)
        assert controller.result.distance == pytest.approx(5.0)

    def test_the_delta_is_signed_and_ordered(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(C)
        controller.add_point(A)
        assert controller.result.delta == pytest.approx((-10.0, 0.0, 0.0))

    def test_a_third_point_is_ignored_until_cleared(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.add_point(B)
        assert controller.add_point(C) is PickOutcome.IGNORED
        assert controller.points == (A, B)


class TestInvalidHits:
    @pytest.mark.parametrize(
        "bad",
        [
            (float("nan"), 0.0, 0.0),
            (0.0, float("inf"), 0.0),
            (1.0, 2.0),
            (1.0, 2.0, 3.0, 4.0),
            ("a", "b", "c"),
            None,
        ],
    )
    def test_an_unusable_pick_is_refused_without_changing_the_state(
        self, controller, bad
    ) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        assert controller.add_point(bad) is PickOutcome.REJECTED_INVALID
        assert controller.state is SelectionState.AWAITING_SECOND
        assert controller.points == (A,), "the good point must survive the bad one"

    def test_a_missed_click_leaves_the_selection_untouched(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.register_miss()
        assert controller.state is SelectionState.AWAITING_SECOND
        assert controller.points == (A,)
        assert "missed" in controller.message

    def test_a_missed_click_is_reported_rather_than_swallowed(self, controller) -> None:
        """A click that produces nothing visible is how the original bug looked."""
        controller.begin(SelectionPurpose.MEASUREMENT)
        before = controller.message
        controller.register_miss()
        assert controller.message != before

    def test_a_miss_while_idle_does_nothing(self, controller) -> None:
        assert controller.register_miss() is PickOutcome.IGNORED
        assert controller.state is SelectionState.IDLE


class TestCoincidentPoints:
    def test_an_axis_refuses_a_point_within_its_tolerance(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        nearly = (0.01, 0.0, 0.0)   # well inside the 0.5 mm default
        assert controller.add_point(nearly) is PickOutcome.REJECTED_COINCIDENT
        assert controller.state is SelectionState.AWAITING_SECOND
        assert controller.points == (A,)
        assert controller.result is None

    def test_the_rejection_says_what_the_threshold_was(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point((0.01, 0.0, 0.0))
        assert "0.5" in controller.message

    def test_an_axis_accepts_a_point_beyond_its_tolerance(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        assert controller.add_point((0.6, 0.0, 0.0)) is PickOutcome.SECOND_CAPTURED

    def test_a_measurement_accepts_a_small_but_real_separation(
        self, controller
    ) -> None:
        """0.01 mm apart is a legitimate distance and a hopeless axis baseline."""
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        assert controller.add_point((0.01, 0.0, 0.0)) is PickOutcome.SECOND_CAPTURED
        assert controller.result.distance == pytest.approx(0.01)

    def test_a_measurement_still_refuses_the_identical_point(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        assert controller.add_point(A) is PickOutcome.REJECTED_COINCIDENT

    def test_an_explicit_tolerance_overrides_the_default(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS, coincidence_tolerance=5.0)
        controller.add_point(A)
        assert controller.add_point(B) is PickOutcome.REJECTED_COINCIDENT  # 5 mm
        assert controller.add_point(C) is PickOutcome.SECOND_CAPTURED      # 10 mm


class TestAxisDerivation:
    def test_the_direction_is_a_unit_vector_from_first_to_second(
        self, controller
    ) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point(B)
        ux, uy, uz = controller.result.direction
        assert (ux, uy, uz) == pytest.approx((0.6, 0.8, 0.0))
        assert math.sqrt(ux * ux + uy * uy + uz * uz) == pytest.approx(1.0)

    def test_reversing_the_picks_reverses_the_direction(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(B)
        controller.add_point(A)
        assert controller.result.direction == pytest.approx((-0.6, -0.8, 0.0))

    def test_the_origin_is_the_midpoint(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point(B)
        assert controller.result.origin == pytest.approx((1.5, 2.0, 0.0))

    def test_a_degenerate_pair_cannot_yield_a_direction(self) -> None:
        """Belt and braces: the controller refuses such a pair, so this is a bug
        guard rather than a user-facing path, and it must shout instead of
        returning a zero vector for an analysis to use as an axis."""
        degenerate = TwoPointSelection(
            purpose=SelectionPurpose.JOINT_AXIS, first=A, second=A
        )
        with pytest.raises(ValueError, match="coincident"):
            _ = degenerate.direction


class TestConfirmation:
    def test_a_measurement_is_readable_before_confirmation(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.add_point(B)
        assert controller.result is not None
        assert controller.result.distance == pytest.approx(5.0)

    def test_an_axis_is_not_available_before_confirmation(self, controller) -> None:
        """The whole reason the two purposes are separated.

        A previewed axis is visible and unusable. Nothing downstream can read it
        until a person has agreed to it.
        """
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point(B)
        assert controller.state is SelectionState.PREVIEW
        assert controller.confirmed_axis is None

    def test_confirming_an_axis_makes_it_available(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point(B)
        confirmed = controller.confirm()
        assert controller.state is SelectionState.COMPLETED
        assert controller.confirmed_axis is confirmed
        assert confirmed.direction == pytest.approx((0.6, 0.8, 0.0))

    def test_a_confirmed_measurement_is_not_an_axis(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.add_point(B)
        controller.confirm()
        assert controller.confirmed_axis is None

    def test_confirming_nothing_raises(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        with pytest.raises(ValueError, match="nothing to confirm"):
            controller.confirm()

    def test_confirming_twice_raises(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point(B)
        controller.confirm()
        with pytest.raises(ValueError):
            controller.confirm()


class TestClearCancelAndRepeat:
    def test_clear_drops_the_points_and_stays_armed(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.add_point(B)
        controller.clear()
        assert controller.state is SelectionState.AWAITING_FIRST
        assert controller.points == ()
        assert controller.result is None
        assert controller.is_picking

    def test_picking_can_be_repeated_after_clearing(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        for _ in range(3):
            controller.add_point(A)
            controller.add_point(C)
            assert controller.result.distance == pytest.approx(10.0)
            controller.clear()
        assert controller.state is SelectionState.AWAITING_FIRST

    def test_cancel_disarms_and_forgets(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.cancel()
        assert controller.state is SelectionState.CANCELLED
        assert not controller.is_picking
        assert controller.points == ()

    def test_a_point_after_cancelling_is_ignored(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.cancel()
        assert controller.add_point(A) is PickOutcome.IGNORED

    def test_picking_can_restart_after_cancelling(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.cancel()
        controller.begin(SelectionPurpose.MEASUREMENT)
        assert controller.add_point(A) is PickOutcome.FIRST_CAPTURED

    def test_clear_before_any_begin_is_harmless(self, controller) -> None:
        controller.clear()
        assert controller.state is SelectionState.IDLE

    def test_a_completed_selection_can_be_followed_by_another(self, controller) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point(B)
        controller.confirm()
        controller.begin(SelectionPurpose.MEASUREMENT)
        assert controller.confirmed_axis is None, "the new session starts empty"
        assert controller.add_point(A) is PickOutcome.FIRST_CAPTURED


class TestStaleCallbacks:
    def test_a_point_with_a_previous_token_is_dropped(self, controller) -> None:
        """A VTK observer from a torn-down session is not a user action."""
        stale = controller.begin(SelectionPurpose.MEASUREMENT)
        controller.begin(SelectionPurpose.MEASUREMENT)
        assert controller.add_point(A, token=stale) is PickOutcome.IGNORED
        assert controller.points == ()

    def test_the_current_token_is_accepted(self, controller) -> None:
        token = controller.begin(SelectionPurpose.MEASUREMENT)
        assert controller.add_point(A, token=token) is PickOutcome.FIRST_CAPTURED

    def test_a_stale_point_cannot_complete_a_pair(self, controller) -> None:
        stale = controller.begin(SelectionPurpose.MEASUREMENT)
        token = controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A, token=token)
        assert controller.add_point(B, token=stale) is PickOutcome.IGNORED
        assert controller.result is None


class TestInvalidation:
    def test_replacing_the_model_discards_the_selection(self, controller) -> None:
        """The original defect, stated as a test.

        A point picked on one solid paired with a point picked on the next one and
        produced a distance between two different parts.
        """
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        assert controller.invalidate("a different model was imported") is True
        assert controller.state is SelectionState.IDLE
        assert controller.points == ()
        assert controller.add_point(B) is PickOutcome.IGNORED

    def test_invalidation_says_why(self, controller) -> None:
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.invalidate("the geometry was regenerated from parameters")
        assert "regenerated from parameters" in controller.message

    def test_invalidating_nothing_reports_that_nothing_was_lost(
        self, controller
    ) -> None:
        assert controller.invalidate("no reason at all") is False

    def test_a_confirmed_axis_does_not_survive_a_regeneration(
        self, controller
    ) -> None:
        controller.begin(SelectionPurpose.JOINT_AXIS)
        controller.add_point(A)
        controller.add_point(B)
        controller.confirm()
        assert controller.confirmed_axis is not None
        controller.invalidate("the geometry was regenerated from parameters")
        assert controller.confirmed_axis is None


class TestUnits:
    def test_the_unit_is_carried_into_the_result(self, controller) -> None:
        controller.set_unit("in")
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.add_point(B)
        assert controller.result.unit == "in"

    def test_changing_the_unit_does_not_rescale_coordinates(self, controller) -> None:
        """Reinterpreting a unit changes what the numbers mean, not the numbers.

        This mirrors the Geometry panel, where the combo reinterprets the file's
        stored coordinates rather than converting them -- see its ``_build_unit_box``
        for why those two are deliberately not separated.
        """
        controller.begin(SelectionPurpose.MEASUREMENT)
        controller.add_point(A)
        controller.add_point(B)
        before = controller.result.distance
        controller.set_unit("in")
        assert controller.result.distance == pytest.approx(before)
        assert controller.result.unit == "in"


class TestPurposeMetadata:
    def test_only_an_axis_requires_confirmation(self) -> None:
        assert SelectionPurpose.JOINT_AXIS.requires_confirmation
        assert not SelectionPurpose.MEASUREMENT.requires_confirmation

    def test_an_axis_tolerance_is_far_coarser_than_a_measurement_one(self) -> None:
        assert (
            SelectionPurpose.JOINT_AXIS.default_coincidence_tolerance
            > 1000.0 * SelectionPurpose.MEASUREMENT.default_coincidence_tolerance
        )

    def test_every_purpose_has_a_label(self) -> None:
        for purpose in SelectionPurpose:
            assert purpose.label
