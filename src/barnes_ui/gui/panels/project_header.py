"""The application and project header.

Four facts, always on screen: which application and version, which project, which
design is active, and whether there is work that has not been written to the project.

The last of those is the one worth arguing for. This application copies imported CAD
into a project directory so that the project is self-contained, but geometry generated
from parameters and every analysis result live only in memory until they are added. A
window that looks the same either way invites closing it.

The header states what it knows and nothing more: with no project open it says so
rather than inventing a name, and the design label reads "unsaved" rather than
borrowing the file name, because an unnamed design is exactly what this build has --
named variants are not implemented.

A note on colour, because the first version of this widget got it wrong in a way the
test suite could not see. It set ``background: #22262C`` on itself with pale text on
the labels, which is fine on a dark desktop and unreadable on a light one -- and
since a Qt stylesheet's ``background`` is inherited by child widgets but the parent
paints nothing itself, what actually appeared was three dark boxes floating on a
light window rather than a bar. So nothing here sets a background except the UNSAVED
badge, which sets its foreground in the same rule and is therefore legible under any
palette. Everything else colours text only, and inherits the theme.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

__all__ = ["ProjectHeader"]

_NO_PROJECT = "No project - File > New project to keep work together"


class ProjectHeader(QWidget):
    """Application, project, active design, and the unsaved marker."""

    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._version = version

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(14)

        title = QLabel(f"Barnes UI {version}")
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        layout.addWidget(self._divider())

        self._project = QLabel()
        self._project.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._project)

        layout.addWidget(self._divider())

        self._design = QLabel()
        layout.addWidget(self._design)

        layout.addStretch(1)

        self._dirty = QLabel()
        layout.addWidget(self._dirty)

        self.set_project(None)
        self.set_design(None)
        self.set_dirty(False)

    @staticmethod
    def _divider() -> QLabel:
        """A faint separator between header fields, instead of a coloured bar."""
        label = QLabel("·")
        label.setStyleSheet("color: #9AA3AD;")
        return label

    # -- state -----------------------------------------------------------------

    def set_project(self, name: str | None) -> None:
        if name:
            self._project.setText(f"Project: {name}")
            # No colour: a known project is ordinary text in whatever the theme's
            # foreground is, which is readable by definition.
            self._project.setStyleSheet("")
        else:
            self._project.setText(_NO_PROJECT)
            self._project.setStyleSheet("color: #9AA3AD;")

    def set_design(self, label: str | None) -> None:
        """Name the geometry on screen, and say where it came from.

        ``None`` means nothing is displayed, which is different from something
        displayed under no name.
        """
        if label:
            self._design.setText(f"Design: {label}")
            self._design.setStyleSheet("")
        else:
            self._design.setText("Design: nothing loaded")
            self._design.setStyleSheet("color: #9AA3AD;")

    def set_dirty(self, dirty: bool, detail: str | None = None) -> None:
        if dirty:
            self._dirty.setText("UNSAVED")
            self._dirty.setToolTip(
                detail
                or "There is geometry or a result in memory that is not in the "
                "project. Use File > Add current model to project."
            )
            self._dirty.setStyleSheet(
                "background: #E8A33D; color: #15181C; font-weight: bold; "
                "padding: 2px 8px; border-radius: 3px;"
            )
        else:
            self._dirty.setText("")
            self._dirty.setToolTip("")
            self._dirty.setStyleSheet("")

    # -- observation, for tests -------------------------------------------------

    def project_text(self) -> str:
        return self._project.text()

    def design_text(self) -> str:
        return self._design.text()

    def dirty_text(self) -> str:
        return self._dirty.text()
