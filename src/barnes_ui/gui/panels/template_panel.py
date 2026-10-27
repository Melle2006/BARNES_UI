"""Parametric meander template: build, adapt, and see exactly what changed.

Phase 4's user-facing half. Two things on this panel earn their space.

The **derived geometry** block updates as the parameters change and shows values the
template knows exactly -- centreline length, envelope, inner turn radius, volume. They
are geometric measurements of a shape that does not exist yet, which is an unusual
category and is tagged as such: the template's volume identity is exact, so the number
is not a prediction.

The **adaptation report** is the whole point of the Phase 4 workflow. Asking for a new
span changes some parameters and leaves others alone, and a change nobody asked for is
the one worth seeing. Unrequested changes are listed separately and in red.

A design that fails a blocking safety check is shown with the reason and the build
button is disabled. Phase 4 criterion 5 says such a design is flagged and not
auto-approved; here that means the user has to change something, not tick a box.
"""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.flexure.adaptation import (
    AdaptationError,
    AdaptationReport,
    adapt_to_span,
    manufacturability_issues,
    required_peak_strain,
)
from ...core.flexure.templates.meander import MeanderError, MeanderParameters
from ...core.provenance import Provenance
from ._common import float_spin, int_spin, note_label, provenance_badge

logger = logging.getLogger(__name__)

__all__ = ["TemplatePanel"]


