"""Design-space sweeps, Pareto fronts and material sensitivity.

Phase 7's user-facing half.

The panel is built around a refusal. When the objectives conflict there is no best
design, and the "Best design" field says so instead of naming one. A weighting box
below it will name one, but only once the weights have been typed in, and it shows
them beside the answer. The point is that the trade-off is the user's decision and
should look like one.

The sweep table keeps inadmissible designs, greyed, with the blocking reason in the
tooltip. Dropping them would leave an unexplained cliff at the edge of the feasible
region; keeping them puts the boundary on screen where it belongs.

Every sweep carries one provenance badge for the whole study, taken as the weakest
tag in it. Four hundred rows of numbers read as rigour, and the badge is the counter
to that.
"""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.flexure.templates.meander import MeanderParameters
from ...core.optimise.objectives import (
    Objective,
    OptimisationError,
    centreline_length,
    material_volume,
    minimum_feature,
    peak_strain,
)
from ...core.optimise.pareto import ParetoFront, pareto_front
from ...core.optimise.sweep import SweepAxis, SweepResult, run_sweep
from ._common import float_spin, int_spin, note_label, provenance_badge

logger = logging.getLogger(__name__)

__all__ = ["OptimisePanel"]

_SWEEPABLE = ("width", "thickness", "pitch", "run_length", "n_runs")


