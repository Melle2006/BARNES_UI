"""The workspace redesign, as widgets.

Three things are checked here, and the third is the point of the whole exercise:

* the navigation works -- four workspaces, one current at a time, the selector and
  the stack never disagreeing;
* the workflow bar renders what ``assess`` says and nothing else;
* the window's facts are wired to reality, so a parameter that moves after a result
  was computed shows up as a stale result rather than as a tick.

Offscreen Qt, so no display is needed. The window tests construct a real VTK render
window via the viewport and skip the module if that is not possible.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from barnes_ui.gui.panels.geometry_summary import GeometrySummary  # noqa: E402
from barnes_ui.gui.panels.project_header import ProjectHeader  # noqa: E402
from barnes_ui.gui.panels.workflow_bar import WorkflowBar  # noqa: E402
from barnes_ui.gui.workflow import (  # noqa: E402
    StepStatus,
    WorkflowFacts,
    WorkflowStep,
    Workspace,
    assess,
)
from barnes_ui.gui.workspaces import WorkspaceNavigator  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


READY = WorkflowFacts(
    has_model=True,
    model_name="meander.step",
    analysis_ready=True,
    geometry_is_generated=True,
    parameters_match_geometry=True,
    template_parameters_valid=True,
    joint_axis_confirmed=True,
    joint_axis_origin=(6.0, 4.5, 0.6),
    has_base_design=True,
)


class TestWorkspaceNavigator:
    def test_the_first_page_registered_becomes_current(self, qt_app) -> None:
        navigator = WorkspaceNavigator()
        navigator.add_workspace(Workspace.DESIGN, QWidget())
        assert navigator.current() is Workspace.DESIGN
        assert navigator.button_for(Workspace.DESIGN).isChecked()

    def test_switching_moves_the_stack_and_the_selector_together(self, qt_app) -> None:
        navigator = WorkspaceNavigator()
        design, analyse = QWidget(), QWidget()
        navigator.add_workspace(Workspace.DESIGN, design)
        navigator.add_workspace(Workspace.ANALYSE, analyse)

        navigator.set_current(Workspace.ANALYSE)
        assert navigator.current() is Workspace.ANALYSE
        assert navigator.page_for(Workspace.ANALYSE) is analyse
        assert navigator.button_for(Workspace.ANALYSE).isChecked()
        assert not navigator.button_for(Workspace.DESIGN).isChecked()

    def test_the_change_is_emitted_once_and_only_on_a_change(self, qt_app) -> None:
        navigator = WorkspaceNavigator()
        navigator.add_workspace(Workspace.DESIGN, QWidget())
        navigator.add_workspace(Workspace.ANALYSE, QWidget())

        seen: list[Workspace] = []
        navigator.workspace_changed.connect(seen.append)
        navigator.set_current(Workspace.ANALYSE)
        navigator.set_current(Workspace.ANALYSE)
        assert seen == [Workspace.ANALYSE]

    def test_the_blurb_says_what_the_workspace_is_for(self, qt_app) -> None:
        navigator = WorkspaceNavigator()
        navigator.add_workspace(Workspace.COMPARE, QWidget())
        assert navigator.blurb_text() == Workspace.COMPARE.blurb

    def test_registering_a_workspace_twice_raises(self, qt_app) -> None:
        navigator = WorkspaceNavigator()
        navigator.add_workspace(Workspace.DESIGN, QWidget())
        with pytest.raises(ValueError, match="already has a page"):
            navigator.add_workspace(Workspace.DESIGN, QWidget())

    def test_selecting_an_unregistered_workspace_raises(self, qt_app) -> None:
        navigator = WorkspaceNavigator()
        navigator.add_workspace(Workspace.DESIGN, QWidget())
        with pytest.raises(KeyError):
            navigator.set_current(Workspace.COMPARE)


class TestWorkflowBar:
    def test_an_empty_bar_tells_the_user_where_to_start(self, qt_app) -> None:
        bar = WorkflowBar()
        assert "Open a CAD file" in bar.next_action_text()

    def test_every_step_gets_a_clickable_chip(self, qt_app) -> None:
        bar = WorkflowBar()
        for step in WorkflowStep:
            assert bar.chip_for(step).text() == step.label

    def test_clicking_a_chip_emits_its_step(self, qt_app) -> None:
        bar = WorkflowBar()
        seen: list[WorkflowStep] = []
        bar.step_selected.connect(seen.append)
        bar.chip_for(WorkflowStep.ANALYSIS).click()
        assert seen == [WorkflowStep.ANALYSIS]

    def test_the_bar_shows_the_step_that_needs_doing(self, qt_app) -> None:
        bar = WorkflowBar()
        bar.set_workflow(assess(WorkflowFacts()))
        text = bar.next_action_text()
        assert "Geometry" in text
        assert "Not started" in text
        assert "Next:" in text

    def test_a_stale_result_is_what_the_bar_reports(self, qt_app) -> None:
        """Not the five complete steps in front of it."""
        import dataclasses

        bar = WorkflowBar()
        facts = dataclasses.replace(
            READY,
            reduced_order_stiffness=7.558,
            stale_reason="a design parameter changed after the result was computed",
        )
        bar.set_workflow(assess(facts))
        text = bar.next_action_text()
        assert "Analysis" in text
        assert "Needs attention" in text
        assert "parameter changed" in text

    def test_a_chip_tooltip_carries_the_purpose_and_the_state(self, qt_app) -> None:
        bar = WorkflowBar()
        bar.set_workflow(assess(WorkflowFacts()))
        tooltip = bar.chip_for(WorkflowStep.JOINT_AXIS).toolTip()
        assert WorkflowStep.JOINT_AXIS.purpose in tooltip
        assert "Blocked" in tooltip

    def test_a_complete_workflow_does_not_claim_the_design_is_good(self, qt_app) -> None:
        """The one place a green bar could be read as an engineering verdict."""
        import dataclasses

        bar = WorkflowBar()
        facts = dataclasses.replace(
            READY,
            solver_available=True,
            solver_description="ccx 2.22",
            reduced_order_stiffness=7.558,
            sweep_row_count=9,
        )
        bar.set_workflow(assess(facts))
        assert "experimentally validated" in bar.next_action_text()

    def test_the_bar_cannot_invent_a_status(self, qt_app) -> None:
        """It renders a workflow and holds no state of its own."""
        bar = WorkflowBar()
        workflow = assess(WorkflowFacts())
        bar.set_workflow(workflow)
        assert bar.workflow is workflow


class TestProjectHeader:
    def test_no_project_is_stated_rather_than_blank(self, qt_app) -> None:
        header = ProjectHeader("0.1.0")
        assert "No project" in header.project_text()
        assert "nothing loaded" in header.design_text()

    def test_a_project_and_design_are_shown(self, qt_app) -> None:
        header = ProjectHeader("0.1.0")
        header.set_project("a3-study")
        header.set_design("meander (4 runs, unsaved)")
        assert "a3-study" in header.project_text()
        assert "4 runs" in header.design_text()

    def test_the_unsaved_marker_appears_and_clears(self, qt_app) -> None:
        header = ProjectHeader("0.1.0")
        assert header.dirty_text() == ""
        header.set_dirty(True, "generated geometry is in a scratch file")
        assert header.dirty_text() == "UNSAVED"
        header.set_dirty(False)
        assert header.dirty_text() == ""


class TestGeometrySummary:
    def test_the_empty_state_says_what_to_do(self, qt_app) -> None:
        summary = GeometrySummary()
        assert "Nothing loaded" in summary.source_text()
        assert "Open a CAD file" in summary.readiness_text()

    def test_inspection_is_offered_only_once_there_is_something_to_inspect(
        self, qt_app
    ) -> None:
        summary = GeometrySummary()
        assert not summary._inspect.isEnabled()

    def test_a_model_with_no_solids_is_reported_as_not_ready(self, qt_app) -> None:
        """Built by hand, so this needs no CAD kernel."""
        from pathlib import Path

        from barnes_ui.core.cad.model import CadFormat, GeometryModel
        from barnes_ui.core.units import LengthUnit, UnitConfidence

        model = GeometryModel(
            source_path=Path("empty.step"),
            source_format=CadFormat.STEP,
            unit=LengthUnit.MILLIMETRE,
            unit_confidence=UnitConfidence.DECLARED,
        )
        summary = GeometrySummary()
        summary.show_model(model)

        assert "empty.step" in summary.source_text()
        assert "NOT ready" in summary.readiness_text()
        assert "No solid bodies" in summary.readiness_text()
        assert summary._inspect.isEnabled()

    def test_the_origin_of_the_geometry_is_stated(self, qt_app) -> None:
        from pathlib import Path

        from barnes_ui.core.cad.model import CadFormat, GeometryModel
        from barnes_ui.core.units import LengthUnit, UnitConfidence

        def model() -> GeometryModel:
            return GeometryModel(
                source_path=Path("thing.step"),
                source_format=CadFormat.STEP,
                unit=LengthUnit.MILLIMETRE,
                unit_confidence=UnitConfidence.DECLARED,
            )

        imported = GeometrySummary()
        imported.show_model(model(), generated=False)
        generated = GeometrySummary()
        generated.show_model(model(), generated=True)

        assert "imported" in imported.source_text()
        assert "generated from parameters" in generated.source_text()

    def test_a_tessellated_import_is_flagged_in_the_card(self, qt_app) -> None:
        from pathlib import Path

        from barnes_ui.core.cad.model import CadFormat, GeometryModel
        from barnes_ui.core.units import LengthUnit, UnitConfidence

        model = GeometryModel(
            source_path=Path("scan.stl"),
            source_format=CadFormat.STL,
            unit=LengthUnit.MILLIMETRE,
            unit_confidence=UnitConfidence.USER_SET,
        )
        summary = GeometrySummary()
        summary.show_model(model)
        assert "not usable for analysis" in summary.source_text()


# ---------------------------------------------------------------------------
# The window
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


@pytest.fixture
def imported_box(window, box_step):
    """A real STEP import, pushed through the window's own import handler."""
    pytest.importorskip("OCP")
    from barnes_ui.core.cad.registry import load_geometry

    model = load_geometry(box_step)
    window._on_import_finished(model)
    return model


