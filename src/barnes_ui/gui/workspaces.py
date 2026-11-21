"""Workspace navigation.

Four workspaces named after what the user is doing, replacing six tabs named after
the modules the code is arranged into. A selector row, a one-sentence statement of
what the current workspace is for, and a stack of pages.

The pages are built by the window, because the window owns the panels and this widget
should not know that a flexure exists. What it owns is the navigation: which workspace
is current, how to get to another one, and keeping the selector in step with the stack
so the highlighted button is always the page on screen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .workflow import Workspace

__all__ = ["WorkspaceNavigator"]


class WorkspaceNavigator(QWidget):
    """A selector over a stack of workspace pages."""

    workspace_changed = Signal(object)  # Workspace

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._buttons: dict[Workspace, QPushButton] = {}
        self._pages: dict[Workspace, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        selector = QHBoxLayout()
        selector.setSpacing(2)
        # Exclusive, so the selector can never show two workspaces as current.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for workspace in Workspace:
            button = QPushButton(workspace.label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(workspace.blurb)
            button.clicked.connect(
                lambda _checked=False, w=workspace: self.set_current(w)
            )
            self._group.addButton(button)
            self._buttons[workspace] = button
            selector.addWidget(button)
        selector.addStretch(1)
        layout.addLayout(selector)

        # What this workspace is for. One sentence, from the enum, so the navigation
        # and the explanation cannot disagree.
        self._blurb = QLabel()
        self._blurb.setWordWrap(True)
        self._blurb.setStyleSheet("color: #9AA3AD;")
        layout.addWidget(self._blurb)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        self._current: Workspace | None = None

    # -- construction ----------------------------------------------------------

    def add_workspace(self, workspace: Workspace, page: QWidget) -> None:
        """Register ``page`` as the content of ``workspace``.

        The first page registered becomes current, so the window does not have to
        remember to select one.
        """
        if workspace in self._pages:
            raise ValueError(f"{workspace.label} already has a page.")
        self._pages[workspace] = self._stack.addWidget(page)
        if self._current is None:
            self.set_current(workspace)

    # -- navigation ------------------------------------------------------------

    def set_current(self, workspace: Workspace) -> None:
        """Show ``workspace``. Emits ``workspace_changed`` only on a real change."""
        if workspace not in self._pages:
            raise KeyError(f"{workspace.label} has no page registered.")

        self._stack.setCurrentIndex(self._pages[workspace])
        self._blurb.setText(workspace.blurb)

        button = self._buttons[workspace]
        if not button.isChecked():
            button.setChecked(True)

        if self._current is workspace:
            return
        self._current = workspace
        self.workspace_changed.emit(workspace)

    def current(self) -> Workspace | None:
        return self._current

    # -- observation, for tests -------------------------------------------------

    def button_for(self, workspace: Workspace) -> QPushButton:
        return self._buttons[workspace]

    def page_for(self, workspace: Workspace) -> QWidget:
        return self._stack.widget(self._pages[workspace])

    def blurb_text(self) -> str:
        return self._blurb.text()

    def workspace_count(self) -> int:
        return len(self._pages)
