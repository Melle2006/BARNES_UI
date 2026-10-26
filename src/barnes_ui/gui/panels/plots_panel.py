"""Plot panel for torque-angle curves and section profiles.

Uses Matplotlib's Qt backend. Two rules carried over from the provenance system:

* A curve is annotated with its provenance tag on the axes themselves, not only in a
  side panel, so that a figure exported into a report cannot be separated from the
  statement of how trustworthy it is.
* A reduced-order or assumption-grade result is drawn dashed and carries a visible
  banner. In Phase 3 an FEA curve will be drawn solid on the same axes, and the two
  must not look alike.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtWidgets import QSizePolicy, QTabWidget, QVBoxLayout, QWidget

from ...core.mechanics.curved_beam import TorqueAngleCurve
from ...core.provenance import Provenance

logger = logging.getLogger(__name__)

__all__ = ["PlotsPanel"]

_STYLE = {
    "figure.facecolor": "#2B2F36",
    "axes.facecolor": "#2B2F36",
    "axes.edgecolor": "#5A6069",
    "axes.labelcolor": "#E8E8E8",
    "text.color": "#E8E8E8",
    "xtick.color": "#C8C8C8",
    "ytick.color": "#C8C8C8",
    "grid.color": "#3E444C",
    "legend.facecolor": "#343941",
    "legend.edgecolor": "#5A6069",
}

_BANNER = {
    Provenance.UNVALIDATED_ASSUMPTION:
        "UNVALIDATED - material parameters are assumed, not measured",
    Provenance.REDUCED_ORDER_PREDICTION:
        "REDUCED-ORDER SCREENING MODEL - error against FEA not yet measured",
    Provenance.ANALYTICAL_ESTIMATE:
        "ANALYTICAL ESTIMATE - valid only within its stated assumptions",
}


class PlotsPanel(QWidget):
    """Tabbed plots: torque-angle, stiffness, section profiles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        import matplotlib
        matplotlib.use("QtAgg")
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self._Figure = Figure
        self._Canvas = FigureCanvasQTAgg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._torque_canvas = self._new_canvas()
        self._strain_canvas = self._new_canvas()
        self._section_canvas = self._new_canvas()
        self._profile_canvas = self._new_canvas()

        self._tabs.addTab(self._torque_canvas, "Torque-angle")
        self._tabs.addTab(self._strain_canvas, "Strain-angle")
        self._tabs.addTab(self._section_canvas, "Centreline")
        self._tabs.addTab(self._profile_canvas, "Section profile")

    def _new_canvas(self):
        figure = self._Figure(figsize=(6.0, 4.0), dpi=100)
        canvas = self._Canvas(figure)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return canvas

    # -- drawing ---------------------------------------------------------------

    def show_analysis(self, curve: TorqueAngleCurve, members) -> None:
        import matplotlib.pyplot as plt

        with plt.rc_context(_STYLE):
            self._draw_torque(curve)
            self._draw_strain(curve)
            self._draw_centreline(members)
            self._draw_profile(members)

    def _draw_torque(self, curve: TorqueAngleCurve) -> None:
        figure = self._torque_canvas.figure
        figure.clear()
        axes = figure.add_subplot(111)

        # Dashed on purpose: a reduced-order curve must not be mistaken for FEA when
        # both appear on the same axes in Phase 3.
        style = "--" if curve.provenance.requires_warning_banner else "-"
        axes.plot(
            curve.angles_degrees, curve.torques, style, color="#E8A33D", linewidth=2,
            label=f"Restoring torque [{curve.provenance.label}]",
        )
        axes.set_xlabel("Joint angle (deg)")
        axes.set_ylabel("Restoring torque (N.mm)")
        axes.set_title("Restoring torque against joint angle")
        axes.grid(True, alpha=0.3)
        axes.legend(loc="upper left", fontsize=8)
        self._annotate(axes, curve.provenance)
        figure.tight_layout()
        self._torque_canvas.draw_idle()

    def _draw_strain(self, curve: TorqueAngleCurve) -> None:
        figure = self._strain_canvas.figure
        figure.clear()
        axes = figure.add_subplot(111)
        axes.plot(
            curve.angles_degrees, curve.peak_strains * 100.0, "--",
            color="#D9534F", linewidth=2, label="Peak bending strain",
        )
        axes.set_xlabel("Joint angle (deg)")
        axes.set_ylabel("Peak engineering strain (%)")
        axes.set_title("Peak bending strain against joint angle")
        axes.grid(True, alpha=0.3)

        # A horizontal marker where small-strain theory has clearly expired. Beyond
        # roughly 5 per cent, a linear-elastic beam model is being used far outside its
        # range and the plot should say so rather than leave it to be inferred.
        if float(curve.peak_strains.max()) > 0.05:
            axes.axhline(5.0, color="#9AA3AD", linestyle=":", linewidth=1)
            axes.text(
                0.02, 5.6, "small-strain validity limit (~5%)",
                transform=axes.get_yaxis_transform(), fontsize=7, color="#9AA3AD",
            )
        axes.legend(loc="upper left", fontsize=8)
        self._annotate(axes, curve.provenance)
        figure.tight_layout()
        self._strain_canvas.draw_idle()

    def _draw_centreline(self, members) -> None:
        figure = self._section_canvas.figure
        figure.clear()
        axes = figure.add_subplot(111)
        for member in members:
            positions = member.positions()
            axes.plot(
                positions[:, 1], positions[:, 2], "-o", markersize=2, linewidth=1.5,
                label=f"Member {member.index}",
            )
        axes.set_xlabel("Y (mm)")
        axes.set_ylabel("Z (mm)")
        axes.set_title("Extracted centrelines, measured from the CAD geometry")
        axes.set_aspect("equal", adjustable="datalim")
        axes.grid(True, alpha=0.3)
        axes.legend(loc="best", fontsize=8)
        self._annotate(axes, Provenance.GEOMETRIC_MEASUREMENT)
        figure.tight_layout()
        self._section_canvas.draw_idle()

    def _draw_profile(self, members) -> None:
        figure = self._profile_canvas.figure
        figure.clear()
        area_axes = figure.add_subplot(211)
        inertia_axes = figure.add_subplot(212)

        areas = []
        inertias = []
        for member in members:
            s = member.arc_coordinates()
            area = member.area_profile()
            inertia = member.inertia_profile()
            areas.append(area)
            inertias.append(inertia)
            area_axes.plot(s, area, linewidth=1.5, label=f"Member {member.index}")
            inertia_axes.plot(s, inertia, linewidth=1.5, label=f"Member {member.index}")

        area_axes.set_ylabel("Area (mm^2)")
        area_axes.set_title("Normal-section properties along the centreline")
        area_axes.grid(True, alpha=0.3)
        area_axes.legend(loc="best", fontsize=8)

        inertia_axes.set_xlabel("Arc length s (mm)")
        inertia_axes.set_ylabel("I about joint axis (mm^4)")
        inertia_axes.grid(True, alpha=0.3)

        # A constant section would otherwise be auto-scaled to its own numerical noise.
        # On the A3 twin strap the area is constant to about 1 part in 100,000, and
        # matplotlib happily zoomed into that, drawing a violently jagged line with an
        # axis labelled "1e-5+2". Anyone reading it would conclude the section varies
        # wildly when it does not vary at all. Where the variation is negligible, show
        # the section against a zero baseline and say how flat it is.
        self._scale_flat_axis(area_axes, areas, "Area")
        self._scale_flat_axis(inertia_axes, inertias, "I")

        self._annotate(area_axes, Provenance.GEOMETRIC_MEASUREMENT)
        figure.tight_layout()
        self._profile_canvas.draw_idle()

    @staticmethod
    def _scale_flat_axis(axes, series: list, quantity: str,
                         flat_threshold: float = 1.0e-3) -> None:
        """Keep a near-constant series from being plotted as magnified noise.

        ``flat_threshold`` is a relative peak-to-peak variation. Below it the series is
        treated as constant: the y-axis is anchored at zero so the line reads flat, and
        the actual variation is stated so the reader is not left guessing whether the
        flatness is real or an artefact of the scaling.
        """
        if not series:
            return
        stacked = np.concatenate([np.asarray(s, dtype=float) for s in series])
        if stacked.size == 0:
            return
        mean = float(np.mean(stacked))
        if mean <= 0:
            return
        variation = float(np.ptp(stacked)) / mean
        if variation >= flat_threshold:
            return

        axes.set_ylim(0.0, mean * 1.35)
        axes.text(
            0.01, 0.90,
            f"{quantity} is constant to within {variation * 100:.4f}% "
            f"(mean {mean:.6g}); axis anchored at zero so the variation is not "
            f"magnified",
            transform=axes.transAxes, fontsize=7, color="#7FB069", va="top",
        )

    @staticmethod
    def _annotate(axes, provenance: Provenance) -> None:
        """Stamp the provenance onto the axes themselves.

        On the figure rather than beside it, so that an exported PNG dropped into a
        report still carries the statement of how far it can be trusted.
        """
        banner = _BANNER.get(provenance)
        if banner:
            axes.text(
                0.99, 0.02, banner, transform=axes.transAxes, ha="right", va="bottom",
                fontsize=7, color="#D9534F",
                bbox=dict(facecolor="#2B2F36", edgecolor="#D9534F", alpha=0.85, pad=2),
            )
        else:
            axes.text(
                0.99, 0.02, provenance.label, transform=axes.transAxes,
                ha="right", va="bottom", fontsize=7, color="#7FB069",
            )

    def clear(self) -> None:
        for canvas in (
            self._torque_canvas, self._strain_canvas,
            self._section_canvas, self._profile_canvas,
        ):
            canvas.figure.clear()
            canvas.draw_idle()