@pytest.fixture
def generated_meander(window, tmp_path):
    """A real generated solid, through the window's own build handler.

    The whole chain: parameters to an OpenCASCADE solid, written to STEP, read back
    through the normal importer, then handed to ``_on_template_built``. Nothing about
    staleness can be tested against a stub, because what makes a result stale is the
    relationship between the parameters that built a solid and the ones on screen.
    """
    pytest.importorskip("OCP")
    from barnes_ui.core.flexure.templates.meander import MeanderParameters
    from barnes_ui.gui.main_window import _template_worker

    parameters = MeanderParameters(
        run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
    )
    window.template_panel.set_parameters(parameters)
    payload = _template_worker(parameters, tmp_path / "meander.step")
    window._on_template_built(payload)
    return parameters


class TestWindowLayout:
    def test_all_four_workspaces_are_present(self, window) -> None:
        assert window.navigator.workspace_count() == len(Workspace)
        for workspace in Workspace:
            assert window.navigator.page_for(workspace) is not None

    def test_design_is_where_the_user_starts(self, window) -> None:
        assert window.navigator.current() is Workspace.DESIGN

    def test_the_viewport_is_not_inside_a_workspace(self, window) -> None:
        """It stays central and visible whichever workspace is selected."""
        for workspace in Workspace:
            page = window.navigator.page_for(workspace)
            assert window.viewport.parent() is not page
            assert window.viewport not in page.findChildren(type(window.viewport))

    def test_nothing_from_the_old_tab_layout_was_dropped(self, window) -> None:
        """Every panel the six peer tabs exposed is still reachable."""
        for panel in (
            window.geometry_panel,
            window.template_panel,
            window.flexure_panel,
            window.fea_panel,
            window.simulation_panel,
            window.optimise_panel,
        ):
            assert panel is not None
            # Reachable means in the widget tree, not merely constructed.
            assert panel.window() is window

    def test_the_inspect_workspace_keeps_the_full_geometry_panel(self, window) -> None:
        page = window.navigator.page_for(Workspace.INSPECT)
        assert window.geometry_panel in page.findChildren(type(window.geometry_panel))

    def test_the_design_workspace_holds_the_summary_and_the_parameters(
        self, window
    ) -> None:
        page = window.navigator.page_for(Workspace.DESIGN)
        assert window.geometry_summary in page.findChildren(GeometrySummary)
        assert window.template_panel in page.findChildren(
            type(window.template_panel)
        )

    def test_the_analyse_workspace_groups_three_panels_one_level_deep(
        self, window
    ) -> None:
        assert window._analyse_tabs.count() == 3
        labels = {window._analyse_tabs.tabText(i) for i in range(3)}
        assert labels == {"Reduced-order model", "Nonlinear FEA", "Motion"}

    def test_the_panels_keep_a_usable_minimum_width(self, window) -> None:
        """A parameter form with its units must not be truncated as the window shrinks."""
        assert window.navigator.minimumWidth() >= 400

    def test_the_viewport_also_has_a_floor(self, window) -> None:
        """Without one the splitter crushes it instead of the panels.

        Stretch factors give a growing window's extra space to the viewport, which
        is right -- and give a shrinking window's loss to the viewport too, which is
        not: at 900 px the panels kept 600 and the 3D view was squeezed to 305, the
        narrowest region on screen. A parameter form scrolls; a 3D view does not.
        """
        assert window.viewport.minimumWidth() >= 400

    def test_the_window_refuses_to_shrink_below_a_usable_layout(self, window) -> None:
        floor = window.minimumSize()
        needed = (
            window.navigator.minimumWidth()
            + window.viewport.minimumWidth()
            + window._measure_dock.minimumWidth()
        )
        assert floor.width() >= needed, (
            f"the window may shrink to {floor.width()} px while its three regions "
            f"need {needed} px between them"
        )

    def test_the_viewport_keeps_the_larger_share(self, window) -> None:
        """Laid out at a real size, because an unshown splitter has no sizes yet."""
        assert window._splitter.widget(0) is window.navigator
        assert window._splitter.widget(1) is window.viewport

        window.resize(1600, 980)
        window.show()
        qt_app = QApplication.instance()
        assert qt_app is not None
        qt_app.processEvents()

        panel_width, viewport_width = window._splitter.sizes()
        assert viewport_width > panel_width, (
            f"panels {panel_width} px, viewport {viewport_width} px"
        )
        window.hide()

    def test_neither_side_of_the_splitter_can_be_collapsed(self, window) -> None:
        """Dragging the handle to the edge must not hide the viewport or the panels."""
        assert not window._splitter.childrenCollapsible()


