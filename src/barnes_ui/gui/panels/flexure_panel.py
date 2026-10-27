"""Flexure analysis panel: joint axis, material, reduced-order stiffness.

Presents Phase 2. The design rule carried over from the geometry panel is that nothing
is shown without its unit and its provenance, and the assumptions behind a number sit
beside the number rather than in a collapsed section or a manual.

The provenance badge is prominent and colour-coded because a reduced-order prediction
and an FEA result will appear in the same places in later phases, and the difference
between them matters more than anything else on the panel.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.cad.model import GeometryModel
from ...core.mechanics.curved_beam import FlexureStiffness, TorqueAngleCurve
from ...core.provenance import Provenance
from ...core.units import format_quantity

logger = logging.getLogger(__name__)

__all__ = ["FlexurePanel"]

_PROVENANCE_COLOURS = {
    Provenance.UNVALIDATED_ASSUMPTION: "#D9534F",
    Provenance.REDUCED_ORDER_PREDICTION: "#E8A33D",
    Provenance.ANALYTICAL_ESTIMATE: "#E8A33D",
    Provenance.FEA_RESULT: "#4C8FBD",
    Provenance.GEOMETRIC_MEASUREMENT: "#7FB069",
    Provenance.EXPERIMENTALLY_VALIDATED: "#7FB069",
}


class FlexurePanel(QWidget):
    """Set up and run a reduced-order flexure analysis."""

    analysis_requested = Signal(dict)
    axis_suggestion_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: GeometryModel | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        layout.addWidget(self._build_joint_box())
        layout.addWidget(self._build_extraction_box())
        layout.addWidget(self._build_material_box())
        layout.addWidget(self._build_run_box())
        layout.addWidget(self._build_results_box(), stretch=2)
        layout.addWidget(self._build_assumptions_box(), stretch=1)

        self.set_enabled_for_model(None)

    # -- construction ----------------------------------------------------------

    def _build_joint_box(self) -> QWidget:
        box = QGroupBox("Joint axis")
        outer = QVBoxLayout(box)

        note = QLabel(
            "STEP files do not carry SolidWorks mates, so the joint axis cannot be "
            "read from the model and must be set here. The suggestion is derived from "
            "the attachment collars and needs checking in the viewport."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9AA3AD;")
        outer.addWidget(note)

        form = QFormLayout()
        self._origin = [self._spin(-1000.0, 1000.0, 3) for _ in range(3)]
        self._direction = [self._spin(-1.0, 1.0, 4) for _ in range(3)]
        self._direction[0].setValue(1.0)

        row_o = QHBoxLayout()
        for spin in self._origin:
            row_o.addWidget(spin)
        form.addRow("Origin (mm):", self._wrap(row_o))

        row_d = QHBoxLayout()
        for spin in self._direction:
            row_d.addWidget(spin)
        form.addRow("Direction:", self._wrap(row_d))
        outer.addLayout(form)

        self._suggest_button = QPushButton("Suggest from attachment geometry")
        self._suggest_button.clicked.connect(self.axis_suggestion_requested.emit)
        outer.addWidget(self._suggest_button)
        return box

    def _build_extraction_box(self) -> QWidget:
        box = QGroupBox("Centreline extraction")
        form = QFormLayout(box)

        self._sweep = [self._spin(-1.0, 1.0, 4) for _ in range(3)]
        self._sweep[1].setValue(1.0)
        row = QHBoxLayout()
        for spin in self._sweep:
            row.addWidget(spin)
        form.addRow("Sweep axis:", self._wrap(row))

        self._range_start = self._spin(-1000.0, 1000.0, 3)
        self._range_end = self._spin(-1000.0, 1000.0, 3)
        form.addRow("Range start (mm):", self._range_start)
        form.addRow("Range end (mm):", self._range_end)

        self._samples = QSpinBox()
        self._samples.setRange(4, 1000)
        self._samples.setValue(120)
        self._samples.setToolTip(
            "Stations along the centreline. The arc length and stiffness both converge "
            "upward with this; 120 was within 0.04 per cent of the 240-station result "
            "on the A3 twin-strap part."
        )
        form.addRow("Samples:", self._samples)

        hint = QLabel(
            "Set the range to span only the beam-like part, excluding the collars. "
            "Attachment features are not beam-like and must not enter the beam model."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9AA3AD;")
        form.addRow(hint)
        return box

    def _build_material_box(self) -> QWidget:
        box = QGroupBox("Material")
        form = QFormLayout(box)

        self._modulus = self._spin(0.001, 100000.0, 4)
        self._modulus.setValue(12.0)
        self._modulus.setSuffix(" MPa")
        form.addRow("Initial Young's modulus:", self._modulus)

        warning = QLabel(
            "PROVISIONAL. This is not a characterisation of TPU 95A and is not derived "
            "from the hardness grade - no defensible derivation exists. Every force "
            "and torque computed from it is unvalidated and is marked as such. Replace "
            "it by fitting a tensile test on a specimen printed with the same filament, "
            "printer, orientation and settings as the real part."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #D9534F;")
        form.addRow(warning)
        return box

    def _build_run_box(self) -> QWidget:
        box = QGroupBox("Motion range and solver")
        form = QFormLayout(box)

        self._max_angle = self._spin(1.0, 180.0, 1)
        self._max_angle.setValue(90.0)
        self._max_angle.setSuffix(" deg")
        form.addRow("Maximum joint angle:", self._max_angle)

        self._steps = QSpinBox()
        self._steps.setRange(2, 500)
        self._steps.setValue(46)
        form.addRow("Curve points:", self._steps)

        self._include_axial = QCheckBox("Include axial flexibility")
        self._include_axial.setChecked(True)
        self._include_axial.setToolTip(
            "A shallow arch resists end displacement largely by stretching. Omitting "
            "this overstated stiffness by 13 per cent on the A3 twin-strap part. A "
            "straight member cannot be solved without it."
        )
        self._include_shear = QCheckBox("Include shear flexibility")
        self._include_shear.setChecked(True)
        self._include_shear.setToolTip(
            "Timoshenko shear term. Worth about 1.7 per cent on the A3 twin strap; "
            "more for stubbier members."
        )
        form.addRow(self._include_axial)
        form.addRow(self._include_shear)

        self._run_button = QPushButton("Run reduced-order analysis")
        self._run_button.clicked.connect(self._emit_request)
        form.addRow(self._run_button)
        return box

    def _build_results_box(self) -> QWidget:
        box = QGroupBox("Results")
        layout = QVBoxLayout(box)

        self._provenance_badge = QLabel("No analysis run")
        self._provenance_badge.setWordWrap(True)
        self._provenance_badge.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._provenance_badge)

        self._results = QTreeWidget()
        self._results.setColumnCount(2)
        self._results.setHeaderLabels(["Quantity", "Value"])
        self._results.setRootIsDecorated(False)
        self._results.setAlternatingRowColors(True)
        layout.addWidget(self._results)
        return box

    def _build_assumptions_box(self) -> QWidget:
        box = QGroupBox("Assumptions and limitations")
        layout = QVBoxLayout(box)
        self._assumptions = QTextEdit()
        self._assumptions.setReadOnly(True)
        self._assumptions.setPlaceholderText(
            "Every assumption in force for the displayed result is listed here."
        )
        layout.addWidget(self._assumptions)
        return box

    @staticmethod
    def _spin(minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(10.0 ** -min(decimals, 2))
        return spin

    @staticmethod
    def _wrap(layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    # -- state -----------------------------------------------------------------

    def set_enabled_for_model(self, model: GeometryModel | None) -> None:
        """Enable analysis only for geometry that may legitimately be analysed."""
        self._model = model
        ready = model is not None and model.is_analysis_ready
        self._run_button.setEnabled(ready)
        self._suggest_button.setEnabled(model is not None)

        if model is None:
            self._run_button.setToolTip("Import a model first.")
            return
        if not ready:
            reasons = "\n".join(f"- {r}" for r in model.analysis_readiness_reasons())
            self._run_button.setToolTip(
                f"This model is not ready for analysis:\n{reasons}"
            )
            return

        self._run_button.setToolTip("")
        box = model.overall_bounding_box
        if box is not None:
            # Default the sweep range to the middle 80 per cent of the Y extent, which
            # for a joint-spanning flexure usually excludes the attachment collars.
            span = box.ymax - box.ymin
            self._range_start.setValue(box.ymin + 0.1 * span)
            self._range_end.setValue(box.ymax - 0.1 * span)

    def set_joint_axis(self, origin, direction) -> None:
        for spin, value in zip(self._origin, origin):
            spin.setValue(float(value))
        for spin, value in zip(self._direction, direction):
            spin.setValue(float(value))

    def settings(self) -> dict:
        return {
            "joint_origin": tuple(s.value() for s in self._origin),
            "joint_direction": tuple(s.value() for s in self._direction),
            "sweep_axis": tuple(s.value() for s in self._sweep),
            "range_start": self._range_start.value(),
            "range_end": self._range_end.value(),
            "samples": self._samples.value(),
            "youngs_modulus": self._modulus.value(),
            "max_angle_deg": self._max_angle.value(),
            "steps": self._steps.value(),
            "include_axial": self._include_axial.isChecked(),
            "include_shear": self._include_shear.isChecked(),
        }

    def _emit_request(self) -> None:
        self.analysis_requested.emit(self.settings())

    # -- results ---------------------------------------------------------------

    def show_results(
        self,
        curve: TorqueAngleCurve,
        stiffness: FlexureStiffness,
        members,
        max_angle_deg: float,
    ) -> None:
        colour = _PROVENANCE_COLOURS.get(curve.provenance, "#9AA3AD")
        self._provenance_badge.setText(
            f"{curve.provenance.label} - {curve.provenance.description}"
        )
        self._provenance_badge.setStyleSheet(f"font-weight: bold; color: {colour};")

        self._results.clear()
        rows: list[tuple[str, str]] = [
            ("Members analysed", str(len(members))),
            (
                "Rotational stiffness (neutral)",
                format_quantity(stiffness.rotational_stiffness, "N.mm/rad"),
            ),
            (
                "Rotational stiffness (neutral)",
                format_quantity(stiffness.rotational_stiffness / 1000.0, "N.m/rad"),
            ),
            (
                f"Restoring torque at {max_angle_deg:.1f} deg",
                format_quantity(float(curve.torques[-1]), "N.mm"),
            ),
            (
                f"Peak bending strain at {max_angle_deg:.1f} deg",
                f"{float(curve.peak_strains[-1]) * 100.0:.3f} %",
            ),
        ]

        for member in members:
            width, depth = member.equivalent_section()
            rows.extend([
                (f"Member {member.index} arc length",
                 format_quantity(member.arc_length, "mm")),
                (f"Member {member.index} chord length",
                 format_quantity(member.chord_length, "mm")),
                (f"Member {member.index} arc/chord",
                 f"{member.curvature_ratio:.5f}"),
                (f"Member {member.index} section",
                 f"{width:.4f} x {depth:.4f} mm (equivalent rectangle)"),
                (f"Member {member.index} mean area",
                 format_quantity(member.mean_area, "mm^2")),
                (f"Member {member.index} mean I",
                 format_quantity(float(member.inertia_profile().mean()), "mm^4")),
                (f"Member {member.index} stiffness",
                 format_quantity(stiffness.member_stiffness[member.index], "N.mm/rad")),
            ])

        for name, value in rows:
            self._results.addTopLevelItem(QTreeWidgetItem([name, value]))
        self._results.resizeColumnToContents(0)

        # The assumptions panel must never be empty for a reduced-order result.
        lines = ["LIMITATIONS IN FORCE FOR THIS RESULT", ""]
        for caveat in curve.caveats:
            lines.append(f"- {caveat.message}")
        lines.append("")
        lines.append("NOTES")
        lines.append("")
        for note in curve.notes:
            lines.append(f"- {note}")
        for member in members:
            for note in member.notes:
                lines.append(f"- Member {member.index}: {note}")
        self._assumptions.setPlainText("\n".join(lines))

    def clear_results(self) -> None:
        self._provenance_badge.setText("No analysis run")
        self._provenance_badge.setStyleSheet("font-weight: bold;")
        self._results.clear()
        self._assumptions.clear()
