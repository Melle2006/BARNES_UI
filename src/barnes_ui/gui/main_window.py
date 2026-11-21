"""Main application window.

Layout: the 3D viewport fills the centre, the geometry panel docks on the left, and
a measurement panel docks on the right. Later phases add tabs for material, flexure
analysis, assembly integration and hand simulation; the dock arrangement is set up to
accommodate them without restructuring.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.cad.export import write_step
from ..core.cad.model import GeometryModel
from ..core.cad.registry import file_dialog_filter, load_geometry
from ..core.logging_setup import log_file_path
from ..core.project.store import PROJECT_SUFFIX, ProjectStore, ProjectStoreError
from ..core.flexure import extract_members
from ..core.flexure.tracing import trace_centerline
from ..core.flexure.adaptation import verify_regeneration
from ..core.flexure.templates.meander import build_meander
from ..core.fea.joint_stiffness import JointStiffnessSetup, measure_joint_stiffness
from ..core.fea.solver import SolverNotAvailableError, find_solver, probe_solver
from ..core.kinematics.modes import SimulationMode
from ..core.kinematics.profiles import (
    LinearRamp,
    SinusoidalCycle,
    TrapezoidalProfile,
    sample_profiles,
)
from ..core.material import provisional_tpu
from ..core.mechanics import JointAxis, analyse_joint_flexure
from ..core.mechanics.spatial_beam import analyse_joint_flexure_spatial
from .panels.fea_panel import FeaPanel
from .panels.flexure_panel import FlexurePanel
from .panels.geometry_panel import GeometryPanel
from .panels.geometry_summary import GeometrySummary
from .panels.optimise_panel import OptimisePanel
from .panels.plots_panel import PlotsPanel
from .panels.project_header import ProjectHeader
from .panels.simulation_panel import SimulationPanel
from .panels.template_panel import TemplatePanel
from .panels.workflow_bar import WorkflowBar
from .tasks import run_in_background
from .workflow import WorkflowFacts, Workspace, assess
from .workspaces import WorkspaceNavigator
from .viewer.selection import (
    PickOutcome,
    PointSelectionController,
    SelectionPurpose,
    SelectionState,
)
from .viewer.viewport import Viewport

logger = logging.getLogger(__name__)

__all__ = ["MainWindow"]


def _flexure_worker(shape, settings: dict) -> tuple:
    """Run the Phase 2 pipeline off the UI thread.

    A module-level function rather than a method so that nothing about the window is
    reachable from the worker thread. Everything it needs arrives as arguments, and it
    returns plain results for the UI thread to display.
    """
    if settings.get("strategy") == "trace":
        # Path-following extraction, and with it the spatial beam model. The two go
        # together on purpose: a member that needs tracing is one that doubles back,
        # and a member that doubles back has runs along the joint axis that the
        # planar model cannot represent. Pairing them in the UI would be a
        # convenience; pairing them here is the point.
        members = [
            trace_centerline(
                shape,
                seed_point=settings["seed_point"],
                seed_direction=settings["seed_direction"],
                bending_axis=settings["joint_direction"],
            )
        ]
        analyse = analyse_joint_flexure_spatial
    else:
        members = extract_members(
            shape,
            sweep_axis=settings["sweep_axis"],
            bending_axis=settings["joint_direction"],
            start=settings["range_start"],
            end=settings["range_end"],
            samples=settings["samples"],
        )
        analyse = analyse_joint_flexure

    material = provisional_tpu(settings["youngs_modulus"])
    joint = JointAxis(
        origin=settings["joint_origin"], direction=settings["joint_direction"]
    )
    curve, stiffness = analyse(
        members,
        material,
        joint,
        max_angle_rad=np.radians(settings["max_angle_deg"]),
        steps=settings["steps"],
        include_shear=settings["include_shear"],
        include_axial=settings["include_axial"],
    )
    return curve, stiffness, members, settings


def _template_worker(parameters, destination: Path) -> tuple:
    """Build a meander solid and read it back through the normal import path.

    Written to STEP and re-imported rather than handed straight to the viewport.
    Two reasons, and the second is the real one. STEP declares its unit, so the
    re-imported model is analysis-ready in the same sense an imported part is --
    whereas a model fabricated in memory would have to claim a unit confidence
    nobody set. And it means the generated part travels through exactly the same
    reader as a SolidWorks export, so a template whose solid the importer dislikes
    fails here rather than three panels later.

    The volume check is the Phase 4 criterion 2 test applied to every build: the
    measured volume against the exact value the parameters imply.
    """
    shape = build_meander(parameters)
    write_step(shape, destination)
    model = load_geometry(destination)
    issue = None
    if model.solids:
        issue = verify_regeneration(parameters, model.solids[0].volume)
    return parameters, model, issue


def _fea_worker(shape, modulus: float, setup: JointStiffnessSetup,
                progress=None, cancellation=None):
    """Run one joint-stiffness measurement off the UI thread."""
    solver = find_solver()
    if solver is None:
        raise SolverNotAvailableError(
            "CalculiX was not found, so there is no FEA to run. The application "
            "does not substitute the reduced-order model for it."
        )
    solver = probe_solver(solver)
    return measure_joint_stiffness(
        shape, provisional_tpu(modulus), setup, solver,
        progress=progress, cancellation=cancellation,
        title="Joint rotational stiffness",
    )


class MainWindow(QMainWindow):
    """The application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Barnes UI {__version__}")
        self.resize(1600, 980)
        # Below this the three regions cannot all be usable at once: the panels
        # need 400, the viewport 420 and the Measure dock 240, and a layout that
        # silently collapses one of them is worse than a window that declines to
        # get smaller.
        self.setMinimumSize(1120, 720)

        self._model: GeometryModel | None = None
        self._project: ProjectStore | None = None

        # -- facts the workflow indicator is derived from.
        #
        # Held here rather than read back out of the panels, because several of them
        # are answers to "what has happened", which no widget knows. A panel can say
        # what its spinboxes contain; only the window knows that the result on screen
        # was computed before the parameters moved.
        self._geometry_is_generated = False
        self._generation_warning: str | None = None
        #: The parameters the displayed solid was actually built from, so that a
        #: later edit can be told from the values that produced it.
        self._built_parameters = None
        self._joint_axis = None            # TwoPointSelection, once confirmed
        self._reduced_order_stiffness: float | None = None
        self._fea_stiffness: float | None = None
        self._fea_failure: str | None = None
        self._stale_reason: str | None = None
        self._analysis_running = False
        self._sweep_row_count = 0
        self._has_base_design = False
        self._unsaved_detail: str | None = None
        # Set once the header and the workflow bar exist. A panel signal that fires
        # while the window is still being built must not reach a widget that has not
        # been created yet.
        self._ui_ready = False
        # References to running background work. Dropping these lets Qt collect the
        # thread mid-run, which crashes the process -- see gui/tasks.py.
        self._jobs: list[tuple[object, object]] = []
        # The two-point selection protocol, and the token that ties a pick to the
        # session that asked for it. A point arriving with a stale token is dropped.
        self._selection = PointSelectionController()
        self._selection_token: int | None = None

        self.viewport = Viewport(self)

        self._build_panels()
        self._build_central()
        self._build_measurement_dock()
        self._build_plots_dock()
        self._build_menus()
        self._build_status_bar()

        self._refresh_workflow()
        self._set_status("Ready. Open a CAD file to begin.")

    # -- construction ----------------------------------------------------------

    def _build_panels(self) -> None:
        """Create the panels and connect them. Layout is ``_build_central``'s job."""
        self.geometry_panel = GeometryPanel(self)
        self.geometry_panel.solid_visibility_changed.connect(
            self.viewport.set_solid_visible
        )
        self.geometry_panel.unit_changed.connect(self._on_unit_changed)

        self.geometry_summary = GeometrySummary(self)
        self.geometry_summary.inspect_requested.connect(
            lambda: self._go_to_workspace(Workspace.INSPECT)
        )

        self.flexure_panel = FlexurePanel(self)
        self.flexure_panel.analysis_requested.connect(self._run_flexure_analysis)
        self.flexure_panel.axis_suggestion_requested.connect(self._suggest_joint_axis)

        self.template_panel = TemplatePanel(self)
        self.template_panel.build_requested.connect(self._build_template)
        self.template_panel.export_requested.connect(self._export_template)
        self.template_panel.parameters_changed.connect(self._on_parameters_changed)

        self.fea_panel = FeaPanel(self)
        self.fea_panel.analysis_requested.connect(self._run_fea)
        self.fea_panel.cancel_requested.connect(self._cancel_fea)
        self.fea_panel.axis_suggestion_requested.connect(self._suggest_fea_axis)

        self.simulation_panel = SimulationPanel(self)
        self.simulation_panel.run_requested.connect(self._run_simulation)

        self.optimise_panel = OptimisePanel(self)
        self.optimise_panel.sweep_finished.connect(self._on_sweep_finished)

    def _build_central(self) -> None:
        """Header, workflow bar, then the workspaces beside the viewport.

        A splitter rather than a dock for the panels. The viewport is the thing being
        worked on and has to stay large, which a splitter states once -- give the
        panels their minimum and the rest to the view -- where four dock widgets left
        it to whichever one Qt sized first. The header and the workflow bar span the
        full width above both, because where you are in the workflow is not a property
        of the panel you happen to be looking at.
        """
        self.header = ProjectHeader(__version__, self)

        self.workflow_bar = WorkflowBar(self)
        self.workflow_bar.step_selected.connect(self._on_step_selected)

        self.navigator = WorkspaceNavigator(self)
        self.navigator.add_workspace(Workspace.DESIGN, self._build_design_page())
        self.navigator.add_workspace(Workspace.ANALYSE, self._build_analyse_page())
        self.navigator.add_workspace(Workspace.COMPARE, self._build_compare_page())
        self.navigator.add_workspace(Workspace.INSPECT, self._build_inspect_page())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.navigator)
        splitter.addWidget(self.viewport)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # Both sides get a minimum, and the viewport's is the one that matters.
        #
        # With a minimum on the panels alone, stretch factors give every pixel of a
        # resize to the viewport -- which is right while the window grows and wrong
        # while it shrinks: at 900 px the panels kept 600 and the viewport was
        # crushed to 305, the narrowest region on screen. A minimum on the viewport
        # forces the splitter to take the space out of the panels instead, which is
        # the correct order: a parameter form scrolls, a 3D view does not.
        self.navigator.setMinimumWidth(400)
        self.viewport.setMinimumWidth(420)
        splitter.setSizes([480, 1100])
        splitter.setChildrenCollapsible(False)
        self._splitter = splitter

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self._rule())
        layout.addWidget(self.workflow_bar)
        layout.addWidget(self._rule())
        layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(container)
        self._ui_ready = True

    def _build_design_page(self) -> QWidget:
        """Workspace A: what the part is.

        The geometry summary first, because every parameter below it is read against
        what is currently on screen. The full Geometry panel is in Inspect -- a body
        tree and thirty measured properties beside a parameter form crowds out the
        controls the user came to this workspace for.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.geometry_summary)
        layout.addWidget(self._scrolled(self.template_panel), stretch=1)
        return page

    def _build_analyse_page(self) -> QWidget:
        """Workspace B: one level of sub-tabs, named after the question each answers.

        Three panels in one column is roughly three thousand pixels of form, so they
        are grouped -- but grouped by what they tell you rather than by which module
        they live in, and only one level deep.
        """
        tabs = QTabWidget()
        tabs.addTab(self._scrolled(self.flexure_panel), "Reduced-order model")
        tabs.addTab(self._scrolled(self.fea_panel), "Nonlinear FEA")
        tabs.addTab(self._scrolled(self.simulation_panel), "Motion")
        tabs.setTabToolTip(
            0,
            "Castigliano on the extracted centreline. Fast, linear, sound for "
            "ranking variants and unsound for an absolute torque.",
        )
        tabs.setTabToolTip(
            1, "CalculiX, nonlinear and hyperelastic. Needs the solver installed."
        )
        tabs.setTabToolTip(
            2,
            "Kinematic preview, or a reduced-order pass driven by a joint spring "
            "fitted to FEA results.",
        )
        self._analyse_tabs = tabs
        return tabs

    def _build_compare_page(self) -> QWidget:
        return self._scrolled(self.optimise_panel)

    def _build_inspect_page(self) -> QWidget:
        return self._scrolled(self.geometry_panel)

    @staticmethod
    def _rule() -> QFrame:
        """A one-pixel separator, drawn in the theme's own colours.

        Structure without a coloured band: the header and the workflow bar need to
        read as separate from the workspaces below them, and a painted background
        is what made the header unreadable on a light desktop.
        """
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    @staticmethod
    def _scrolled(widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        return area

    # -- workflow state --------------------------------------------------------

    def _facts(self) -> WorkflowFacts:
        """Assemble what is true right now. The only place facts are gathered."""
        model = self._model
        axis = self._joint_axis
        return WorkflowFacts(
            has_model=model is not None,
            model_name=model.source_path.name if model else None,
            model_is_exact=model.is_exact if model else True,
            analysis_ready=bool(model and model.is_analysis_ready),
            readiness_reasons=(
                tuple(model.analysis_readiness_reasons()) if model else ()
            ),
            geometry_is_generated=self._geometry_is_generated,
            parameters_match_geometry=(
                self._built_parameters is not None
                and self._built_parameters == self.template_panel.parameters()
            ),
            generation_warning=self._generation_warning,
            template_parameters_valid=self.template_panel.parameters() is not None,
            template_blocked_reason=self.template_panel.blocking_reason(),
            joint_axis_confirmed=axis is not None,
            joint_axis_origin=axis.origin if axis is not None else None,
            solver_available=self.fea_panel.solver_available,
            solver_description=self.fea_panel.solver_description,
            analysis_running=self._analysis_running,
            reduced_order_stiffness=self._reduced_order_stiffness,
            fea_stiffness=self._fea_stiffness,
            fea_failure=self._fea_failure,
            stale_reason=self._stale_reason,
            has_base_design=self._has_base_design,
            sweep_row_count=self._sweep_row_count,
            variant_count=0,  # named variants are not implemented in this build
        )

    def _refresh_workflow(self) -> None:
        """Re-assess and re-render. Cheap, so it is called after anything changes."""
        if not self._ui_ready:
            return
        workflow = assess(self._facts())
        self.workflow_bar.set_workflow(workflow)

        self.header.set_project(self._project.name if self._project else None)
        self.header.set_design(self._design_label())
        self.header.set_dirty(
            self._unsaved_detail is not None, self._unsaved_detail
        )

    def _design_label(self) -> str | None:
        """Name the geometry on screen, honestly.

        Named design variants are not implemented, so a generated flexure has no name
        of its own; saying "unsaved" is accurate where borrowing the scratch file's
        name would imply a saved design that does not exist.
        """
        if self._model is None:
            return None
        if self._geometry_is_generated:
            parameters = self.template_panel.parameters()
            runs = f"{parameters.n_runs} runs" if parameters else "generated"
            return f"meander ({runs}, unsaved)"
        return self._model.source_path.name

    def _mark_stale(self, reason: str) -> None:
        """Record that the displayed results no longer match the inputs.

        Only when there is something to invalidate. Marking a project with no results
        stale would put a warning on screen about nothing.
        """
        if self._reduced_order_stiffness is None and self._fea_stiffness is None:
            return
        self._stale_reason = reason
        self._refresh_workflow()

    def _on_parameters_changed(self) -> None:
        """A parameter moved, so the generated solid may no longer match it.

        Only when the displayed geometry was generated from parameters. An imported
        part has no parametric history -- editing the template's spinboxes while an
        imported A3 is on screen changes a design the application could build, not
        the one being analysed, and invalidating that analysis would be wrong.

        When it does apply there are two consequences. The solid stops counting as
        generated-from-these-parameters, which sends the Parameters step back to
        "generate the CAD" instead of leaving it Complete. And any result computed
        from it is stale -- stiffness goes as width cubed, so a small edit is not a
        small error.
        """
        if not self._geometry_is_generated:
            return

        parameters = self.template_panel.parameters()
        if parameters is None or parameters == self._built_parameters:
            # Nudging a spinbox and putting it back has not changed the design.
            # Compared by value rather than tracked with a dirty flag, so that it
            # cannot report a stale result for a design that is identical.
            self._refresh_workflow()
            return

        self._mark_stale(
            "a design parameter changed after the solid was generated, so the "
            "geometry on screen is not the geometry these parameters describe"
        )
        self._refresh_workflow()

    def _on_step_selected(self, step) -> None:
        """A click on the workflow bar goes to the workspace that owns that step."""
        self._go_to_workspace(step.workspace)
        state = assess(self._facts()).state_for(step)
        self._set_status(state.summary().replace("\n", "  ") )

    def _go_to_workspace(self, workspace) -> None:
        self.navigator.set_current(workspace)

    def _on_sweep_finished(self, result) -> None:
        """Count what a sweep evaluated.

        ``evaluations`` only. Designs the template refused to build are in
        ``rejected`` and are not candidates that were compared -- counting them would
        inflate the figure the workflow reports.
        """
        self._sweep_row_count = len(result.evaluations)
        self._refresh_workflow()

    def _build_plots_dock(self) -> None:
        self.plots_panel = PlotsPanel(self)
        dock = QDockWidget("Plots", self)
        dock.setWidget(self.plots_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        # A minimum only, not a preferred size. Set too high, Qt gives the dock most of
        # the window the moment it appears and the 3D view is squeezed to a sliver.
        dock.setMinimumHeight(220)
        dock.hide()  # shown once there is something to plot
        self._plots_dock = dock

    def _build_measurement_dock(self) -> None:
        """Right dock: the two-point selection tool.

        One tool, two purposes, and the difference between them stated on screen
        rather than implied. A measurement is a number you read; an axis is an
        engineering input the stiffness result is acutely sensitive to, so it is not
        available to anything until it has been confirmed.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        purpose_row = QHBoxLayout()
        purpose_row.addWidget(QLabel("Pick for:"))
        self._purpose_combo = QComboBox()
        self._purpose_combo.addItem(
            "Distance between two points", userData=SelectionPurpose.MEASUREMENT
        )
        self._purpose_combo.addItem(
            "Joint axis from two points", userData=SelectionPurpose.JOINT_AXIS
        )
        self._purpose_combo.setToolTip(
            "A distance is read off and used by nobody. A joint axis, once "
            "confirmed, is written into the Flexure and FEA panels and changes "
            "every torque they report."
        )
        self._purpose_combo.currentIndexChanged.connect(self._on_purpose_changed)
        purpose_row.addWidget(self._purpose_combo, stretch=1)
        layout.addLayout(purpose_row)

        self._measure_button = QPushButton("Pick two points")
        self._measure_button.setCheckable(True)
        self._measure_button.toggled.connect(self._on_measure_toggled)
        layout.addWidget(self._measure_button)

        # The instruction, and the only place the current state is spelled out.
        # Taken verbatim from the controller so that the two cannot disagree.
        self._measure_instruction = QLabel()
        self._measure_instruction.setWordWrap(True)
        font = QFont()
        font.setBold(True)
        self._measure_instruction.setFont(font)
        layout.addWidget(self._measure_instruction)

        button_row = QHBoxLayout()
        self._confirm_selection_button = QPushButton("Confirm")
        self._confirm_selection_button.clicked.connect(self._confirm_selection)
        button_row.addWidget(self._confirm_selection_button)

        clear = QPushButton("Clear")
        clear.setToolTip("Drop the picked points and stay in picking mode.")
        clear.clicked.connect(self._clear_measurement)
        button_row.addWidget(clear)

        cancel = QPushButton("Cancel")
        cancel.setToolTip("Abandon the operation and return the mouse to the camera.")
        cancel.clicked.connect(self._cancel_selection)
        button_row.addWidget(cancel)
        layout.addLayout(button_row)

        self._measure_output = QTextEdit()
        self._measure_output.setReadOnly(True)
        self._measure_output.setPlaceholderText(
            "Enable picking, then click two points on the model."
        )
        layout.addWidget(self._measure_output)

        note = QLabel(
            "Points are picked on the display tessellation, so a measurement carries "
            "the mesh's chord tolerance. Snapping to exact vertices and edges is not "
            "implemented."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9AA3AD;")
        layout.addWidget(note)

        dock = QDockWidget("Measure", self)
        dock.setWidget(widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setMinimumWidth(240)
        dock.resize(300, dock.height())
        self._measure_dock = dock

        self._refresh_selection_ui()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        self._add_action(
            file_menu, "&Open CAD file...", self._open_cad, QKeySequence.StandardKey.Open
        )
        file_menu.addSeparator()
        self._add_action(file_menu, "&New project...", self._new_project)
        self._add_action(file_menu, "Open &project...", self._open_project)
        self._add_action(
            file_menu, "Add current model to project", self._add_to_project
        )
        file_menu.addSeparator()
        self._add_action(file_menu, "E&xit", self.close, QKeySequence.StandardKey.Quit)

        view_menu = self.menuBar().addMenu("&View")
        self._add_action(view_menu, "&Isometric", self.viewport.view_iso)
        self._add_action(view_menu, "&Front", self.viewport.view_front)
        self._add_action(view_menu, "&Top", self.viewport.view_top)
        self._add_action(view_menu, "&Right", self.viewport.view_right)
        view_menu.addSeparator()
        self._add_action(view_menu, "Fit to &window", self.viewport.fit)

        section = QAction("&Section plane", self)
        section.setCheckable(True)
        section.toggled.connect(self.viewport.enable_section)
        view_menu.addAction(section)

        help_menu = self.menuBar().addMenu("&Help")
        self._add_action(help_menu, "&Supported formats", self._show_formats)
        self._add_action(help_menu, "&About", self._show_about)

    def _add_action(self, menu, text, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _build_status_bar(self) -> None:
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(220)
        self._progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._progress)

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    # -- CAD import ------------------------------------------------------------

    def _open_cad(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self, "Open CAD file", "", file_dialog_filter()
        )
        if not path_text:
            return
        self.load_file(Path(path_text))

    def load_file(self, path: Path) -> None:
        """Import a file on a worker thread.

        Import is off the UI thread because a large STEP assembly takes seconds to
        parse and measure, and a frozen window during that time looks like a crash.
        """
        self._set_status(f"Importing {path.name}...")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # indeterminate: the reader reports no progress
        self.setEnabled(False)

        job = run_in_background(
            self,
            load_geometry,
            path,
            on_finished=self._on_import_finished,
            on_failed=self._on_import_failed,
        )
        self._jobs.append(job)

    def _on_import_finished(self, model: GeometryModel) -> None:
        self._finish_job()
        self._invalidate_selection("a different model was imported")
        self._model = model
        # An import replaces the design, so nothing computed for the previous one
        # survives. Cleared rather than marked stale: a stale result is one you can
        # still compare against, and these are results for a different part.
        self._geometry_is_generated = False
        self._built_parameters = None
        self._generation_warning = None
        self._reduced_order_stiffness = None
        self._fea_stiffness = None
        self._fea_failure = None
        self._stale_reason = None
        self._unsaved_detail = (
            None
            if self._project is None
            else f"{model.source_path.name} is not in the project yet."
        )

        self.geometry_panel.show_model(model)
        self.geometry_summary.show_model(model, generated=False)
        self.viewport.show_model(model)
        self.flexure_panel.set_enabled_for_model(model)
        self.flexure_panel.clear_results()
        self.plots_panel.clear()
        self._plots_dock.hide()
        self._refresh_workflow()

        summary = (
            f"{model.source_path.name}: {model.solid_count} body/bodies, "
            f"{model.total_volume:.6g} {model.unit.symbol}^3 total"
        )
        if not model.is_analysis_ready:
            summary += "  -  NOT ready for analysis (see Geometry panel)"
        self._set_status(summary)
        logger.info("Displayed %s", model.source_path)

    def _on_import_failed(self, message: str, detail: str) -> None:
        self._finish_job()
        self._set_status("Import failed.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Could not import file")
        box.setText(message)
        box.setDetailedText(detail)
        box.exec()

    def _finish_job(self) -> None:
        self._progress.setVisible(False)
        self._progress.setRange(0, 100)
        self.setEnabled(True)

    # -- flexure analysis ------------------------------------------------------

    def _suggest_joint_axis(self) -> None:
        """Propose a joint axis from the model's overall geometry.

        A suggestion, not a determination. Two attachment features either side of a
        joint do not establish where its axis lies -- the axis can be offset dorsally
        or palmarly, and a millimetre of offset changes the moment arm and hence the
        torque. The point of offering one is that an axis is far easier to check in
        the viewport than to type in correctly.
        """
        if self._model is None or not self._model.solids:
            return
        box = self._model.overall_bounding_box
        if box is None:
            return

        # Midway along the long axis, centred laterally, at the mid-height of the
        # attachment features rather than of the whole part -- the arch pushes the
        # overall bounding box upward and would bias a naive mid-height.
        centre = box.centre
        origin = (centre[0], centre[1], box.zmin + 0.35 * (box.zmax - box.zmin))
        self.flexure_panel.set_joint_axis(origin, (1.0, 0.0, 0.0))
        self._set_status(
            "Joint axis suggested from the bounding box. Check it against the model "
            "before running - this is a guess, not a measurement."
        )

    def _run_flexure_analysis(self, settings: dict) -> None:
        if self._model is None or not self._model.solids:
            return
        if not self._model.is_analysis_ready:
            QMessageBox.warning(
                self, "Not ready for analysis",
                "This model is not ready for analysis:\n\n"
                + "\n".join(f"- {r}" for r in self._model.analysis_readiness_reasons()),
            )
            return

        shape = self._model.solids[0].shape
        self._set_status("Extracting centrelines and running reduced-order analysis...")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self.setEnabled(False)

        job = run_in_background(
            self,
            _flexure_worker,
            shape,
            settings,
            on_finished=self._on_flexure_finished,
            on_failed=self._on_flexure_failed,
        )
        self._jobs.append(job)

    def _on_flexure_finished(self, payload: tuple) -> None:
        self._finish_job()
        curve, stiffness, members, settings = payload

        self.flexure_panel.show_results(
            curve, stiffness, members, settings["max_angle_deg"]
        )
        self.plots_panel.show_analysis(curve, members)
        self._plots_dock.show()
        # Give the plots roughly a third of the height, so the model stays visible
        # beside its results rather than being pushed off screen.
        self.resizeDocks(
            [self._plots_dock], [max(300, int(self.height() * 0.34))], Qt.Orientation.Vertical
        )

        # Hand the number to the FEA panel so that, once an FEA of the same joint
        # finishes, the two can be shown together with the gap as a percentage.
        # That comparison is Phase 3 criterion 7 and is the most useful single thing
        # this application reports.
        self.fea_panel.set_reduced_order_stiffness(stiffness.rotational_stiffness)

        # A fresh result for the inputs as they stand: whatever made the previous one
        # stale has been answered.
        self._reduced_order_stiffness = stiffness.rotational_stiffness
        self._stale_reason = None
        self._refresh_workflow()

        self._set_status(
            f"Reduced-order analysis complete: {stiffness.rotational_stiffness:.6g} "
            f"N.mm/rad at neutral  -  {curve.provenance.label} result, see the "
            "assumptions panel"
        )

    def _on_flexure_failed(self, message: str, detail: str) -> None:
        self._finish_job()
        self._set_status("Flexure analysis failed.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Flexure analysis failed")
        box.setText(message)
        box.setDetailedText(detail)
        box.exec()

    # -- parametric template ---------------------------------------------------

    def _build_template(self, parameters) -> None:
        """Build the meander and show it, replacing whatever is displayed."""
        destination = self._scratch_directory() / "generated_meander.step"
        self._set_status("Building the meander...")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self.setEnabled(False)

        job = run_in_background(
            self, _template_worker, parameters, destination,
            on_finished=self._on_template_built,
            on_failed=self._on_template_failed,
        )
        self._jobs.append(job)

    def _on_template_built(self, payload: tuple) -> None:
        self._finish_job()
        parameters, model, issue = payload
        self._invalidate_selection("the geometry was regenerated from parameters")
        self._model = model
        self._geometry_is_generated = True
        self._built_parameters = parameters
        self._has_base_design = True
        self._reduced_order_stiffness = None
        self._fea_stiffness = None
        self._fea_failure = None
        self._stale_reason = None
        self._unsaved_detail = (
            "This flexure was generated from parameters and exists only in a scratch "
            "file. Export it, or add it to a project, to keep it."
        )

        self.geometry_panel.show_model(model)
        self.geometry_summary.show_model(model, generated=True)
        self.viewport.show_model(model)
        self.flexure_panel.set_enabled_for_model(model)
        self.flexure_panel.clear_results()
        self.optimise_panel.set_base_design(parameters)

        # The template knows this part's geometry exactly, so the flexure panel can
        # be set up for it rather than left for the user to work out: a meander
        # needs the tracer, and the first run starts at the origin heading along X.
        self.flexure_panel.select_strategy("trace")
        self.flexure_panel.set_trace_seed(
            (0.0, 0.0, parameters.thickness / 2.0), (1.0, 0.0, 0.0)
        )

        # Recorded on the window, not only shown in a dialog. A modal warning that
        # has been clicked away leaves a solid on screen that must not be analysed
        # and nothing saying so; the workflow bar keeps saying it, and the Readiness
        # and Analysis steps stay blocked until the geometry is regenerated.
        self._generation_warning = issue.message if issue is not None else None
        self._refresh_workflow()

        if issue is not None:
            QMessageBox.warning(
                self, "Regenerated volume does not match the parameters",
                issue.message
                + "\n\nThe solid was still built and displayed, because looking at "
                  "it is how you work out what went wrong. Do not analyse it.",
            )
            self._set_status("Built, but the volume check failed - see the warning.")
            return

        self._set_status(
            f"Built: {parameters.describe()}  -  volume matches the exact value the "
            "parameters imply."
        )

    def _on_template_failed(self, message: str, detail: str) -> None:
        self._finish_job()
        self._set_status("Could not build the meander.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Could not build the meander")
        box.setText(message)
        box.setDetailedText(detail)
        box.exec()

    def _export_template(self, parameters) -> None:
        path_text, _ = QFileDialog.getSaveFileName(
            self, "Export meander as STEP", "meander.step", "STEP (*.step *.stp)"
        )
        if not path_text:
            return
        try:
            write_step(build_meander(parameters), Path(path_text))
        except Exception as exc:  # noqa: BLE001 - reported to the user
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self._set_status(f"Exported {Path(path_text).name}.")

    def _scratch_directory(self) -> Path:
        """Somewhere to put generated geometry, outside any synced folder.

        Solver and generator scratch files must not live inside OneDrive: a sync
        starting mid-write is a corrupt file, and the project directory is usually
        inside one. Risk R11.
        """
        import tempfile

        directory = Path(tempfile.gettempdir()) / "barnes_ui_generated"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # -- finite element analysis -----------------------------------------------

    def _run_fea(self, settings: dict) -> None:
        if self._model is None or not self._model.solids:
            QMessageBox.information(
                self, "Nothing to analyse",
                "Open a CAD file or build a meander first.",
            )
            return
        if not self._model.is_analysis_ready:
            QMessageBox.warning(
                self, "Not ready for analysis",
                "This model is not ready for analysis:\n\n"
                + "\n".join(f"- {r}" for r in self._model.analysis_readiness_reasons()),
            )
            return

        box = self._model.overall_bounding_box
        if box is None:
            return
        # Span the longest bounding-box direction, which is the axis a flexure
        # bridges along. It is a default, shown in the status bar so it can be
        # argued with, not an inference about the design.
        span_axis = int(max(range(3), key=lambda i: box.size[i]))

        axis_point = settings["axis_point"]
        if all(value == 0.0 for value in axis_point):
            QMessageBox.information(
                self, "No joint axis",
                "The joint axis point is still at the origin. STEP carries no mates, "
                "so the axis has to be stated -- press 'Suggest from the bounding "
                "box' and then check it against the model, or type it in.",
            )
            return

        setup = JointStiffnessSetup(
            attachment_depth=settings["collar_depth"],
            axis_point=axis_point,
            rotation_deg=settings["rotation_deg"],
            span_axis=span_axis,
            smallest_feature=settings["smallest_dimension"],
            elements_through_thickness=settings["elements_through_thickness"],
            second_order=settings["second_order"],
        )

        self._set_status(
            f"Meshing and submitting to CalculiX. Spanning axis "
            f"{'XYZ'[span_axis]}, attachment depth "
            f"{settings['collar_depth']:g} mm."
        )
        self._progress.setVisible(True)
        self._progress.setRange(0, 100)
        self.fea_panel.set_running(True)
        self._analysis_running = True
        self._fea_failure = None
        self._refresh_workflow()

        job = run_in_background(
            self, _fea_worker,
            self._model.solids[0].shape,
            12.0,
            setup,
            accepts_progress=True,
            accepts_token=True,
            on_progress=self._on_fea_progress,
            on_finished=self._on_fea_finished,
            on_failed=self._on_fea_failed,
            on_cancelled=self._on_fea_cancelled,
        )
        self._jobs.append(job)
        self._fea_job = job

    def _on_fea_progress(self, fraction: float, message: str) -> None:
        if fraction >= 0:
            self._progress.setValue(int(fraction * 100))
        if message:
            self._set_status(message)

    def _on_fea_finished(self, outcome) -> None:
        self._finish_job()
        self.fea_panel.set_running(False)
        self._analysis_running = False
        self.fea_panel.show_result(
            outcome.result, outcome.stiffness, outcome.setup.rotation_deg
        )
        if outcome.succeeded:
            # A solve that ran is not the same as a solve that produced a result,
            # which is why the stiffness is only recorded on the succeeded branch.
            self._fea_stiffness = outcome.stiffness
            self._fea_failure = None
            self._stale_reason = None
            self._set_status(
                f"FEA complete: {outcome.stiffness:.6g} N.mm/rad. "
                f"{outcome.result.convergence.summary}"
            )
        else:
            self._fea_stiffness = None
            self._fea_failure = str(outcome.failure)
            self._set_status(f"FEA produced no usable result. {outcome.failure}")
        self._refresh_workflow()

    def _on_fea_failed(self, message: str, detail: str) -> None:
        self._finish_job()
        self.fea_panel.set_running(False)
        self._analysis_running = False
        self._fea_stiffness = None
        self._fea_failure = message
        self._refresh_workflow()
        self._set_status("FEA failed.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("FEA failed")
        box.setText(message)
        box.setDetailedText(detail)
        box.exec()

    def _on_fea_cancelled(self) -> None:
        self._finish_job()
        self.fea_panel.set_running(False)
        self._analysis_running = False
        # Not a failure: a cancelled run produced nothing and nothing is claimed.
        self._fea_failure = None
        self._refresh_workflow()
        self._set_status("FEA cancelled.")

    def _cancel_fea(self) -> None:
        job = getattr(self, "_fea_job", None)
        if job is not None:
            job[1].token.cancel()
            self._set_status("Cancelling after the current increment...")

    def _suggest_fea_axis(self) -> None:
        """Fill the FEA panel's axis point from the bounding box, and say so.

        The suggestion is the box centre, which is a starting point and not a
        determination -- on an arched flexure it sits above the real joint. The
        status bar says that every time, because the number looks equally
        authoritative either way.
        """
        if self._model is None or not self._model.solids:
            return
        box = self._model.overall_bounding_box
        if box is None:
            return
        self.fea_panel.set_axis_point(box.centre)
        self._set_status(
            "Axis point suggested from the bounding box. On a part whose flexure "
            "arches away from the joint this sits above the real axis -- check it "
            "in the viewport before running."
        )

    # -- hand simulation -------------------------------------------------------

    def _run_simulation(self, settings: dict) -> None:
        """Run a Mode 1 preview or a Mode 2 reduced-order pass on one joint.

        Deliberately a single joint rather than a whole hand. A chain needs joint
        axes confirmed on an imported assembly, which is Phase 4 work the GUI does
        not yet expose; offering a hand whose axes were guessed would be exactly the
        failure risk R4 describes.
        """
        profile_kind = settings["profile"]
        start, end = settings["start"], settings["end"]
        if profile_kind == "ramp":
            profile = LinearRamp(start, end)
        elif profile_kind == "sinusoid":
            profile = SinusoidalCycle(start, end)
        else:
            profile = TrapezoidalProfile(start, end)

        schedule = sample_profiles({"joint": profile}, steps=settings["steps"])

        if settings["mode"] is SimulationMode.KINEMATIC_PREVIEW:
            from ..core.kinematics.modes import KinematicPose

            poses = [
                KinematicPose(angles=dict(angles), time=time)
                for time, angles in schedule
            ]
            self.simulation_panel.show_preview(poses)
            self._set_status(
                f"Kinematic preview: {len(poses)} poses. No force or torque is "
                "reported, because none was computed."
            )
            return

        spring = settings["spring"]
        if spring is None:
            self.simulation_panel.show_error(
                "Reduced-order dynamics needs a joint spring fitted to FEA results."
            )
            return

        import numpy as np

        from ..core.kinematics.spring import ExtrapolationError

        try:
            angles = np.array([a["joint"] for _, a in schedule])
            torques = np.array([spring.torque(float(a)).value for a in angles])
        except ExtrapolationError as exc:
            self.simulation_panel.show_error(
                f"{exc}\n\nThe motion was not run. Shorten the range, or run the "
                "FEA at the angles you need."
            )
            self._set_status("Simulation refused: outside the spring's fitted range.")
            return

        self.simulation_panel.show_torque_history(angles, torques, spring)

        self._set_status(
            f"Reduced-order pass complete: peak |torque| "
            f"{np.max(np.abs(torques)):.6g} N.mm."
        )

    # -- two-point selection ---------------------------------------------------
    #
    # The window owns none of the protocol. It arms the viewport, forwards picks to
    # the controller with the session token, and renders whatever the controller
    # says the state is. See gui/viewer/selection.py.

    def _on_unit_changed(self, unit) -> None:
        """Follow a reinterpretation of the model's length unit.

        Reinterpreting does not rescale the stored coordinates, so a captured pick
        keeps its numbers and changes what they mean. The selection is therefore not
        discarded -- only the symbol the panel quotes is updated, and the output is
        re-rendered so that a distance is never shown against the previous unit.
        """
        self._selection.set_unit(unit.symbol)
        self._refresh_selection_ui()

    def _selected_purpose(self) -> SelectionPurpose:
        return self._purpose_combo.currentData() or SelectionPurpose.MEASUREMENT

    def _coincidence_tolerance(self, purpose: SelectionPurpose) -> float | None:
        """Scale the "same point" threshold to the part, for an axis.

        A fixed 0.5 mm is right for a finger-joint flexure and wrong by two orders
        of magnitude for a whole hand. Two per cent of the bounding-box diagonal,
        with the fixed value as a floor, keeps the baseline long enough that the
        tessellation's chord error is not amplified into a visible angular error.
        A distance measurement gets no such treatment: small distances are
        legitimate measurements, so only floating-point noise is refused.
        """
        if purpose is SelectionPurpose.MEASUREMENT:
            return None
        box = self._model.overall_bounding_box if self._model else None
        if box is None:
            return None
        return max(purpose.default_coincidence_tolerance, 0.02 * box.diagonal)

    def _on_purpose_changed(self, _index: int) -> None:
        """Switching purpose mid-pick restarts the operation rather than reusing it.

        Two points picked loosely enough for a distance are not necessarily a
        usable axis baseline, and silently promoting them would be exactly the
        conflation this panel exists to prevent.
        """
        if self._measure_button.isChecked():
            self._measure_button.setChecked(False)
        self._selection.reset()
        self.viewport.clear_selection_graphics()
        self._measure_output.clear()
        self._refresh_selection_ui()

    def _on_measure_toggled(self, enabled: bool) -> None:
        if enabled:
            purpose = self._selected_purpose()
            if self._model is not None:
                self._selection.set_unit(self._model.unit.symbol)
            token = self._selection.begin(
                purpose,
                coincidence_tolerance=self._coincidence_tolerance(purpose),
            )
            self._measure_output.clear()
            self.viewport.clear_selection_graphics()
            self.viewport.start_point_picking(
                self._on_point_picked,
                on_miss=self._on_pick_missed,
                instruction=self._selection.message,
            )
            self._selection_token = token
        else:
            self.viewport.stop_point_picking()
            if self._selection.is_picking:
                self._selection.cancel()
        self._refresh_selection_ui()

    def _on_point_picked(self, point: tuple[float, float, float]) -> None:
        outcome = self._selection.add_point(point, token=self._selection_token)

        if outcome is PickOutcome.FIRST_CAPTURED:
            self.viewport.mark_point(0, point)
        elif outcome is PickOutcome.SECOND_CAPTURED:
            self.viewport.mark_point(1, point)
            self._draw_selection_preview()

        self._refresh_selection_ui()

    def _on_pick_missed(self) -> None:
        self._selection.register_miss()
        self._refresh_selection_ui()

    def _draw_selection_preview(self) -> None:
        result = self._selection.result
        if result is None:
            return
        if result.purpose is SelectionPurpose.JOINT_AXIS:
            self.viewport.draw_axis_preview(result.origin, result.direction)
        else:
            self.viewport.draw_measurement_line(result.first, result.second)

    def _confirm_selection(self) -> None:
        if self._selection.state is not SelectionState.PREVIEW:
            return
        result = self._selection.confirm()

        if result.purpose is SelectionPurpose.JOINT_AXIS:
            self.flexure_panel.set_joint_axis(result.origin, result.direction)
            self.fea_panel.set_axis_point(result.origin)
            # The window owns the committed axis, not the controller. The controller
            # owns the protocol, and beginning a new selection -- to measure
            # something, say -- clears its confirmed result. The engineering input
            # written into the panels has to outlive that.
            self._joint_axis = result
            self._mark_stale(
                "the joint axis was changed after the result was computed, and the "
                "reported stiffness depends on it"
            )
            self._set_status(
                "Joint axis confirmed and written into the Flexure and FEA panels. "
                "It is the midpoint of two surface picks, not a measurement of where "
                "the joint rotates -- check it before you run anything."
            )
        else:
            self._set_status(
                f"Measurement recorded: {result.distance:.4f} {result.unit}."
            )

        # The operation is finished, so the mouse goes back to the camera. The
        # markers and the axis line stay: they are the record of what was agreed.
        self._measure_button.setChecked(False)
        self.viewport.stop_point_picking()
        self._refresh_selection_ui()
        self._refresh_workflow()

    def _clear_measurement(self) -> None:
        """Drop the points and stay armed, if the tool is armed."""
        self._selection.clear()
        self.viewport.clear_selection_graphics()
        self._measure_output.clear()
        self._refresh_selection_ui()

    def _cancel_selection(self) -> None:
        self._measure_button.setChecked(False)  # triggers the toggle handler
        self._selection.cancel()
        self.viewport.stop_point_picking()
        self.viewport.clear_selection_graphics()
        self._measure_output.clear()
        self._refresh_selection_ui()

    def _invalidate_selection(self, reason: str) -> None:
        """Throw the selection away because the geometry it referred to changed.

        The original defect: coordinates picked on one solid survived an import and
        paired with a point on the next one, producing a distance between two
        different parts with nothing on screen to betray it.
        """
        discarded = self._selection.invalidate(reason)
        # A confirmed axis is a set of coordinates on a particular solid, so it does
        # not survive that solid being replaced either. The numbers left in the
        # analysis panels are not cleared -- they are the user's to check, and
        # silently zeroing an input they typed would be worse -- but the workflow
        # stops reporting a confirmed axis.
        self._joint_axis = None
        if self._measure_button.isChecked():
            self._measure_button.setChecked(False)
        self.viewport.stop_point_picking()
        self.viewport.clear_selection_graphics()
        if discarded:
            self._measure_output.setPlainText(self._selection.message)
        else:
            self._measure_output.clear()
        self._refresh_selection_ui()
        self._refresh_workflow()

    def _refresh_selection_ui(self) -> None:
        """Render the controller's state. The only writer of these widgets."""
        state = self._selection.state
        self._measure_instruction.setText(self._selection.message)
        # The same words in the viewport, where the eyes are while picking.
        if self.viewport.is_picking:
            self.viewport.set_picking_instruction(self._selection.message)
        self._measure_instruction.setStyleSheet(
            "color: #E8A33D;" if state is SelectionState.AWAITING_SECOND
            else "color: #7FB069;" if state is SelectionState.COMPLETED
            else ""
        )

        can_confirm = state is SelectionState.PREVIEW
        self._confirm_selection_button.setEnabled(can_confirm)
        self._confirm_selection_button.setToolTip(
            "Accept these two points."
            if can_confirm
            else "Pick two distinct points first."
        )

        result = self._selection.result
        if result is None:
            if state in (SelectionState.AWAITING_FIRST, SelectionState.AWAITING_SECOND):
                self._measure_output.setPlainText(
                    "\n".join(
                        f"Point {i + 1}: ({p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f}) "
                        f"{self._selection.unit}"
                        for i, p in enumerate(self._selection.points)
                    )
                )
            return

        unit = result.unit
        dx, dy, dz = result.delta
        lines = [
            f"Point 1: ({result.first[0]:.4f}, {result.first[1]:.4f}, "
            f"{result.first[2]:.4f}) {unit}",
            f"Point 2: ({result.second[0]:.4f}, {result.second[1]:.4f}, "
            f"{result.second[2]:.4f}) {unit}",
            "",
            f"Distance:  {result.distance:.4f} {unit}",
            "",
            f"dX = {dx:.4f} {unit}",
            f"dY = {dy:.4f} {unit}",
            f"dZ = {dz:.4f} {unit}",
        ]
        if result.purpose is SelectionPurpose.JOINT_AXIS:
            ox, oy, oz = result.origin
            ux, uy, uz = result.direction
            lines += [
                "",
                f"Axis origin:     ({ox:.4f}, {oy:.4f}, {oz:.4f}) {unit}",
                f"Axis direction:  ({ux:.5f}, {uy:.5f}, {uz:.5f})",
                "",
                "CONFIRMED - written into the Flexure and FEA panels."
                if state is SelectionState.COMPLETED
                else "NOT CONFIRMED - nothing uses this axis yet.",
            ]
        lines += [
            "",
            "Picked on the display tessellation, not on exact geometry.",
        ]
        self._measure_output.setPlainText("\n".join(lines))

    # -- projects --------------------------------------------------------------

    def _new_project(self) -> None:
        path_text, _ = QFileDialog.getSaveFileName(
            self, "Create project", "", f"Barnes UI project (*{PROJECT_SUFFIX})"
        )
        if not path_text:
            return
        try:
            self._project = ProjectStore.create(
                Path(path_text), application_version=__version__
            )
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "Could not create project", str(exc))
            return
        self._set_status(f"Created project {self._project.name}")
        self._update_title()

    def _open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open project directory")
        if not directory:
            return
        try:
            self._project = ProjectStore.open(Path(directory))
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "Could not open project", str(exc))
            return
        count = len(self._project.data.geometry)
        self._set_status(f"Opened project {self._project.name} ({count} geometry entries)")
        self._update_title()

    def _add_to_project(self) -> None:
        if self._project is None:
            QMessageBox.information(
                self, "No project open",
                "Create or open a project first (File > New project).",
            )
            return
        if self._model is None:
            QMessageBox.information(
                self, "No model loaded", "Import a CAD file first."
            )
            return
        try:
            entry = self._project.add_geometry(self._model)
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "Could not add geometry", str(exc))
            return
        self._unsaved_detail = None
        self._refresh_workflow()
        self._set_status(
            f"Added {self._model.source_path.name} to project as {entry.entry_id}"
        )

    def _update_title(self) -> None:
        base = f"Barnes UI {__version__}"
        if self._project is not None:
            base = f"{self._project.name} - {base}"
        self.setWindowTitle(base)
        self._refresh_workflow()

    # -- help ------------------------------------------------------------------

    def _show_formats(self) -> None:
        QMessageBox.information(
            self,
            "Supported formats",
            "Readable now:\n"
            "   STEP (.step, .stp)   exact geometry, declares units  - recommended\n"
            "   IGES (.iges, .igs)   exact but lossy; surfaces, not solids\n"
            "   BREP (.brep)         OpenCASCADE native\n"
            "   STL  (.stl)          tessellated; viewing only, not analysis\n"
            "   DXF  (.dxf)          2D curves only\n\n"
            "Native SolidWorks files (.SLDPRT, .SLDASM) cannot be read without "
            "SolidWorks. Export as STEP AP214 instead; for assemblies, tick "
            "'Save all components as a single file' so component placement is kept.\n\n"
            "Nothing needed for analysis is lost in a STEP export.",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Barnes UI",
            f"<b>Barnes UI {__version__}</b><br><br>"
            "TPU flexure design, stiffness analysis and prosthetic-hand simulation."
            "<br><br>"
            "<b>Nothing in this application is experimentally validated.</b> No "
            "printed specimen has been tested, so every absolute force and stress "
            "is a prediction from an uncalibrated material. Design <i>ranking</i> "
            "does not depend on that calibration; absolute sizing does.<br><br>"
            "Named design variants are not implemented: a parameter sweep compares "
            "candidates within one run and leaves none behind to reopen.<br><br>"
            f"Log file:<br><code>{log_file_path()}</code><br><br>"
            "See the <code>docs/</code> directory for the feasibility assessment, "
            "solver comparison, architecture and development plan.",
        )

    # -- shutdown --------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Close the VTK render window before Qt tears the widget tree down.

        Skipping this reliably hangs or crashes on Windows, because VTK's render
        window outlives the Qt widget that owned it.
        """
        try:
            self.viewport.close_viewport()
        except Exception:  # pragma: no cover
            logger.debug("Viewport shutdown raised; continuing.")
        super().closeEvent(event)