class TestWindowNavigation:
    def test_clicking_a_workflow_chip_opens_that_workspace(self, window) -> None:
        window.workflow_bar.chip_for(WorkflowStep.COMPARISON).click()
        assert window.navigator.current() is Workspace.COMPARE

        window.workflow_bar.chip_for(WorkflowStep.ANALYSIS).click()
        assert window.navigator.current() is Workspace.ANALYSE

    def test_returning_to_an_earlier_step_is_possible(self, window) -> None:
        """The brief's requirement, which needs something clickable to be real."""
        window.workflow_bar.chip_for(WorkflowStep.ANALYSIS).click()
        window.workflow_bar.chip_for(WorkflowStep.GEOMETRY).click()
        assert window.navigator.current() is Workspace.DESIGN

    def test_the_summary_card_opens_the_full_inspection(self, window) -> None:
        window.geometry_summary.inspect_requested.emit()
        assert window.navigator.current() is Workspace.INSPECT


class TestWindowWorkflowFacts:
    def test_an_empty_window_reports_nothing_complete(self, window) -> None:
        workflow = assess(window._facts())
        assert workflow.statuses_of(StepStatus.COMPLETE) == ()
        assert "Geometry" in window.workflow_bar.next_action_text()

    def test_the_header_starts_with_no_project_and_no_design(self, window) -> None:
        assert "No project" in window.header.project_text()
        assert "nothing loaded" in window.header.design_text()

    def test_importing_a_part_completes_the_geometry_step(
        self, window, imported_box
    ) -> None:
        facts = window._facts()
        assert facts.has_model
        assert facts.analysis_ready
        assert not facts.geometry_is_generated
        assert assess(facts)[WorkflowStep.GEOMETRY].status is StepStatus.COMPLETE

    def test_importing_a_part_names_it_in_the_header_and_the_card(
        self, window, imported_box
    ) -> None:
        assert "box.step" in window.header.design_text()
        assert "box.step" in window.geometry_summary.source_text()
        assert "Ready for analysis" in window.geometry_summary.readiness_text()

    def test_the_next_action_after_an_import_is_the_joint_axis(
        self, window, imported_box
    ) -> None:
        """Parameters is Not started too, but an imported part has none."""
        pending = assess(window._facts()).first_needing_attention()
        assert pending is not None
        assert pending.step is WorkflowStep.JOINT_AXIS

    def test_confirming_an_axis_completes_that_step(self, window, imported_box) -> None:
        """P1's picking and P2's indicator, joined up."""
        from barnes_ui.gui.viewer.selection import SelectionPurpose

        index = window._purpose_combo.findData(SelectionPurpose.JOINT_AXIS)
        window._purpose_combo.setCurrentIndex(index)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 5.0, 1.5))
        window._on_point_picked((10.0, 5.0, 1.5))
        window._confirm_selection()

        facts = window._facts()
        assert facts.joint_axis_confirmed
        assert facts.joint_axis_origin == pytest.approx((5.0, 5.0, 1.5))
        assert assess(facts)[WorkflowStep.JOINT_AXIS].status is StepStatus.COMPLETE
        assert assess(facts)[WorkflowStep.READINESS].status is StepStatus.COMPLETE

    def test_replacing_the_model_un_confirms_the_axis(
        self, window, imported_box
    ) -> None:
        from barnes_ui.gui.viewer.selection import SelectionPurpose

        index = window._purpose_combo.findData(SelectionPurpose.JOINT_AXIS)
        window._purpose_combo.setCurrentIndex(index)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 5.0, 1.5))
        window._on_point_picked((10.0, 5.0, 1.5))
        window._confirm_selection()
        assert window._facts().joint_axis_confirmed

        window._invalidate_selection("a different model was imported")
        assert not window._facts().joint_axis_confirmed

    def test_a_measurement_after_an_axis_does_not_lose_the_axis(
        self, window, imported_box
    ) -> None:
        """The window owns the committed axis; the controller owns the protocol.

        Beginning a new selection resets the controller's confirmed result, which is
        correct for the controller and must not take the engineering input with it.
        """
        from barnes_ui.gui.viewer.selection import SelectionPurpose

        index = window._purpose_combo.findData(SelectionPurpose.JOINT_AXIS)
        window._purpose_combo.setCurrentIndex(index)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 5.0, 1.5))
        window._on_point_picked((10.0, 5.0, 1.5))
        window._confirm_selection()

        measurement = window._purpose_combo.findData(SelectionPurpose.MEASUREMENT)
        window._purpose_combo.setCurrentIndex(measurement)
        window._measure_button.setChecked(True)
        window._on_point_picked((0.0, 0.0, 0.0))

        assert window._selection.confirmed_axis is None, "the controller moved on"
        assert window._facts().joint_axis_confirmed, "the axis is still the input"


