"""Widgets shared by the workflow panels.

Factored out when the fourth panel needed the same provenance badge as the first.
Three panels showing the same tag in three slightly different colours would quietly
undermine the one visual convention this application depends on, so the colours and
the badge live here and nowhere else.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from ...core.provenance import Caveat, Provenance

__all__ = [
    "PROVENANCE_COLOURS",
    "provenance_badge",
    "note_label",
    "banner_label",
    "float_spin",
    "int_spin",
    "row",
    "caveat_text",
]

#: One colour per provenance tag, used by every panel.
#:
#: Red through amber to green, following the IntEnum's own ordering, so the colour
#: carries the same ranking the tag does. Analytical estimates share amber with
#: reduced-order predictions because both are "valid inside assumptions you should
#: read", and experimentally validated shares green with measured because both are
#: facts about something real.
PROVENANCE_COLOURS = {
    Provenance.UNVALIDATED_ASSUMPTION: "#D9534F",
    Provenance.REDUCED_ORDER_PREDICTION: "#E8A33D",
    Provenance.ANALYTICAL_ESTIMATE: "#E8A33D",
    Provenance.FEA_RESULT: "#4C8FBD",
    Provenance.GEOMETRIC_MEASUREMENT: "#7FB069",
    Provenance.EXPERIMENTALLY_VALIDATED: "#7FB069",
}


def provenance_badge(provenance: Provenance) -> QLabel:
    """A coloured label naming a provenance tag, with its description as a tooltip."""
    label = QLabel(provenance.label.upper())
    label.setToolTip(provenance.description)
    colour = PROVENANCE_COLOURS[provenance]
    label.setStyleSheet(
        f"background: {colour}; color: #15181C; font-weight: bold; "
        "padding: 2px 8px; border-radius: 3px;"
    )
    return label


def note_label(text: str) -> QLabel:
    """Muted explanatory text. Wrapped, because these are sentences, not captions."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #9AA3AD;")
    return label


def banner_label(text: str, colour: str = "#D9534F") -> QLabel:
    """A prominent, always-visible warning banner.

    Used for the simulation mode banner, which a result carries rather than a widget
    deciding to render -- see core/kinematics/modes.py.
    """
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"background: {colour}; color: #15181C; font-weight: bold; padding: 6px; "
        "border-radius: 3px;"
    )
    return label


def float_spin(minimum: float, maximum: float, decimals: int,
               value: float = 0.0, step: float = 0.1,
               suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    spin.setValue(value)
    if suffix:
        spin.setSuffix(suffix)
    return spin


def int_spin(minimum: int, maximum: int, value: int,
             suffix: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    if suffix:
        spin.setSuffix(suffix)
    return spin


def row(*widgets: QWidget) -> QWidget:
    """Lay several widgets out horizontally inside one container."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def caveat_text(caveats: "tuple[Caveat, ...] | list[Caveat]") -> str:
    """Caveats as a bulleted block for an assumptions box.

    Returns a sentence rather than an empty string when there are none, because a
    blank assumptions panel reads as "no assumptions" and that is never true.
    """
    if not caveats:
        return (
            "No caveats are attached to this result. That means the values are "
            "geometric measurements rather than predictions -- it does not mean a "
            "prediction has been validated."
        )
    return "\n".join(f"- {c.message}" for c in caveats)