class TemplatePanel(QWidget):
    """Edit meander parameters, adapt to a span, and build the solid."""

    #: Emitted with the parameters to build and display.
    build_requested = Signal(object)
    #: Emitted with (parameters, path) to export a STEP file.
    export_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report: AdaptationReport | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        layout.addWidget(self._build_parameters_box())
        layout.addWidget(self._build_derived_box())
        layout.addWidget(self._build_adaptation_box())
        layout.addWidget(self._build_safety_box(), stretch=1)
        layout.addWidget(self._build_actions_box())

        self._refresh()

    # -- construction ----------------------------------------------------------

    def _build_parameters_box(self) -> QWidget:
        box = QGroupBox("Meander parameters")
        form = QFormLayout(box)

        self._run_length = float_spin(0.5, 500.0, 3, 12.0, 0.5, " mm")
        self._n_runs = int_spin(2, 60, 4)
        self._pitch = float_spin(0.05, 50.0, 3, 3.0, 0.1, " mm")
        self._width = float_spin(0.05, 20.0, 3, 1.0, 0.05, " mm")
        self._thickness = float_spin(0.05, 20.0, 3, 1.2, 0.05, " mm")

        form.addRow("Run length:", self._run_length)
        form.addRow("Runs:", self._n_runs)
        form.addRow("Pitch:", self._pitch)
        form.addRow("Width (bending):", self._width)
        form.addRow("Thickness (out of plane):", self._thickness)

        for widget in (self._run_length, self._n_runs, self._pitch,
                       self._width, self._thickness):
            widget.valueChanged.connect(self._refresh)

        form.addRow(note_label(
            "Width is the in-plane dimension bending acts on, so stiffness goes as "
            "its cube: a 10 per cent change in width is a 33 per cent change in "
            "stiffness."
        ))
        return box

    def _build_derived_box(self) -> QWidget:
        box = QGroupBox("Derived geometry")
        layout = QVBoxLayout(box)
        self._derived = QLabel()
        self._derived.setWordWrap(True)
        self._derived.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self._derived)
        layout.addWidget(provenance_badge(Provenance.GEOMETRIC_MEASUREMENT))
        layout.addWidget(note_label(
            "Exact for this template: the volume identity width x thickness x "
            "centreline length holds analytically, so these are measurements of the "
            "shape the parameters define rather than predictions about it."
        ))
        return box

    def _build_adaptation_box(self) -> QWidget:
        box = QGroupBox("Adapt to a joint")
        form = QFormLayout(box)

        self._target_span = float_spin(1.0, 500.0, 3, 16.0, 0.5, " mm")
        self._strategy = QComboBox()
        self._strategy.addItem("Change the pitch, keep the run count", "pitch")
        self._strategy.addItem("Change the run count, keep the pitch", "runs")
        self._joint_angle = float_spin(1.0, 180.0, 1, 100.0, 5.0, " deg")

        form.addRow("Attachment span:", self._target_span)
        form.addRow("Strategy:", self._strategy)
        form.addRow("Range of motion:", self._joint_angle)

        self._adapt_button = QPushButton("Adapt")
        self._adapt_button.clicked.connect(self._adapt)
        form.addRow(self._adapt_button)

        self._adaptation_output = QTextEdit()
        self._adaptation_output.setReadOnly(True)
        self._adaptation_output.setPlaceholderText(
            "The parameter-change report appears here. Changes nobody asked for are "
            "listed separately -- they are the ones worth reading."
        )
        self._adaptation_output.setMinimumHeight(110)
        form.addRow(self._adaptation_output)

        form.addRow(note_label(
            "Adaptation regenerates from parameters; it never scales the solid. "
            "Thickness and width are preserved exactly unless you change them above."
        ))
        return box

    def _build_safety_box(self) -> QWidget:
        box = QGroupBox("Safety checks")
        layout = QVBoxLayout(box)
        self._min_feature = float_spin(0.05, 5.0, 2, 0.4, 0.05, " mm")
        self._min_feature.valueChanged.connect(self._refresh)
        form = QFormLayout()
        form.addRow("Minimum printable feature:", self._min_feature)
        layout.addLayout(form)

        self._safety_output = QTextEdit()
        self._safety_output.setReadOnly(True)
        self._safety_output.setMinimumHeight(90)
        layout.addWidget(self._safety_output)
        return box

    def _build_actions_box(self) -> QWidget:
        box = QGroupBox("Build")
        layout = QVBoxLayout(box)
        self._build_button = QPushButton("Build and display")
        self._build_button.clicked.connect(self._emit_build)
        layout.addWidget(self._build_button)

        self._export_button = QPushButton("Export STEP...")
        self._export_button.clicked.connect(self._emit_export)
        layout.addWidget(self._export_button)
        return box

    # -- state -----------------------------------------------------------------

    def parameters(self) -> MeanderParameters | None:
        """Current parameters, or None when they do not describe a buildable part."""
        try:
            return MeanderParameters(
                run_length=self._run_length.value(),
                n_runs=self._n_runs.value(),
                pitch=self._pitch.value(),
                width=self._width.value(),
                thickness=self._thickness.value(),
            )
        except MeanderError:
            return None

    def set_parameters(self, parameters: MeanderParameters) -> None:
        for widget, value in (
            (self._run_length, parameters.run_length),
            (self._n_runs, parameters.n_runs),
            (self._pitch, parameters.pitch),
            (self._width, parameters.width),
            (self._thickness, parameters.thickness),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._refresh()

    # -- behaviour -------------------------------------------------------------

    def _refresh(self) -> None:
        parameters = self.parameters()
        if parameters is None:
            self._derived.setText(
                "These parameters do not describe a buildable meander. The usual "
                "cause is a pitch at or below the width, which merges adjacent runs "
                "into a solid block."
            )
            self._safety_output.setPlainText("")
            self._build_button.setEnabled(False)
            self._export_button.setEnabled(False)
            return

        x, y, z = parameters.envelope
        self._derived.setText(
            f"centreline   {parameters.centreline_length:10.4f} mm\n"
            f"envelope     {x:7.3f} x {y:7.3f} x {z:7.3f} mm\n"
            f"volume       {parameters.expected_volume:10.4f} mm^3\n"
            f"turn radius  {parameters.turn_radius:10.4f} mm "
            f"(inner {parameters.inner_radius:.4f} mm)\n"
            f"turns        {parameters.n_turns}"
        )

        issues = manufacturability_issues(parameters, self._min_feature.value())
        strain = required_peak_strain(
            parameters, math.radians(self._joint_angle.value())
        )
        lines = [
            f"Estimated peak strain at {self._joint_angle.value():.0f} deg: "
            f"{strain.value * 100:.1f} % [{strain.provenance.label}]",
            "  " + strain.caveats[0].message if strain.caveats else "",
            "",
        ]
        lines.extend(str(issue) for issue in issues)
        if not issues:
            lines.append("No manufacturability issues at this minimum feature size.")
        self._safety_output.setPlainText("\n".join(line for line in lines if line != ""))

        blocking = [i for i in issues if i.blocking]
        self._build_button.setEnabled(not blocking)
        self._export_button.setEnabled(not blocking)
        if blocking:
            self._build_button.setToolTip(
                "This design has a feature below the minimum printable size. It is "
                "flagged and not auto-approved: change a parameter, or change the "
                "minimum feature size if your printer really can do it."
            )
        else:
            self._build_button.setToolTip("")

    def _adapt(self) -> None:
        parameters = self.parameters()
        if parameters is None:
            self._adaptation_output.setPlainText(
                "Fix the parameters before adapting them."
            )
            return
        try:
            report = adapt_to_span(
                parameters,
                target_span=self._target_span.value(),
                strategy=self._strategy.currentData(),
                minimum_feature_size=self._min_feature.value(),
                joint_angle=math.radians(self._joint_angle.value()),
                # The strain screen is advisory on this panel: it is a
                # uniform-curvature estimate and blocking a design on it would give
                # a crude formula a veto it has not earned. Manufacturability still
                # blocks.
                strain_limit=10.0,
            )
        except AdaptationError as exc:
            self._adaptation_output.setPlainText(f"Cannot adapt: {exc}")
            return

        self._report = report
        lines = [report.summary()]
        if report.unintended_changes:
            lines.append("")
            lines.append("CHANGES YOU DID NOT ASK FOR:")
            lines.extend(f"  {c}" for c in report.unintended_changes)
        self._adaptation_output.setPlainText("\n".join(lines))
        self.set_parameters(report.adapted)

    def _emit_build(self) -> None:
        parameters = self.parameters()
        if parameters is not None:
            self.build_requested.emit(parameters)

    def _emit_export(self) -> None:
        parameters = self.parameters()
        if parameters is not None:
            self.export_requested.emit(parameters)