class TestWindowStaleResults:
    def test_generating_a_solid_completes_the_parameters_step(
        self, window, generated_meander
    ) -> None:
        facts = window._facts()
        assert facts.geometry_is_generated
        assert facts.generation_warning is None
        assert assess(facts)[WorkflowStep.PARAMETERS].status is StepStatus.COMPLETE

    def test_a_parameter_change_marks_an_existing_result_stale(
        self, window, generated_meander
    ) -> None:
        window._reduced_order_stiffness = 7.558
        window.template_panel._width.setValue(generated_meander.width + 0.2)

        facts = window._facts()
        assert facts.stale_reason is not None
        assert "parameter changed" in facts.stale_reason
        assert (
            assess(facts)[WorkflowStep.ANALYSIS].status is StepStatus.NEEDS_ATTENTION
        )

    def test_a_parameter_change_un_completes_the_parameters_step(
        self, window, generated_meander
    ) -> None:
        """The solid on screen is no longer the one these parameters describe.

        Where it came from is unchanged -- it is still a generated solid -- which is
        why these are two facts and not one. Conflating them made an edited
        parameter look exactly like an imported part.
        """
        window.template_panel._width.setValue(generated_meander.width + 0.2)
        facts = window._facts()
        assert facts.geometry_is_generated
        assert not facts.parameters_match_geometry

        state = assess(facts)[WorkflowStep.PARAMETERS]
        assert state.status is StepStatus.IN_PROGRESS
        assert "stale" in state.detail
        assert "regenerate" in state.next_action

    def test_returning_a_parameter_to_its_built_value_changes_nothing(
        self, window, generated_meander
    ) -> None:
        """Equality against the built parameters, not a dirty flag.

        Nudging a spinbox and putting it back has not changed the design, and
        reporting a stale result for it would train the user to ignore the warning.
        """
        window.template_panel._width.setValue(generated_meander.width)
        facts = window._facts()
        assert facts.parameters_match_geometry
        assert facts.stale_reason is None

    def test_a_parameter_change_with_no_result_marks_nothing(
        self, window, generated_meander
    ) -> None:
        """A warning about nothing is worse than no warning."""
        window.template_panel._width.setValue(generated_meander.width + 0.2)
        assert window._facts().stale_reason is None

    def test_the_bar_reports_the_stale_result(self, window, generated_meander) -> None:
        window._reduced_order_stiffness = 7.558
        window.template_panel._width.setValue(generated_meander.width + 0.2)
        text = window.workflow_bar.next_action_text()
        assert "Needs attention" in text
        assert "out of date" in text

    def test_editing_parameters_does_not_invalidate_an_imported_analysis(
        self, window, imported_box
    ) -> None:
        """The template's spinboxes describe a design the application could build.

        They say nothing about the imported part being analysed, so touching them
        must not mark its result stale.
        """
        window._reduced_order_stiffness = 7.558
        window.template_panel._width.setValue(
            window.template_panel._width.value() + 0.2
        )
        assert window._facts().stale_reason is None
        assert window._facts().reduced_order_stiffness == 7.558

    def test_an_import_clears_results_rather_than_staling_them(
        self, window, imported_box
    ) -> None:
        """Results for a different part are not something to compare against."""
        assert window._facts().reduced_order_stiffness is None
        assert window._facts().stale_reason is None

    def test_a_generation_warning_reaches_the_workflow(self, window) -> None:
        """A dismissed modal dialog stops saying anything; the bar does not."""
        from pathlib import Path

        from barnes_ui.core.cad.model import CadFormat, GeometryModel
        from barnes_ui.core.units import LengthUnit, UnitConfidence

        window._model = GeometryModel(
            source_path=Path("meander.step"),
            source_format=CadFormat.STEP,
            unit=LengthUnit.MILLIMETRE,
            unit_confidence=UnitConfidence.DECLARED,
        )
        window._generation_warning = "measured 61.2 mm^3 against an exact 74.6 mm^3"
        window._refresh_workflow()

        state = assess(window._facts())[WorkflowStep.GEOMETRY]
        assert state.status is StepStatus.NEEDS_ATTENTION
        assert "61.2" in state.detail
        assert "61.2" in window.workflow_bar.next_action_text()