class OptimisePanel(QWidget):
    """Sweep the template, rank what comes out, and refuse to over-rank it."""

    sweep_finished = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base: MeanderParameters | None = None
        self._result: SweepResult | None = None
        self._front: ParetoFront | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        layout.addWidget(self._build_axes_box())
        layout.addWidget(self._build_objectives_box())
        layout.addWidget(self._build_run_box())
        layout.addWidget(self._build_table_box(), stretch=2)
        layout.addWidget(self._build_front_box(), stretch=1)

    # -- construction ----------------------------------------------------------

    def _build_axes_box(self) -> QWidget:
        box = QGroupBox("Sweep axes")
        form = QFormLayout(box)

        self._axis_widgets = []
        for index in range(2):
            parameter = QComboBox()
            parameter.addItem("(none)", None)
            for name in _SWEEPABLE:
                parameter.addItem(name, name)
            low = float_spin(0.01, 500.0, 3, 0.8 if index == 0 else 2.0, 0.1)
            high = float_spin(0.01, 500.0, 3, 1.6 if index == 0 else 5.0, 0.1)
            steps = int_spin(2, 40, 5)
            from ._common import row

            form.addRow(f"Axis {index + 1}:", parameter)
            form.addRow("  from / to / steps:", row(low, high, steps))
            self._axis_widgets.append((parameter, low, high, steps))

        self._axis_widgets[0][0].setCurrentIndex(1)   # width by default
        form.addRow(note_label(
            "n_runs is swept as whole numbers; the grid values are rounded. "
            "Combinations the template cannot build -- a pitch at or below the width "
            "-- are reported rather than silently skipped."
        ))
        return box

    def _build_objectives_box(self) -> QWidget:
        box = QGroupBox("Objectives")
        layout = QVBoxLayout(box)

        self._objective_boxes = {
            "material_volume": QCheckBox("Material volume (minimise)"),
            "minimum_feature": QCheckBox("Smallest feature (maximise)"),
            "centreline_length": QCheckBox("Centreline length (maximise)"),
            "peak_strain": QCheckBox("Peak bending strain (minimise)"),
        }
        self._objective_boxes["material_volume"].setChecked(True)
        self._objective_boxes["centreline_length"].setChecked(True)
        for widget in self._objective_boxes.values():
            layout.addWidget(widget)

        form = QFormLayout()
        self._strain_angle = float_spin(1.0, 180.0, 1, 100.0, 5.0, " deg")
        self._min_feature = float_spin(0.05, 5.0, 2, 0.4, 0.05, " mm")
        form.addRow("Strain evaluated at:", self._strain_angle)
        form.addRow("Minimum printable feature:", self._min_feature)
        layout.addLayout(form)

        layout.addWidget(note_label(
            "Rotational stiffness is not offered here. It needs a model, and which "
            "model -- reduced-order, fitted spring or FEA -- changes the answer by "
            "about a quarter on the A3 part. Choosing it in a drop-down would hide "
            "the most consequential decision in the search."
        ))
        return box

    def _build_run_box(self) -> QWidget:
        box = QGroupBox("Run")
        layout = QVBoxLayout(box)
        self._run_button = QPushButton("Sweep")
        self._run_button.clicked.connect(self._run)
        layout.addWidget(self._run_button)
        self._summary = QLabel("Set a base design on the Template tab first.")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._badges = QWidget()
        self._badge_layout = QVBoxLayout(self._badges)
        self._badge_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._badges)
        return box

    def _build_table_box(self) -> QWidget:
        box = QGroupBox("Evaluated designs")
        layout = QVBoxLayout(box)
        self._table = QTableWidget(0, 0)
        self._table.setMinimumHeight(180)
        layout.addWidget(self._table)
        layout.addWidget(note_label(
            "Greyed rows failed a manufacturability check. They are shown so the "
            "edge of the feasible region is visible, and they take no part in any "
            "ranking."
        ))
        return box

    def _build_front_box(self) -> QWidget:
        box = QGroupBox("Trade-off")
        layout = QVBoxLayout(box)
        self._front_output = QTextEdit()
        self._front_output.setReadOnly(True)
        self._front_output.setStyleSheet("font-family: Consolas, monospace;")
        self._front_output.setMinimumHeight(120)
        layout.addWidget(self._front_output)

        form = QFormLayout()
        self._weights = QLineEdit()
        self._weights.setPlaceholderText(
            "material_volume=1, centreline_length=0.5"
        )
        form.addRow("Weights:", self._weights)
        choose = QPushButton("Choose one using these weights")
        choose.clicked.connect(self._choose_weighted)
        form.addRow(choose)
        layout.addLayout(form)

        layout.addWidget(note_label(
            "A weighted pick is a decision, not a calculation. The weights are "
            "required for every objective, because an omitted weight is an implicit "
            "zero and an implicit zero is a decision nobody wrote down."
        ))
        return box

    # -- state -----------------------------------------------------------------

    def set_base_design(self, parameters: MeanderParameters) -> None:
        self._base = parameters
        self._summary.setText(f"Base design: {parameters.describe()}")

    def _objectives(self) -> list[Objective]:
        chosen: list[Objective] = []
        if self._objective_boxes["material_volume"].isChecked():
            chosen.append(material_volume())
        if self._objective_boxes["minimum_feature"].isChecked():
            chosen.append(minimum_feature())
        if self._objective_boxes["centreline_length"].isChecked():
            chosen.append(centreline_length())
        if self._objective_boxes["peak_strain"].isChecked():
            chosen.append(peak_strain(math.radians(self._strain_angle.value())))
        return chosen

    def _axes(self) -> list[SweepAxis]:
        axes: list[SweepAxis] = []
        for parameter, low, high, steps in self._axis_widgets:
            name = parameter.currentData()
            if name is None:
                continue
            count = steps.value()
            start, stop = low.value(), high.value()
            values = [
                start + (stop - start) * i / max(1, count - 1) for i in range(count)
            ]
            if name == "n_runs":
                values = sorted({max(2, int(round(v))) for v in values})
            axes.append(SweepAxis(name, tuple(values)))
        return axes

    # -- behaviour -------------------------------------------------------------

    def _run(self) -> None:
        if self._base is None:
            self._summary.setText(
                "No base design. Set the parameters on the Template tab first; a "
                "sweep varies a design, it does not invent one."
            )
            return
        try:
            axes = self._axes()
            objectives = self._objectives()
            self._result = run_sweep(
                self._base, axes, objectives,
                minimum_feature_size=self._min_feature.value(),
            )
            self._front = pareto_front(self._result.evaluations, objectives)
        except OptimisationError as exc:
            self._summary.setText(f"Cannot sweep: {exc}")
            return

        self._summary.setText(self._result.summary())
        self._show_badge(self._result)
        self._fill_table(self._result, objectives)
        self._show_front(self._front)
        self.sweep_finished.emit(self._result)

    def _show_badge(self, result: SweepResult) -> None:
        while self._badge_layout.count():
            self._badge_layout.takeAt(0).widget().deleteLater()
        self._badge_layout.addWidget(provenance_badge(result.provenance))

    def _fill_table(self, result: SweepResult, objectives) -> None:
        columns = ["design"] + [o.name for o in objectives]
        self._table.clear()
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setRowCount(len(result.evaluations))

        grey = QBrush(QColor("#6B737C"))
        for row_index, evaluation in enumerate(result.evaluations):
            cells = [evaluation.design.named()] + [
                f"{evaluation.value(o.name):.6g}" for o in objectives
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if not evaluation.is_valid:
                    item.setForeground(grey)
                    item.setToolTip(
                        "; ".join(i.message for i in evaluation.blocking_issues)
                    )
                self._table.setItem(row_index, column, item)
        self._table.resizeColumnsToContents()

    def _show_front(self, front: ParetoFront) -> None:
        lines = [front.summary(), ""]
        try:
            winner = front.winner()
        except OptimisationError as exc:
            lines.append("Best design: there isn't one.")
            lines.append(str(exc))
        else:
            lines.append(f"Best design: {winner.design.named()}")
        self._front_output.setPlainText("\n".join(lines))

    def _choose_weighted(self) -> None:
        if self._front is None:
            return
        try:
            weights = _parse_weights(self._weights.text())
            chosen = self._front.best_by_weights(weights)
        except (OptimisationError, ValueError) as exc:
            self._front_output.setPlainText(
                self._front.summary() + f"\n\nCannot choose: {exc}"
            )
            return
        stated = ", ".join(f"{k}={v:g}" for k, v in sorted(weights.items()))
        self._front_output.setPlainText(
            self._front.summary()
            + f"\n\nWith weights {stated}: {chosen.design.named()}"
            + "\nThese weights are the decision. Changing them changes the answer."
        )


def _parse_weights(text: str) -> dict[str, float]:
    """Parse ``name=value, name=value`` into a mapping."""
    weights: dict[str, float] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"{part!r} is not name=value.")
        name, value = part.split("=", 1)
        weights[name.strip()] = float(value)
    if not weights:
        raise ValueError(
            "No weights given. A weighted pick needs a weight for every objective."
        )
    return weights
