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
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
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
from .panels.fea_panel import FeaPanel
from .panels.flexure_panel import FlexurePanel
from .panels.geometry_panel import GeometryPanel
from .panels.optimise_panel import OptimisePanel
from .panels.plots_panel import PlotsPanel
from .panels.simulation_panel import SimulationPanel
from .panels.template_panel import TemplatePanel
from .tasks import run_in_background
from .viewer.viewport import Viewport

logger = logging.getLogger(__name__)

__all__ = ["MainWindow"]


def _flexure_worker(shape, settings: dict) -> tuple:
    """Run the Phase 2 pipeline off the UI thread.

    A module-level function rather than a method so that nothing about the window is
    reachable from the worker thread. Everything it needs arrives as arguments, and it
    returns plain results for the UI thread to display.
    """
    members = extract_members(
        shape,
        sweep_axis=settings["sweep_axis"],
        bending_axis=settings["joint_direction"],
        start=settings["range_start"],
        end=settings["range_end"],
        samples=settings["samples"],
    )
    material = provisional_tpu(settings["youngs_modulus"])
    joint = JointAxis(
        origin=settings["joint_origin"], direction=settings["joint_direction"]
    )
    curve, stiffness = analyse_joint_flexure(
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
        self.setWindowTitle(f"Barnes UI {__version__} - Phase 1: CAD inspection")
        self.resize(1500, 950)

        self._model: GeometryModel | None = None
        self._project: ProjectStore | None = None
        # References to running background work. Dropping these lets Qt collect the
        # thread mid-run, which crashes the process -- see gui/tasks.py.
        self._jobs: list[tuple[object, object]] = []
        self._measure_points: list[tuple[float, float, float]] = []

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)

        self._build_geometry_dock()
        self._build_measurement_dock()
        self._build_plots_dock()
        self._build_menus()
        self._build_status_bar()

        self._set_status("Ready. Open a CAD file to begin.")

    # -- construction ----------------------------------------------------------

    def _build_geometry_dock(self) -> None:
        """Left dock: a tab per workflow stage.

        Tabbed rather than stacked vertically because later phases add assembly
        integration and hand simulation, and five panels in one column would be
        unusable. Each panel is wrapped in a scroll area so a small window never
        hides the run button.
        """
        self.geometry_panel = GeometryPanel(self)
        self.geometry_panel.solid_visibility_changed.connect(
            self.viewport.set_solid_visible
        )

        self.flexure_panel = FlexurePanel(self)
        self.flexure_panel.analysis_requested.connect(self._run_flexure_analysis)
        self.flexure_panel.axis_suggestion_requested.connect(self._suggest_joint_axis)

        self.template_panel = TemplatePanel(self)
        self.template_panel.build_requested.connect(self._build_template)
        self.template_panel.export_requested.connect(self._export_template)

        self.fea_panel = FeaPanel(self)
        self.fea_panel.analysis_requested.connect(self._run_fea)
        self.fea_panel.cancel_requested.connect(self._cancel_fea)

        self.simulation_panel = SimulationPanel(self)
        self.simulation_panel.run_requested.connect(self._run_simulation)

        self.optimise_panel = OptimisePanel(self)

        tabs = QTabWidget()
        tabs.addTab(self._scrolled(self.geometry_panel), "Geometry")
        tabs.addTab(self._scrolled(self.flexure_panel), "Flexure")
        tabs.addTab(self._scrolled(self.template_panel), "Template")
        tabs.addTab(self._scrolled(self.fea_panel), "FEA")
        tabs.addTab(self._scrolled(self.simulation_panel), "Simulate")
        tabs.addTab(self._scrolled(self.optimise_panel), "Optimise")
        self._tabs = tabs

        dock = QDockWidget("Workflow", self)
        dock.setWidget(tabs)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        dock.setMinimumWidth(440)
        self._geometry_dock = dock

    @staticmethod
    def _scrolled(widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        return area

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
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._measure_button = QPushButton("Pick two points")
        self._measure_button.setCheckable(True)
        self._measure_button.toggled.connect(self._on_measure_toggled)
        layout.addWidget(self._measure_button)

        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_measurement)
        layout.addWidget(clear)

        self._measure_output = QTextEdit()
        self._measure_output.setReadOnly(True)
        self._measure_output.setPlaceholderText(
            "Enable picking, then click two points on the model."
        )
        layout.addWidget(self._measure_output)

        note = QLabel(
            "Points are picked on the display tessellation, so a measurement carries "
            "the mesh's chord tolerance. Snapping to exact vertices and edges is "
            "Phase 2 work and is not implemented yet."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9AA3AD;")
        layout.addWidget(note)

        dock = QDockWidget("Measure", self)
        dock.setWidget(widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setMinimumWidth(300)

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
        self._model = model
        self.geometry_panel.show_model(model)
        self.viewport.show_model(model)
        self.flexure_panel.set_enabled_for_model(model)
        self.flexure_panel.clear_results()
        self.plots_panel.clear()
        self._plots_dock.hide()

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
        self._model = model
        self.geometry_panel.show_model(model)
        self.viewport.show_model(model)
        self.flexure_panel.set_enabled_for_model(model)
        self.flexure_panel.clear_results()
        self.optimise_panel.set_base_design(parameters)

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

        setup = JointStiffnessSetup(
            attachment_depth=settings["collar_depth"],
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
        self.fea_panel.show_result(
            outcome.result, outcome.stiffness, outcome.setup.rotation_deg
        )
        if outcome.succeeded:
            self._set_status(
                f"FEA complete: {outcome.stiffness:.6g} N.mm/rad. "
                f"{outcome.result.convergence.summary}"
            )
        else:
            self._set_status(f"FEA produced no usable result. {outcome.failure}")

    def _on_fea_failed(self, message: str, detail: str) -> None:
        self._finish_job()
        self.fea_panel.set_running(False)
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
        self._set_status("FEA cancelled.")

    def _cancel_fea(self) -> None:
        job = getattr(self, "_fea_job", None)
        if job is not None:
            job[1].token.cancel()
            self._set_status("Cancelling after the current increment...")

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

    # -- measurement -----------------------------------------------------------

    def _on_measure_toggled(self, enabled: bool) -> None:
        if enabled:
            self._measure_points.clear()
            self.viewport.start_point_picking(self._on_point_picked)
            self._set_status("Click two points on the model.")
        else:
            self.viewport.stop_point_picking()
            self._set_status("Picking stopped.")

    def _on_point_picked(self, point: tuple[float, float, float]) -> None:
        self._measure_points.append(point)
        unit = self._model.unit.symbol if self._model else "mm"

        if len(self._measure_points) == 1:
            self._measure_output.setPlainText(
                f"Point 1: ({point[0]:.4f}, {point[1]:.4f}, {point[2]:.4f}) {unit}\n"
                "Click a second point."
            )
            return

        start, end = self._measure_points[-2], self._measure_points[-1]
        dx, dy, dz = (end[i] - start[i] for i in range(3))
        distance = (dx * dx + dy * dy + dz * dz) ** 0.5

        self.viewport.draw_measurement_line(start, end)
        self._measure_output.setPlainText(
            f"Point 1: ({start[0]:.4f}, {start[1]:.4f}, {start[2]:.4f}) {unit}\n"
            f"Point 2: ({end[0]:.4f}, {end[1]:.4f}, {end[2]:.4f}) {unit}\n\n"
            f"Distance:  {distance:.4f} {unit}\n\n"
            f"dX = {dx:.4f} {unit}\n"
            f"dY = {dy:.4f} {unit}\n"
            f"dZ = {dz:.4f} {unit}\n\n"
            "Measured on the display tessellation, not on exact geometry."
        )
        self._measure_points.clear()

    def _clear_measurement(self) -> None:
        self._measure_points.clear()
        self.viewport.clear_measurement()
        self._measure_output.clear()

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
        self._set_status(
            f"Added {self._model.source_path.name} to project as {entry.entry_id}"
        )

    def _update_title(self) -> None:
        base = f"Barnes UI {__version__} - Phase 1: CAD inspection"
        if self._project is not None:
            base = f"{self._project.name} - {base}"
        self.setWindowTitle(base)

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
            "TPU flexure design, stiffness analysis and prosthetic-hand simulation.<br><br>"
            "<b>Phase 1 - CAD import and inspection.</b><br>"
            "Flexure mechanics (Phase 2) and nonlinear FEA (Phase 3) are not "
            "implemented yet. No stiffness, force or torque is computed by this "
            "build, and none is displayed.<br><br>"
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