class TestThemeSafety:
    """Colours must not assume a dark desktop.

    The Phase 2 header set ``background: #22262C`` on itself and pale text on its
    labels. On the light system theme this machine actually runs, that rendered as
    three near-black boxes floating on a light window with barely legible text --
    and every one of the 808 tests passed, because each label held exactly the right
    string.

    The rule this enforces: a stylesheet may set a background only if it sets a
    foreground in the same rule. A rule that paints a background and leaves the text
    to the theme is a coin flip on whether the result is readable, and a Qt
    stylesheet's ``background`` is inherited by child widgets while the parent paints
    nothing itself -- so the mistake does not even look like a bar.

    A static scan rather than a rendering check, for the same reason
    ``test_architecture.py`` scans source: a rule inside a rarely taken branch would
    pass a check that only looked at the window as currently built.
    """

    def _stylesheet_literals(self):
        """Every string literal passed to setStyleSheet under gui/, with its site."""
        import ast
        from pathlib import Path

        import barnes_ui

        gui_root = Path(barnes_ui.__file__).parent / "gui"
        found = []
        for module in sorted(gui_root.rglob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setStyleSheet"
                ):
                    continue
                for argument in node.args:
                    for text in _string_parts(argument):
                        found.append((module.name, node.lineno, text))
        return found

    def test_the_scan_finds_something(self) -> None:
        """Guard against the check passing because it matched nothing."""
        assert len(self._stylesheet_literals()) >= 10

    def test_no_stylesheet_paints_a_background_without_a_foreground(self) -> None:
        offenders = [
            f"{name}:{line}: {text.strip()!r}"
            for name, line, text in self._stylesheet_literals()
            if "background" in text and "color:" not in text
        ]
        assert not offenders, (
            "These rules set a background and leave the text colour to the system "
            "theme, so they are unreadable under half of them:\n"
            + "\n".join(offenders)
            + "\nColour the text and inherit the background, or set both together "
            "as the provenance badge does."
        )


def _string_parts(node):
    """Yield the string constants in an expression, through f-strings and joins."""
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        yield "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    elif isinstance(node, ast.BinOp):
        yield from _string_parts(node.left)
        yield from _string_parts(node.right)
