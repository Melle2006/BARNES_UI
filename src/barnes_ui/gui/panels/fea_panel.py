"""Nonlinear FEA: solver status, mesh, run, and the reduced-order comparison.

Phase 3's user-facing half, plus the Phase 6 capability list.

Three things this panel must do and most FEA front-ends do not.

**Say whether there is a solver at all, before anything else.** With CalculiX absent
the run button is disabled and the installation instructions are on screen. There is
no fallback to the reduced-order model: Phase 3 criterion 6 exists because a silent
substitution would leave a reduced-order number in a box labelled FEA.

**Show the convergence diagnostics beside the result, not behind a button.**
Increments, cutbacks and warnings are how an experienced reader judges whether to
believe a converged run, and the A3 flexure's second wrong answer was detectable
*only* from a cutback count that nothing displayed.

**Put the reduced-order and FEA numbers side by side with the gap as a percentage.**
That comparison is Phase 3 criterion 7 and it is the single most useful thing this
application can show: it says how much the fast model can be trusted on this part.

The capability list is read from the Phase 6 registry rather than hard-coded. A
feature whose benchmark has not been run on this machine is shown as unavailable with
the reason, because "CalculiX supports contact" is not the same statement as "contact
works here".
"""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.fea.capabilities import Capability, CapabilityRegistry, CapabilityStatus
from ...core.fea.solver import SolverInfo, find_solver, installation_instructions
from ...core.provenance import Provenance
from ._common import float_spin, int_spin, note_label, provenance_badge, row

logger = logging.getLogger(__name__)

__all__ = ["FeaPanel"]

_STATUS_COLOURS = {
    CapabilityStatus.PASSED: "#7FB069",
    CapabilityStatus.FAILED: "#D9534F",
    CapabilityStatus.NOT_TESTED: "#9AA3AD",
    CapabilityStatus.NOT_AVAILABLE: "#8A6FB0",
}


