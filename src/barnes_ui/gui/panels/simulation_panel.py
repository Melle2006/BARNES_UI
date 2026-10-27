"""Hand simulation: kinematic preview and reduced-order dynamics, kept apart.

Phase 5's user-facing half, and the panel where the project's central discipline is
most at risk. An animation of a hand closing with a torque plotted beside it is the
most persuasive and least verified thing this application can produce.

The separation is not enforced here. It is enforced in
:mod:`barnes_ui.core.kinematics.modes`, where the Mode 1 result type has nowhere to
put a torque, and this panel simply cannot display one in preview mode because none
reaches it. What the panel does is show the mode's own banner text, which comes from
the result rather than from this file, so a future edit here cannot quietly drop it.

Mode 2 needs a joint spring, and a joint spring needs FEA points. Without them the
mode is unavailable and says why. There is no option to fit a spring to the
reduced-order curve and call the result dynamics: that would wrap a 24 per cent error
in an animation and present it as a simulation.
"""

from __future__ import annotations

import logging
import math

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.kinematics.modes import SimulationMode
from ...core.kinematics.spring import (
    JointSpring,
    SpringFitError,
    SpringFitKind,
    fit_joint_spring,
)
from ...core.provenance import Provenance
from ._common import (
    banner_label,
    float_spin,
    int_spin,
    note_label,
    provenance_badge,
)

logger = logging.getLogger(__name__)

__all__ = ["SimulationPanel"]

_MODE_COLOURS = {
    SimulationMode.KINEMATIC_PREVIEW: "#9AA3AD",
    SimulationMode.REDUCED_ORDER: "#E8A33D",
    SimulationMode.COUPLED_FEA: "#4C8FBD",
}


