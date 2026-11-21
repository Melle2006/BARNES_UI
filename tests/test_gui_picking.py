"""Viewport picking, against a real VTK render window.

These tests exist because mocked callbacks proved nothing about the original defect.
The protocol was fine in isolation; what was broken was the binding between the mouse
and the protocol -- PyVista binds point picking to the **right** button and the ``P``
key unless ``left_clicking=True`` is passed, and the panel told the user to click.
A test that called the callback directly passed throughout.

So the assertions here reach into PyVista's picking component to check which observer
is installed. That is private API and deliberately so: the public surface does not
report what the mouse is bound to, and that binding is precisely the thing that was
wrong. If a PyVista upgrade renames it, this test failing is the correct outcome --
it is the only automated check that the left button picks.

The render window is real. On a machine with no usable OpenGL the whole module skips
rather than reporting a pass it did not earn.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QApplication  # noqa: E402

from barnes_ui.gui.viewer.selection import (  # noqa: E402
    SelectionPurpose,
    SelectionState,
)

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewport(qt_app):
    """A live Viewport, torn down the way the application tears one down."""
    from barnes_ui.gui.viewer.viewport import Viewport

    try:
        view = Viewport()
    except Exception as exc:  # pragma: no cover - no usable OpenGL on this machine
        pytest.skip(f"Could not create a VTK render window: {exc}")
    yield view
    view.close_viewport()


class _FakePicker:
    """Stands in for the VTK picker, which only ``GetActor`` is consulted on."""

    def __init__(self, actor) -> None:
        self._actor = actor

    def GetActor(self):  # noqa: N802 - VTK naming
        return self._actor


def _picking_component(viewport):
    return viewport.plotter.picking


def _left_observer(viewport):
    return _picking_component(viewport)._picking_left_clicking_observer


def _right_observer(viewport):
    return _picking_component(viewport)._picking_right_clicking_observer


def _actor_names(viewport) -> set[str]:
    return set(viewport.plotter.renderer.actors)


class TestArming:
    def test_arming_binds_the_left_mouse_button(self, viewport) -> None:
        """The root cause, as a regression test.

        Before the fix the left button was never bound, so clicking the model did
        nothing and the on-screen hint that would have said "right-click or press P"
        was suppressed.
        """
        viewport.start_point_picking(lambda _point: None)
        assert _left_observer(viewport) is not None
        assert _right_observer(viewport) is None

    def test_arming_marks_the_picker_in_use(self, viewport) -> None:
        viewport.start_point_picking(lambda _point: None)
        assert _picking_component(viewport)._picker_in_use
        assert viewport.is_picking

    def test_arming_returns_a_new_session_token_each_time(self, viewport) -> None:
        first = viewport.start_point_picking(lambda _point: None)
        second = viewport.start_point_picking(lambda _point: None)
        assert second != first
        assert viewport.pick_session == second

    def test_arming_twice_does_not_raise(self, viewport) -> None:
        """PyVista raises on re-arming a live picker; the viewport disarms first.

        Reachable from the panel: the toggle and a model replacement can both call
        in, and a ``PyVistaPickingError`` out of a Qt slot is an error dialog over
        the model.
        """
        viewport.start_point_picking(lambda _point: None)
        viewport.start_point_picking(lambda _point: None)  # must not raise
        assert viewport.is_picking

    def test_disarming_removes_the_observer(self, viewport) -> None:
        viewport.start_point_picking(lambda _point: None)
        viewport.stop_point_picking()
        assert _left_observer(viewport) is None
        assert not _picking_component(viewport)._picker_in_use
        assert not viewport.is_picking

    def test_disarming_twice_is_harmless(self, viewport) -> None:
        viewport.start_point_picking(lambda _point: None)
        viewport.stop_point_picking()
        viewport.stop_point_picking()
        assert not viewport.is_picking

    def test_the_instruction_is_drawn_in_the_viewport(self, viewport) -> None:
        viewport.start_point_picking(
            lambda _point: None, instruction="Click the first point."
        )
        assert viewport._INSTRUCTION_NAME in _actor_names(viewport)

    def test_disarming_removes_the_instruction(self, viewport) -> None:
        viewport.start_point_picking(lambda _point: None, instruction="Click.")
        viewport.stop_point_picking()
        assert viewport._INSTRUCTION_NAME not in _actor_names(viewport)


class TestHitsAndMisses:
    def test_a_hit_reaches_the_callback_with_its_coordinates(self, viewport) -> None:
        seen: list[tuple[float, float, float]] = []
        viewport.start_point_picking(seen.append)
        viewport._on_point_picked((1.5, -2.0, 3.25), _FakePicker(object()))
        assert seen == [(1.5, -2.0, 3.25)]

    def test_a_click_that_hits_nothing_is_a_miss_not_a_coordinate(
        self, viewport
    ) -> None:
        """A background click must never become a measured point.

        VTK still returns a position for it -- a point on the focal plane -- which
        looks exactly like an ordinary pick on the part.
        """
        seen: list[tuple[float, float, float]] = []
        misses: list[int] = []
        viewport.start_point_picking(seen.append, on_miss=lambda: misses.append(1))
        viewport._on_point_picked((0.0, 0.0, 0.0), _FakePicker(None))
        assert seen == []
        assert misses == [1]

    def test_a_pick_after_disarming_is_dropped(self, viewport) -> None:
        """No stale callbacks: a disarmed viewport forwards nothing."""
        seen: list[tuple[float, float, float]] = []
        viewport.start_point_picking(seen.append)
        viewport.stop_point_picking()
        viewport._on_point_picked((1.0, 1.0, 1.0), _FakePicker(object()))
        assert seen == []

    def test_a_pick_with_too_few_coordinates_is_dropped(self, viewport) -> None:
        seen: list[tuple[float, float, float]] = []
        viewport.start_point_picking(seen.append)
        viewport._on_point_picked((1.0, 2.0), _FakePicker(object()))
        assert seen == []


class TestSelectionGraphics:
    def test_both_markers_stay_visible(self, viewport) -> None:
        """The second pick must not replace the first one's marker.

        PyVista's own picked-point representation uses a single actor name for
        every pick, so relying on ``show_point=True`` means a two-point selection
        is never shown as two points.
        """
        viewport.mark_point(0, (0.0, 0.0, 0.0))
        viewport.mark_point(1, (5.0, 0.0, 0.0))
        names = _actor_names(viewport)
        assert viewport._MARKER_NAMES[0] in names
        assert viewport._MARKER_NAMES[1] in names

    def test_a_marker_is_not_itself_pickable(self, viewport) -> None:
        viewport.mark_point(0, (0.0, 0.0, 0.0))
        actor = viewport.plotter.renderer.actors[viewport._MARKER_NAMES[0]]
        assert actor.GetPickable() == 0

    def test_there_is_no_third_point(self, viewport) -> None:
        with pytest.raises(ValueError, match="no point 2"):
            viewport.mark_point(2, (0.0, 0.0, 0.0))

    def test_the_measurement_line_is_drawn_and_cleared(self, viewport) -> None:
        viewport.draw_measurement_line((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        assert viewport._LINE_NAME in _actor_names(viewport)
        viewport.clear_selection_graphics()
        assert viewport._LINE_NAME not in _actor_names(viewport)

    def test_clearing_removes_the_markers_too(self, viewport) -> None:
        viewport.mark_point(0, (0.0, 0.0, 0.0))
        viewport.mark_point(1, (5.0, 0.0, 0.0))
        viewport.clear_selection_graphics()
        names = _actor_names(viewport)
        assert not set(viewport._MARKER_NAMES) & names

    def test_clearing_with_nothing_drawn_is_harmless(self, viewport) -> None:
        viewport.clear_selection_graphics()

    def test_the_axis_preview_extends_past_the_picked_points(self, viewport) -> None:
        """An axis has to be judged against the part, not against the two picks."""
        viewport.draw_axis_preview((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), length=40.0)
        actor = viewport.plotter.renderer.actors[viewport._LINE_NAME]
        xmin, xmax = actor.GetBounds()[:2]
        assert xmax - xmin == pytest.approx(40.0)

    def test_an_axis_preview_needs_a_direction(self, viewport) -> None:
        with pytest.raises(ValueError, match="non-zero direction"):
            viewport.draw_axis_preview((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), length=10.0)


class TestLifecycle:
    def test_clearing_the_scene_disarms_picking(self, viewport) -> None:
        """``Plotter.clear`` leaves the observers installed and the flag set.

        A viewport cleared mid-pick would otherwise stay armed against actors that
        no longer exist, and the next arming would raise.
        """
        viewport.start_point_picking(lambda _point: None)
        viewport.clear()
        assert not viewport.is_picking
        assert _left_observer(viewport) is None

    def test_picking_can_be_re_armed_after_clearing(self, viewport) -> None:
        viewport.start_point_picking(lambda _point: None)
        viewport.clear()
        viewport.start_point_picking(lambda _point: None)
        assert viewport.is_picking

    def test_the_bounds_grid_is_not_a_pick_target(self, viewport) -> None:
        """A click on the grid would report a coordinate out in empty space."""
        for actor in viewport.plotter.renderer.actors.values():
            if actor.GetClassName().startswith("vtkCubeAxes"):
                assert actor.GetPickable() == 0
                return
        pytest.skip("No bounds-grid actor in this VTK build")


# ---------------------------------------------------------------------------
# The window: that the mouse, the controller and the panels are connected
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qt_app):
    from barnes_ui.gui.main_window import MainWindow

    try:
        win = MainWindow()
    except Exception as exc:  # pragma: no cover - no usable OpenGL on this machine
        pytest.skip(f"Could not create the main window: {exc}")
    yield win
    win.viewport.close_viewport()


def _select_purpose(window, purpose: SelectionPurpose) -> None:
    index = window._purpose_combo.findData(purpose)
    assert index >= 0
    window._purpose_combo.setCurrentIndex(index)


class TestWindowWiring:
    def test_the_toggle_arms_the_viewport(self, window) -> None:
        window._measure_button.setChecked(True)
        assert window.viewport.is_picking
        assert window._selection.state is SelectionState.AWAITING_FIRST

    def test_untoggling_disarms_and_cancels(self, window) -> None:
        window._measure_button.setChecked(True)
        window._measure_button.setChecked(False)
        assert not window.viewport.is_picking
        assert window._selection.state is SelectionState.CANCELLED

    def test_two_picks_produce_a_distance_in_the_panel(self, window) -> None:
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._on_point_picked((3.0, 4.0, 0.0))
        text = window._measure_output.toPlainText()
        assert "5.0000" in text
        assert "tessellation" in text

    def test_the_first_pick_is_marked_immediately(self, window) -> None:
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        assert window.viewport._MARKER_NAMES[0] in _actor_names(window.viewport)

    def test_a_missed_click_is_reported_in_the_panel(self, window) -> None:
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._on_pick_missed()
        assert "missed" in window._measure_instruction.text()
        assert window._selection.points == ((0.0, 0.0, 0.0),)

    def test_the_confirm_button_is_disabled_until_two_points_exist(
        self, window
    ) -> None:
        window._measure_button.setChecked(True)
        assert not window._confirm_selection_button.isEnabled()
        window._on_point_picked((0.0, 0.0, 0.0))
        assert not window._confirm_selection_button.isEnabled()
        window._on_point_picked((3.0, 4.0, 0.0))
        assert window._confirm_selection_button.isEnabled()

    def test_clearing_keeps_the_tool_armed(self, window) -> None:
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._clear_measurement()
        assert window._selection.state is SelectionState.AWAITING_FIRST
        assert window.viewport.is_picking
        assert not set(window.viewport._MARKER_NAMES) & _actor_names(window.viewport)

    def test_cancelling_returns_the_mouse_to_the_camera(self, window) -> None:
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._cancel_selection()
        assert not window.viewport.is_picking
        assert not window._measure_button.isChecked()
        assert _left_observer(window.viewport) is None

    def test_picking_can_be_repeated(self, window) -> None:
        for _ in range(3):
            window._measure_button.setChecked(True)
            window._on_point_picked((0.0, 0.0, 0.0))
            window._on_point_picked((0.0, 0.0, 10.0))
            assert "10.0000" in window._measure_output.toPlainText()
            window._measure_button.setChecked(False)

    def test_switching_workspaces_leaves_the_session_alone(self, window) -> None:
        """The workspaces and the viewport are different widgets.

        Worth asserting rather than assuming, and more so since P2 moved the panels
        out of a dock and into a splitter beside the viewport: the viewport is now a
        sibling of the thing being switched, and a selection in progress must not
        notice.
        """
        from barnes_ui.gui.workflow import Workspace

        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        token = window.viewport.pick_session
        for workspace in Workspace:
            window.navigator.set_current(workspace)
        assert window.viewport.pick_session == token
        assert window.viewport.is_picking
        assert window._selection.points == ((0.0, 0.0, 0.0),)


class TestWindowAxisDefinition:
    def test_a_previewed_axis_is_written_nowhere(self, window) -> None:
        _select_purpose(window, SelectionPurpose.JOINT_AXIS)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._on_point_picked((10.0, 0.0, 0.0))
        assert window._selection.state is SelectionState.PREVIEW
        assert window.fea_panel.axis_point() == (0.0, 0.0, 0.0)
        assert "NOT CONFIRMED" in window._measure_output.toPlainText()

    def test_confirming_writes_the_axis_into_the_panels(self, window) -> None:
        _select_purpose(window, SelectionPurpose.JOINT_AXIS)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 2.0, 4.0))
        window._on_point_picked((10.0, 2.0, 4.0))
        window._confirm_selection()

        assert window.fea_panel.axis_point() == pytest.approx((5.0, 2.0, 4.0))
        settings = window.flexure_panel.settings()
        assert settings["joint_origin"] == pytest.approx((5.0, 2.0, 4.0))
        assert settings["joint_direction"] == pytest.approx((1.0, 0.0, 0.0))

    def test_confirming_disarms_but_keeps_the_evidence(self, window) -> None:
        _select_purpose(window, SelectionPurpose.JOINT_AXIS)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._on_point_picked((10.0, 0.0, 0.0))
        window._confirm_selection()
        assert not window.viewport.is_picking
        assert window.viewport._LINE_NAME in _actor_names(window.viewport)

    def test_coincident_picks_cannot_define_an_axis(self, window) -> None:
        _select_purpose(window, SelectionPurpose.JOINT_AXIS)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._on_point_picked((0.01, 0.0, 0.0))
        assert window._selection.state is SelectionState.AWAITING_SECOND
        assert not window._confirm_selection_button.isEnabled()
        assert "same point" in window._measure_instruction.text()

    def test_switching_purpose_mid_pick_starts_over(self, window) -> None:
        """Two points loose enough for a distance are not an axis baseline."""
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        _select_purpose(window, SelectionPurpose.JOINT_AXIS)
        assert window._selection.state is SelectionState.IDLE
        assert not window._measure_button.isChecked()
        assert window._measure_output.toPlainText() == ""


class TestWindowInvalidation:
    def test_importing_another_model_discards_the_selection(self, window) -> None:
        """The original defect at the level the user meets it."""
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))

        window._invalidate_selection("a different model was imported")

        assert window._selection.state is SelectionState.IDLE
        assert window._selection.points == ()
        assert not window._measure_button.isChecked()
        assert not window.viewport.is_picking
        assert "discarded" in window._measure_output.toPlainText()
        # And a point arriving afterwards cannot restart the pair.
        window._on_point_picked((10.0, 0.0, 0.0))
        assert window._selection.points == ()

    def test_a_confirmed_axis_does_not_survive_a_regeneration(self, window) -> None:
        _select_purpose(window, SelectionPurpose.JOINT_AXIS)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))
        window._on_point_picked((10.0, 0.0, 0.0))
        window._confirm_selection()
        assert window._selection.confirmed_axis is not None

        window._invalidate_selection("the geometry was regenerated from parameters")
        assert window._selection.confirmed_axis is None
        assert not set(window.viewport._MARKER_NAMES) & _actor_names(window.viewport)