class FeaPanel(QWidget):
    """Configure and run a CalculiX analysis, and compare it against Phase 2."""

    analysis_requested = Signal(dict)
    cancel_requested = Signal()
    axis_suggestion_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._solver: SolverInfo | None = None
        self._registry = CapabilityRegistry.load()
        self._reduced_order_stiffness: float | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        layout.addWidget(self._build_solver_box())
        layout.addWidget(self._build_mesh_box())
        layout.addWidget(self._build_run_box())
        layout.addWidget(self._build_results_box(), stretch=2)
        layout.addWidget(self._build_comparison_box())
        layout.addWidget(self._build_capability_box(), stretch=1)

        self.refresh_solver()

    # -- construction ----------------------------------------------------------

    def _build_solver_box(self) -> QWidget:
        box = QGroupBox("Solver")
        layout = QVBoxLayout(box)
        self._solver_label = QLabel()
        self._solver_label.setWordWrap(True)
        layout.addWidget(self._solver_label)

        self._solver_help = QTextEdit()
        self._solver_help.setReadOnly(True)
        self._solver_help.setMaximumHeight(120)
        self._solver_help.hide()
        layout.addWidget(self._solver_help)

        rescan = QPushButton("Look again")
        rescan.clicked.connect(self.refresh_solver)
        layout.addWidget(rescan)
        return box

    def _build_mesh_box(self) -> QWidget:
        box = QGroupBox("Mesh")
        form = QFormLayout(box)

        self._smallest_feature = float_spin(0.05, 50.0, 3, 1.0, 0.1, " mm")
        self._through_thickness = int_spin(1, 8, 2)
        self._second_order = QCheckBox("Second-order tetrahedra (C3D10)")
        self._second_order.setChecked(True)

        form.addRow("Thinnest feature:", self._smallest_feature)
        form.addRow("Elements across it:", self._through_thickness)
        form.addRow(self._second_order)
        form.addRow(note_label(
            "The thinnest feature must be stated when it is interior. On the A3 twin "
            "strap the bounding box's smallest extent is 10.95 mm while the strap is "
            "1.0 mm thick, and the default sizing produced a mesh CalculiX rejected "
            "outright."
        ))
        form.addRow(note_label(
            "First-order tetrahedra lock in a nearly incompressible material: the run "
            "converges cleanly and reports the part as far stiffer than it is, with "
            "no warning from the solver. Leave second order on for TPU."
        ))
        return box

    def _build_run_box(self) -> QWidget:
        box = QGroupBox("Joint rotation")
        form = QFormLayout(box)

        self._angle = float_spin(0.1, 120.0, 2, 2.0, 0.5, " deg")
        self._collar_depth = float_spin(0.1, 50.0, 2, 3.2, 0.1, " mm")
        form.addRow("Prescribed rotation:", self._angle)
        form.addRow("Attachment depth:", self._collar_depth)

        self._axis_point = [float_spin(-1000.0, 1000.0, 3, 0.0, 0.1) for _ in range(3)]
        form.addRow("Axis passes through (mm):", row(*self._axis_point))

        self._suggest_button = QPushButton("Suggest from the bounding box")
        self._suggest_button.clicked.connect(self.axis_suggestion_requested)
        form.addRow(self._suggest_button)

        form.addRow(note_label(
            "The axis is a required input, not a default. On the A3 twin strap the "
            "bounding box centre sits two millimetres above the real joint, because "
            "the straps arch upward and drag the box with them -- and a run at the "
            "wrong height converges perfectly and reports a different stiffness. "
            "Check the suggestion against the model."
        ))
        form.addRow(note_label(
            "Every surface within the attachment depth of each end is tied. Tying "
            "one surface of a collar rather than all of them is not an approximation "
            "of tying all of them; it is a different structure, and on the A3 part it "
            "gave an answer 63 times out."
        ))

        self._run_button = QPushButton("Run FEA")
        self._run_button.clicked.connect(self._emit_request)
        form.addRow(self._run_button)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self.cancel_requested)
        self._cancel_button.setEnabled(False)
        form.addRow(self._cancel_button)
        return box

    def _build_results_box(self) -> QWidget:
        box = QGroupBox("Result")
        layout = QVBoxLayout(box)
        self._badge_row = QWidget()
        self._badge_layout = QVBoxLayout(self._badge_row)
        self._badge_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._badge_row)

        self._result_output = QTextEdit()
        self._result_output.setReadOnly(True)
        self._result_output.setStyleSheet("font-family: Consolas, monospace;")
        self._result_output.setPlaceholderText(
            "Reaction moment, convergence record and caveats appear here."
        )
        layout.addWidget(self._result_output)
        return box

    def _build_comparison_box(self) -> QWidget:
        box = QGroupBox("Reduced-order versus FEA")
        layout = QVBoxLayout(box)
        self._comparison = QLabel(
            "Run the Phase 2 reduced-order analysis and an FEA of the same joint to "
            "see the gap between them."
        )
        self._comparison.setWordWrap(True)
        self._comparison.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self._comparison)
        layout.addWidget(note_label(
            "Both models are linear in the elastic modulus, so the ratio between them "
            "does not depend on the material being calibrated even though neither "
            "absolute value can be trusted until it is."
        ))
        return box

    def _build_capability_box(self) -> QWidget:
        box = QGroupBox("Advanced capabilities (Phase 6)")
        layout = QVBoxLayout(box)

        self._capabilities = QTreeWidget()
        self._capabilities.setHeaderLabels(["Capability", "Status"])
        self._capabilities.setRootIsDecorated(False)
        self._capabilities.setMinimumHeight(140)
        layout.addWidget(self._capabilities)
        layout.addWidget(note_label(
            "Read from the benchmark registry written by "
            "scripts/phase6_benchmarks.py. A capability is offered only where a "
            "benchmark with a known answer has been reproduced on this machine; "
            "untested means unavailable."
        ))
        self._populate_capabilities()
        return box

    # -- state -----------------------------------------------------------------

    def refresh_solver(self) -> None:
        self._solver = find_solver()
        if self._solver is None:
            self._solver_label.setText(
                "CalculiX was not found. FEA is unavailable, and the application "
                "will NOT substitute the reduced-order model for it."
            )
            self._solver_label.setStyleSheet("color: #D9534F; font-weight: bold;")
            self._solver_help.setPlainText(installation_instructions())
            self._solver_help.show()
            self._run_button.setEnabled(False)
        else:
            self._solver_label.setText(self._solver.describe())
            self._solver_label.setStyleSheet("color: #7FB069;")
            self._solver_help.hide()
            self._run_button.setEnabled(True)

    @property
    def solver_available(self) -> bool:
        """Whether a CalculiX executable was found by the last ``refresh_solver``.

        Public so that the workflow indicator reports solver availability from the
        same discovery this panel ran, rather than probing the filesystem again and
        possibly disagreeing with what is on screen.
        """
        return self._solver is not None

    @property
    def solver_description(self) -> str | None:
        return self._solver.describe() if self._solver is not None else None

    def reload_capabilities(self) -> None:
        self._registry = CapabilityRegistry.load()
        self._populate_capabilities()

    def _populate_capabilities(self) -> None:
        self._capabilities.clear()
        for capability in Capability:
            record = self._registry.record(capability)
            item = QTreeWidgetItem([capability.label, record.status.label])
            item.setToolTip(
                1,
                record.evidence or capability.benchmark_description,
            )
            colour = _STATUS_COLOURS[record.status]
            item.setForeground(1, _brush(colour))
            self._capabilities.addTopLevelItem(item)
        self._capabilities.resizeColumnToContents(0)

    def set_running(self, running: bool) -> None:
        self._run_button.setEnabled(not running and self._solver is not None)
        self._cancel_button.setEnabled(running)

    def set_reduced_order_stiffness(self, value: float | None) -> None:
        """Remember the Phase 2 answer so the comparison can be drawn later."""
        self._reduced_order_stiffness = value

    def set_axis_point(self, point) -> None:
        for spin, value in zip(self._axis_point, point):
            spin.setValue(float(value))

    def axis_point(self) -> tuple[float, float, float]:
        return tuple(spin.value() for spin in self._axis_point)

    def settings(self) -> dict:
        return {
            "axis_point": self.axis_point(),
            "smallest_dimension": self._smallest_feature.value(),
            "elements_through_thickness": self._through_thickness.value(),
            "second_order": self._second_order.isChecked(),
            "rotation_deg": self._angle.value(),
            "collar_depth": self._collar_depth.value(),
        }

    def _emit_request(self) -> None:
        self.analysis_requested.emit(self.settings())

    # -- display ---------------------------------------------------------------

    def show_result(self, result, stiffness: float | None, rotation_deg: float) -> None:
        """Display a finished run: numbers, convergence record and caveats."""
        while self._badge_layout.count():
            self._badge_layout.takeAt(0).widget().deleteLater()

        lines = [result.mesh_description, "", result.convergence.summary]
        if not result.is_trustworthy:
            self._badge_layout.addWidget(
                provenance_badge(Provenance.UNVALIDATED_ASSUMPTION)
            )
            lines.insert(
                0,
                "NO RESULT. This run did not produce a trustworthy solution, so "
                "nothing is reported from it."
                + (
                    " It converged on a null problem: every displacement and every "
                    "reaction is exactly zero, which means nothing was actually "
                    "loaded."
                    if result.is_null_solution else ""
                ),
            )
            self._result_output.setPlainText("\n".join(lines))
            return

        self._badge_layout.addWidget(provenance_badge(Provenance.FEA_RESULT))
        if stiffness is not None:
            lines.insert(0, f"rotational stiffness  {stiffness:12.6g} N.mm/rad")
            moment = stiffness * math.radians(rotation_deg)
            lines.insert(
                0,
                f"reaction moment       {moment:12.6g} N.mm at {rotation_deg:g} deg",
            )
        lines.append("")
        lines.append("Caveats:")
        lines.extend(f"- {c.message}" for c in result.caveats())
        self._result_output.setPlainText("\n".join(lines))

        self._update_comparison(stiffness)

    def _update_comparison(self, fea_stiffness: float | None) -> None:
        rom = self._reduced_order_stiffness
        if rom is None or fea_stiffness is None or fea_stiffness == 0.0:
            return
        ratio = rom / fea_stiffness
        self._comparison.setText(
            f"reduced-order  {rom:12.6g} N.mm/rad\n"
            f"FEA            {fea_stiffness:12.6g} N.mm/rad\n"
            f"ratio          {ratio:12.4f}\n"
            f"the fast model is {abs(ratio - 1.0) * 100:.1f} % "
            f"{'stiff' if ratio > 1 else 'soft'}"
        )


def _brush(colour: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(colour))