class SimulationPanel(QWidget):
    """Drive a joint through a motion, with or without a restoring torque."""

    run_requested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spring: JointSpring | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self._banner = banner_label(
            SimulationMode.KINEMATIC_PREVIEW.banner, "#9AA3AD"
        )
        layout.addWidget(self._banner)

        layout.addWidget(self._build_mode_box())
        layout.addWidget(self._build_spring_box(), stretch=1)
        layout.addWidget(self._build_motion_box())
        layout.addWidget(self._build_results_box(), stretch=1)

        self._on_mode_changed()

    # -- construction ----------------------------------------------------------

    def _build_mode_box(self) -> QWidget:
        box = QGroupBox("Mode")
        layout = QVBoxLayout(box)
        self._mode = QComboBox()
        self._mode.addItem(
            SimulationMode.KINEMATIC_PREVIEW.label, SimulationMode.KINEMATIC_PREVIEW
        )
        self._mode.addItem(
            SimulationMode.REDUCED_ORDER.label, SimulationMode.REDUCED_ORDER
        )
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self._mode)
        layout.addWidget(note_label(
            "Coupled FEA is not offered. Phase 6 established what this toolchain can "
            "and cannot do; a whole-hand deformable solve is not on that list."
        ))
        return box

    def _build_spring_box(self) -> QWidget:
        box = QGroupBox("Joint spring, from FEA points")
        layout = QVBoxLayout(box)

        layout.addWidget(note_label(
            "Enter the angle and reaction moment from each FEA run of this joint, "
            "one row per run. Three points is the minimum: with two you have a "
            "straight line and should say so rather than fitting a curve."
        ))

        self._points = QTableWidget(5, 2)
        self._points.setHorizontalHeaderLabels(["Angle (deg)", "Torque (N.mm)"])
        self._points.setMinimumHeight(150)
        layout.addWidget(self._points)

        form = QFormLayout()
        self._fit_kind = QComboBox()
        self._fit_kind.addItem(
            "Shape-preserving interpolation (PCHIP)", SpringFitKind.INTERPOLATED
        )
        self._fit_kind.addItem(
            "Odd polynomial (symmetric designs)", SpringFitKind.ODD_POLYNOMIAL
        )
        self._terms = int_spin(1, 6, 3)
        form.addRow("Fit:", self._fit_kind)
        form.addRow("Polynomial terms:", self._terms)
        layout.addLayout(form)

        self._fit_button = QPushButton("Fit joint spring")
        self._fit_button.clicked.connect(self._fit)
        layout.addWidget(self._fit_button)

        self._spring_output = QTextEdit()
        self._spring_output.setReadOnly(True)
        self._spring_output.setMaximumHeight(90)
        layout.addWidget(self._spring_output)
        return box

    def _build_motion_box(self) -> QWidget:
        box = QGroupBox("Motion")
        form = QFormLayout(box)

        self._profile = QComboBox()
        self._profile.addItem("Linear ramp", "ramp")
        self._profile.addItem("Sinusoidal cycle (out and back)", "sinusoid")
        self._profile.addItem("Trapezoid (ramp, hold, ramp)", "trapezoid")

        self._start = float_spin(-90.0, 180.0, 1, 0.0, 1.0, " deg")
        self._end = float_spin(-90.0, 180.0, 1, 90.0, 1.0, " deg")
        self._steps = int_spin(5, 501, 51)

        form.addRow("Profile:", self._profile)
        form.addRow("From:", self._start)
        form.addRow("To:", self._end)
        form.addRow("Samples:", self._steps)

        self._run_button = QPushButton("Run")
        self._run_button.clicked.connect(self._emit_request)
        form.addRow(self._run_button)

        form.addRow(note_label(
            "A profile prescribes where the joint is at each instant. Nothing here "
            "solves an equation of motion, so the time axis is a parameterisation "
            "and not a physical schedule."
        ))
        return box

    def _build_results_box(self) -> QWidget:
        box = QGroupBox("Result")
        layout = QVBoxLayout(box)
        self._badges = QWidget()
        self._badge_layout = QVBoxLayout(self._badges)
        self._badge_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._badges)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self._output)
        return box

    # -- behaviour -------------------------------------------------------------

    def mode(self) -> SimulationMode:
        return self._mode.currentData()

    def _on_mode_changed(self) -> None:
        mode = self.mode()
        self._banner.setText(mode.banner)
        self._banner.setStyleSheet(
            f"background: {_MODE_COLOURS[mode]}; color: #15181C; font-weight: bold; "
            "padding: 6px; border-radius: 3px;"
        )
        needs_spring = mode is SimulationMode.REDUCED_ORDER
        self._run_button.setEnabled(not needs_spring or self._spring is not None)
        if needs_spring and self._spring is None:
            self._run_button.setToolTip(
                "Reduced-order dynamics needs a joint spring fitted to FEA results. "
                "Fitting one to the reduced-order curve instead would wrap that "
                "model's own error inside an animation and call it a simulation."
            )
        else:
            self._run_button.setToolTip("")

    def _collect_points(self) -> tuple[np.ndarray, np.ndarray]:
        angles: list[float] = []
        torques: list[float] = []
        for row in range(self._points.rowCount()):
            angle_item = self._points.item(row, 0)
            torque_item = self._points.item(row, 1)
            if angle_item is None or torque_item is None:
                continue
            if not angle_item.text().strip() or not torque_item.text().strip():
                continue
            try:
                angles.append(math.radians(float(angle_item.text())))
                torques.append(float(torque_item.text()))
            except ValueError:
                raise SpringFitError(
                    f"Row {row + 1} does not contain two numbers."
                ) from None
        return np.array(angles), np.array(torques)

    def _fit(self) -> None:
        try:
            angles, torques = self._collect_points()
            self._spring = fit_joint_spring(
                angles, torques,
                source="entered by hand from FEA runs in this session",
                name="joint",
                kind=self._fit_kind.currentData(),
                polynomial_terms=self._terms.value(),
                provenance=Provenance.FEA_RESULT,
            )
        except SpringFitError as exc:
            self._spring = None
            self._spring_output.setPlainText(f"Cannot fit a spring: {exc}")
        else:
            low, high = self._spring.fitted_range_degrees
            self._spring_output.setPlainText(
                self._spring.describe()
                + f"\nValid from {low:.1f} to {high:.1f} deg. Outside that range the "
                  "spring refuses to report a torque."
            )
        self._on_mode_changed()

    def spring(self) -> JointSpring | None:
        return self._spring

    def settings(self) -> dict:
        return {
            "mode": self.mode(),
            "profile": self._profile.currentData(),
            "start": math.radians(self._start.value()),
            "end": math.radians(self._end.value()),
            "steps": self._steps.value(),
            "spring": self._spring,
        }

    def _emit_request(self) -> None:
        self.run_requested.emit(self.settings())

    # -- display ---------------------------------------------------------------

    def show_preview(self, poses) -> None:
        """Mode 1 output. Positions only -- there is no torque to show."""
        self._clear_badges()
        self._badge_layout.addWidget(
            provenance_badge(Provenance.GEOMETRIC_MEASUREMENT)
        )
        lines = [SimulationMode.KINEMATIC_PREVIEW.banner, ""]
        lines.append(f"{len(poses)} poses.")
        for pose in poses[:: max(1, len(poses) // 10)]:
            angles = ", ".join(
                f"{name} {math.degrees(value):7.2f} deg"
                for name, value in pose.angles.items()
            )
            lines.append(f"  t={pose.time:6.3f}  {angles}")
        self._output.setPlainText("\n".join(lines))

    def show_simulation(self, result) -> None:
        """Mode 2 output: torque history, with the caveats that come with it."""
        self._clear_badges()
        self._badge_layout.addWidget(
            provenance_badge(Provenance.REDUCED_ORDER_PREDICTION)
        )
        self._output.setPlainText(result.summary())

    def show_torque_history(self, angles, torques, spring) -> None:
        """Mode 2 output for a single joint driven through a prescribed motion.

        A public method rather than the window writing into the text box, so the
        banner and the caveats are attached here, once, instead of at every call
        site that happens to produce a torque.
        """
        self._clear_badges()
        self._badge_layout.addWidget(
            provenance_badge(Provenance.REDUCED_ORDER_PREDICTION)
        )
        lines = [
            SimulationMode.REDUCED_ORDER.banner,
            "",
            spring.describe(),
            "",
            f"{'angle (deg)':>12}{'torque (N.mm)':>16}",
        ]
        stride = max(1, len(angles) // 20)
        for angle, torque in zip(angles[::stride], torques[::stride]):
            lines.append(f"{math.degrees(angle):12.2f}{torque:16.6g}")
        lines.append("")
        lines.append("Caveats:")
        lines.extend(f"- {c.message}" for c in spring.caveats)
        self._output.setPlainText("\n".join(lines))

    def show_error(self, message: str) -> None:
        self._clear_badges()
        self._output.setPlainText(message)

    def _clear_badges(self) -> None:
        while self._badge_layout.count():
            self._badge_layout.takeAt(0).widget().deleteLater()
