"""The persistent workflow indicator.

A chip per step, coloured by its assessed status, above the workspaces. It answers
the three questions the old tab bar could not: what the steps are, which one has a
problem, and what to do about it.

Every chip is clickable, because the brief's requirement that users be able to return
to earlier steps is only real if there is something to click. Clicking emits the step;
the window decides which workspace that means.

The bar renders a :class:`~barnes_ui.gui.workflow.Workflow` and holds no state of its
own beyond the last one it was given. It cannot mark a step Complete -- only
``workflow.assess`` can, and only from facts.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..workflow import StepStatus, Workflow, WorkflowStep
from ._common import status_colour

__all__ = ["WorkflowBar"]


class WorkflowBar(QWidget):
    """Shows where the project is in the workflow, and what is next."""

    step_selected = Signal(object)  # WorkflowStep

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workflow: Workflow | None = None
        self._chips: dict[WorkflowStep, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        chips = QHBoxLayout()
        chips.setSpacing(4)
        for index, step in enumerate(WorkflowStep):
            if index:
                arrow = QLabel("›")       # single right-pointing angle quote
                arrow.setStyleSheet("color: #5A6069;")
                chips.addWidget(arrow)
            button = QPushButton(step.label)
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, s=step: self.step_selected.emit(s)
            )
            self._chips[step] = button
            chips.addWidget(button)
        chips.addStretch(1)
        layout.addLayout(chips)

        # The single most useful line in the window: what is stopping the next
        # operation, and what to do. Wrapped, because these are sentences.
        self._next_action = QLabel()
        self._next_action.setWordWrap(True)
        layout.addWidget(self._next_action)

        self.set_workflow(None)

    # -- rendering -------------------------------------------------------------

    def set_workflow(self, workflow: Workflow | None) -> None:
        self._workflow = workflow

        if workflow is None:
            for step, button in self._chips.items():
                self._paint(button, StepStatus.NOT_STARTED)
                button.setToolTip(step.purpose)
            self._next_action.setText("Open a CAD file to begin.")
            self._next_action.setStyleSheet("color: #9AA3AD;")
            return

        for state in workflow:
            button = self._chips[state.step]
            self._paint(button, state.status)
            button.setToolTip(f"{state.step.purpose}\n\n{state.summary()}")

        self._show_next(workflow)

    def _show_next(self, workflow: Workflow) -> None:
        pending = workflow.first_needing_attention()
        if pending is None:
            self._next_action.setText(
                "Every step is complete for the inputs on screen. That is not a "
                "statement about the design being right -- nothing here is "
                "experimentally validated."
            )
            self._next_action.setStyleSheet("color: #7FB069;")
            return

        text = f"{pending.label} - {pending.status.label}. {pending.detail}"
        if pending.next_action:
            text += f"\nNext: {pending.next_action}"
        self._next_action.setText(text)
        self._next_action.setStyleSheet(f"color: {status_colour(pending.status)};")

    @staticmethod
    def _paint(button: QPushButton, status: StepStatus) -> None:
        colour = status_colour(status)
        weight = "bold" if status is not StepStatus.NOT_STARTED else "normal"
        button.setStyleSheet(
            f"QPushButton {{ color: {colour}; font-weight: {weight}; "
            f"border: 1px solid {colour}; border-radius: 3px; padding: 3px 10px; }}"
            f"QPushButton:hover {{ background: {colour}; color: #15181C; }}"
        )

    # -- observation, for tests and the status bar ------------------------------

    @property
    def workflow(self) -> Workflow | None:
        return self._workflow

    def chip_for(self, step: WorkflowStep) -> QPushButton:
        return self._chips[step]

    def next_action_text(self) -> str:
        return self._next_action.text()
