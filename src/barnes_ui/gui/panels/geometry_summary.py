"""A compact read-only summary of the displayed geometry, for the Design workspace.

The full Geometry panel -- body tree, every measured property, units, warnings -- is
the right tool for diagnosing a questionable import and the wrong thing to put beside
a set of parameter spinboxes, where it crowds out the controls the user came for. So
Design gets this card and Inspect keeps the panel.

Nothing is computed here. Every value is read straight off the model, which is also
why there is no provenance badge: these are geometric measurements, exactly as the
Geometry panel labels them, and a second badge in a second style would start the drift
that ``_common.py`` exists to prevent.

A card that duplicated the readiness logic would be a second place for it to be wrong,
so the verdict and its reasons come from ``model.is_analysis_ready`` and
``model.analysis_readiness_reasons()`` and are only formatted here.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.cad.model import GeometryModel

__all__ = ["GeometrySummary"]


class GeometrySummary(QWidget):
    """What is on screen, in six lines."""

    inspect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        box = QGroupBox("Current geometry")
        inner = QVBoxLayout(box)

        form = QFormLayout()
        self._source = QLabel()
        self._source.setWordWrap(True)
        self._bodies = QLabel()
        self._envelope = QLabel()
        self._volume = QLabel()
        form.addRow("Source:", self._source)
        form.addRow("Bodies:", self._bodies)
        form.addRow("Envelope:", self._envelope)
        form.addRow("Volume:", self._volume)
        inner.addLayout(form)

        self._readiness = QLabel()
        self._readiness.setWordWrap(True)
        font = QFont()
        font.setBold(True)
        self._readiness.setFont(font)
        inner.addWidget(self._readiness)

        self._inspect = QPushButton("Open full inspection...")
        self._inspect.setToolTip(
            "The Inspect workspace: body tree, every measured property, unit "
            "confirmation, topology counts and all warnings."
        )
        self._inspect.clicked.connect(self.inspect_requested.emit)
        inner.addWidget(self._inspect)

        layout.addWidget(box)
        self.clear()

    # -- state -----------------------------------------------------------------

    def clear(self) -> None:
        self._source.setText("Nothing loaded")
        self._source.setStyleSheet("color: #9AA3AD;")
        self._bodies.setText("-")
        self._envelope.setText("-")
        self._volume.setText("-")
        self._readiness.setText(
            "Open a CAD file, or generate a flexure from the parameters below."
        )
        self._readiness.setStyleSheet("color: #9AA3AD;")
        self._inspect.setEnabled(False)

    def show_model(self, model: GeometryModel, *, generated: bool = False) -> None:
        unit = model.unit.symbol
        origin = "generated from parameters" if generated else "imported"

        self._source.setText(
            f"{model.source_path.name}  ({model.source_format.label}, {origin})"
        )
        if model.is_exact:
            self._source.setStyleSheet("color: #7FB069;")
        else:
            self._source.setStyleSheet("color: #E8A33D;")
            self._source.setText(
                self._source.text() + "  -  tessellated, not usable for analysis"
            )

        self._bodies.setText(str(model.solid_count))

        box = model.overall_bounding_box
        if box is None:
            self._envelope.setText("-")
        else:
            dx, dy, dz = box.size
            self._envelope.setText(f"{dx:.3f} x {dy:.3f} x {dz:.3f} {unit}")

        self._volume.setText(f"{model.total_volume:.5g} {unit}^3")

        if model.is_analysis_ready:
            self._readiness.setText("Ready for analysis.")
            self._readiness.setStyleSheet("color: #7FB069;")
        else:
            reasons = model.analysis_readiness_reasons()
            self._readiness.setText(
                "NOT ready for analysis:\n"
                + "\n".join(f"  - {r}" for r in reasons)
            )
            self._readiness.setStyleSheet("color: #E8A33D;")

        self._inspect.setEnabled(True)

    # -- observation, for tests -------------------------------------------------

    def source_text(self) -> str:
        return self._source.text()

    def readiness_text(self) -> str:
        return self._readiness.text()

    def envelope_text(self) -> str:
        return self._envelope.text()
