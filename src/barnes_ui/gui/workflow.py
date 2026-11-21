"""The workflow the application is organised around, and where the user is in it.

The old interface exposed Geometry, Flexure, Template, FEA, Simulate and Optimise as
six peer tabs. That is the module layout, not a workflow: it asks the user to
understand how the code is arranged before they can understand what to do, and it has
no way of saying that step four cannot be attempted because step one is unfinished.

This module defines the workflow instead -- six steps across four workspaces -- and
derives each step's state from facts about the project. Nothing here reads a widget,
and nothing here is a label a panel decided to show. ``assess`` is a pure function
from :class:`WorkflowFacts` to a :class:`Workflow`, which means the one thing that
would hollow out a progress indicator -- a step that reports Complete because the user
navigated past it -- is not expressible.

Two conventions it keeps to:

**A step is never Complete on the strength of an attempt.** Analysis is Complete when a
result exists *and* nothing it depends on has changed since. The moment an input moves,
the same facts produce Needs attention and name what changed.

**A capability that does not exist is a limitation, not a blocker.** ``limitation`` on
a step says what this build cannot do at all -- named design variants, a joint axis
read from a STEP file -- separately from ``next_action``, which is what the user can do
now. Conflating them would either promise a feature or hide a gap.

No Qt and no VTK, so the whole of it is testable headless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "StepStatus",
    "Workflow",
    "WorkflowFacts",
    "WorkflowStep",
    "Workspace",
    "StepState",
    "assess",
]


class Workspace(Enum):
    """A place in the application, named after the user's task.

    Four rather than three: the brief's Design, Analyse and Compare, plus Inspect,
    which keeps the full CAD inspection and the lower-level engineering controls
    reachable. Dropping those because they are not on the happy path would remove
    working functionality -- the Geometry panel is how a questionable import gets
    diagnosed.
    """

    DESIGN = (
        "Design",
        "Import a part or generate a flexure from parameters, check its dimensions "
        "and validity, and define the joint axis.",
    )
    ANALYSE = (
        "Analyse",
        "Choose the material, the loading and the mesh, check readiness, and run "
        "the reduced-order model or CalculiX.",
    )
    COMPARE = (
        "Compare",
        "Sweep parameters, compare the candidates and read the trade-offs.",
    )
    INSPECT = (
        "Inspect",
        "The whole imported model: bodies, measured properties, units, validity and "
        "warnings, plus the solver capability registry.",
    )

    def __init__(self, label: str, blurb: str) -> None:
        self.label = label
        self.blurb = blurb


class StepStatus(Enum):
    """How a step is doing.

    ``BLOCKED`` and ``NEEDS_ATTENTION`` are different on purpose. Blocked means an
    earlier step has to happen first and there is nothing to do here yet. Needs
    attention means this step is where the problem is.
    """

    NOT_STARTED = "not-started"
    IN_PROGRESS = "in-progress"
    COMPLETE = "complete"
    NEEDS_ATTENTION = "needs-attention"
    BLOCKED = "blocked"

    @property
    def label(self) -> str:
        return {
            "not-started": "Not started",
            "in-progress": "In progress",
            "complete": "Complete",
            "needs-attention": "Needs attention",
            "blocked": "Blocked",
        }[self.value]

    @property
    def is_actionable(self) -> bool:
        """Whether the user can do something about this step right now."""
        return self in (
            StepStatus.NOT_STARTED,
            StepStatus.IN_PROGRESS,
            StepStatus.NEEDS_ATTENTION,
        )


class WorkflowStep(Enum):
    """The steps, in the order the primary loop takes them."""

    GEOMETRY = (
        "Geometry",
        Workspace.DESIGN,
        "Get a valid, exact solid in front of you -- imported, or generated from "
        "parameters.",
    )
    PARAMETERS = (
        "Parameters",
        Workspace.DESIGN,
        "Choose a flexure family and the dimensions that define it, then generate "
        "the CAD.",
    )
    JOINT_AXIS = (
        "Joint axis",
        Workspace.DESIGN,
        "State where the joint rotates. Every reported torque depends on it.",
    )
    READINESS = (
        "Readiness",
        Workspace.ANALYSE,
        "Confirm the prerequisites an analysis needs before it is submitted.",
    )
    ANALYSIS = (
        "Analysis",
        Workspace.ANALYSE,
        "Run the reduced-order model or a CalculiX solve, and read the result with "
        "its provenance.",
    )
    COMPARISON = (
        "Comparison",
        Workspace.COMPARE,
        "Put candidate designs beside each other and find the trade-off.",
    )

    def __init__(self, label: str, workspace: Workspace, purpose: str) -> None:
        self.label = label
        self.workspace = workspace
        self.purpose = purpose


@dataclass(frozen=True)
class WorkflowFacts:
    """Everything the workflow is derived from.

    Plain data, assembled by the window from the model, the panels and the selection
    controller. Every field is something that is either true or measured -- there is
    deliberately no field meaning "the user has visited this panel".
    """

    # -- geometry
    has_model: bool = False
    model_name: str | None = None
    model_is_exact: bool = True
    analysis_ready: bool = False
    readiness_reasons: tuple[str, ...] = ()

    #: True when the displayed solid came from the parametric generator rather than
    #: from an import. The distinction decides whether the Parameters step applies at
    #: all. It does not change when a parameter is edited -- where the solid came
    #: from is history.
    geometry_is_generated: bool = False

    #: True when the parameters on screen are the ones the displayed solid was built
    #: from. Separate from ``geometry_is_generated`` because the two answer different
    #: questions, and one field answering both is what made an edited parameter look
    #: like an imported part.
    parameters_match_geometry: bool = False

    #: Set when a generated solid failed its own volume check against the exact value
    #: its parameters imply. The solid is still displayed -- looking at it is how you
    #: work out what went wrong -- but it must not be analysed, and a modal dialog
    #: that has been dismissed is no longer saying so.
    generation_warning: str | None = None

    # -- parametric design
    #
    # Defaults to True because the parameter panel ships with a valid meander, so
    # "valid" is what a fresh application reports. Defaulting to False would make an
    # untouched project claim that its parameters are unbuildable, and the workflow
    # would point at Parameters before the user had opened anything.
    template_parameters_valid: bool = True
    #: Set when the parameters are buildable but a manufacturability check refuses
    #: them. Carries the reason, because "blocked" without one is not actionable.
    template_blocked_reason: str | None = None

    # -- joint axis
    joint_axis_confirmed: bool = False
    joint_axis_origin: tuple[float, float, float] | None = None

    # -- analysis
    solver_available: bool = False
    solver_description: str | None = None
    analysis_running: bool = False
    reduced_order_stiffness: float | None = None
    fea_stiffness: float | None = None
    fea_failure: str | None = None
    #: Why the results on screen no longer correspond to the current inputs.
    stale_reason: str | None = None

    # -- comparison
    has_base_design: bool = False
    sweep_row_count: int = 0
    #: Named, reopenable design variants. Not implemented in this build; the field
    #: exists so that the workflow does not have to change shape when it is.
    variant_count: int = 0

    @property
    def has_any_result(self) -> bool:
        return self.reduced_order_stiffness is not None or self.fea_stiffness is not None


@dataclass(frozen=True)
class StepState:
    """One step's assessed state."""

    step: WorkflowStep
    status: StepStatus
    #: Why the status is what it is. Always populated.
    detail: str
    #: What the user should do next, or None when there is nothing to do.
    next_action: str | None = None
    #: What this build cannot do at all, independent of the current state.
    limitation: str | None = None

    @property
    def label(self) -> str:
        return self.step.label

    @property
    def workspace(self) -> Workspace:
        return self.step.workspace

    def summary(self) -> str:
        """One line, for a tooltip or a status bar."""
        parts = [f"{self.label}: {self.status.label}", self.detail]
        if self.next_action:
            parts.append(f"Next: {self.next_action}")
        if self.limitation:
            parts.append(f"Limitation: {self.limitation}")
        return "\n".join(parts)


@dataclass(frozen=True)
class Workflow:
    """The assessed state of every step."""

    steps: tuple[StepState, ...] = field(default_factory=tuple)

    def state_for(self, step: WorkflowStep) -> StepState:
        for state in self.steps:
            if state.step is step:
                return state
        raise KeyError(f"{step} is not in this workflow.")

    def __getitem__(self, step: WorkflowStep) -> StepState:
        return self.state_for(step)

    def __iter__(self):
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    @property
    def is_complete(self) -> bool:
        return all(s.status is StepStatus.COMPLETE for s in self.steps)

    def statuses_of(self, status: StepStatus) -> tuple[StepState, ...]:
        return tuple(s for s in self.steps if s.status is status)

    def first_needing_attention(self) -> StepState | None:
        """The step to point the user at.

        Needs attention first, wherever it is in the order -- a problem later in the
        workflow is still a problem -- then the earliest step that is merely
        unfinished *and has something to do*. A step with no ``next_action`` is
        skipped: the Parameters step on an imported part is permanently Not started
        and permanently nothing to do, and offering it would bury the step that
        matters behind one that cannot be finished.
        """
        for state in self.steps:
            if state.status is StepStatus.NEEDS_ATTENTION:
                return state
        for state in self.steps:
            if (
                state.status in (StepStatus.NOT_STARTED, StepStatus.IN_PROGRESS)
                and state.next_action
            ):
                return state
        return None


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

_AXIS_LIMITATION = (
    "STEP carries no mates, so the joint axis cannot be read from the file. On a "
    "compliant joint there is no pin on the axis either, so cylinder detection finds "
    "the mounting bosses instead. The axis has to be stated."
)

_VARIANT_LIMITATION = (
    "Named design variants that can be saved, reopened and compared are not "
    "implemented in this build. A parameter sweep compares combinations within one "
    "run; it does not leave designs behind that you can return to."
)

_TESSELLATION_LIMITATION = (
    "Point picking works on the display tessellation, so a measured dimension carries "
    "the mesh's chord tolerance. Snapping to exact vertices and edges is not "
    "implemented."
)


def assess(facts: WorkflowFacts) -> Workflow:
    """Derive every step's state from ``facts``. Pure; no side effects."""
    return Workflow(
        steps=(
            _geometry(facts),
            _parameters(facts),
            _joint_axis(facts),
            _readiness(facts),
            _analysis(facts),
            _comparison(facts),
        )
    )


def _geometry(facts: WorkflowFacts) -> StepState:
    step = WorkflowStep.GEOMETRY
    if not facts.has_model:
        return StepState(
            step,
            StepStatus.NOT_STARTED,
            "Nothing is loaded.",
            "Open a CAD file, or set parameters in Design and generate a flexure.",
            limitation=_TESSELLATION_LIMITATION,
        )

    name = facts.model_name or "the model"

    if facts.generation_warning:
        # Ahead of the readiness check on purpose. The solid is well-formed enough
        # for OpenCASCADE to call it valid; what failed is the comparison against
        # the volume its own parameters imply, which is the stronger check.
        return StepState(
            step,
            StepStatus.NEEDS_ATTENTION,
            f"{name} was generated, but it does not match its parameters: "
            f"{facts.generation_warning}",
            "Do not analyse this solid. Change a parameter and regenerate, or "
            "inspect it to work out what the generator did.",
            limitation=_TESSELLATION_LIMITATION,
        )

    if facts.analysis_ready:
        source = "generated from parameters" if facts.geometry_is_generated else "imported"
        return StepState(
            step,
            StepStatus.COMPLETE,
            f"{name} is {source}, exact, topologically valid and ready for analysis.",
            limitation=_TESSELLATION_LIMITATION,
        )

    reasons = "\n".join(f"- {r}" for r in facts.readiness_reasons) or (
        "- The model reports that it is not ready, without giving a reason. That is "
        "itself a defect worth reporting."
    )
    action = (
        "Re-export the part as STEP."
        if not facts.model_is_exact
        else "Resolve the problems listed, then re-check."
    )
    return StepState(
        step,
        StepStatus.NEEDS_ATTENTION,
        f"{name} is loaded but not ready for analysis:\n{reasons}",
        action,
        limitation=_TESSELLATION_LIMITATION,
    )


def _parameters(facts: WorkflowFacts) -> StepState:
    step = WorkflowStep.PARAMETERS

    if facts.template_blocked_reason:
        return StepState(
            step,
            StepStatus.BLOCKED,
            facts.template_blocked_reason,
            "Change a parameter, or raise the minimum printable feature size if the "
            "printer really can resolve it.",
        )

    if not facts.template_parameters_valid:
        return StepState(
            step,
            StepStatus.NEEDS_ATTENTION,
            "The current parameters do not describe a buildable meander. The usual "
            "cause is a pitch at or below the width, which merges adjacent runs into "
            "a solid block.",
            "Adjust the parameters until they describe a valid member.",
        )

    if facts.geometry_is_generated:
        if facts.parameters_match_geometry:
            return StepState(
                step,
                StepStatus.COMPLETE,
                "The displayed solid was generated from these parameters, and its "
                "measured volume matched the exact value they imply.",
            )
        return StepState(
            step,
            StepStatus.IN_PROGRESS,
            "These parameters have changed since the solid on screen was generated, "
            "so the preview is stale: it is a picture of a different design.",
            "Press 'Build and display' to regenerate, or put the parameters back.",
        )

    if facts.has_model:
        # An imported part has no parameters. Saying so is more useful than leaving
        # the step looking unfinished for the whole of an import-driven session --
        # and ``next_action`` is None because there is genuinely nothing to do here,
        # which is what keeps the step from being offered as the next thing.
        return StepState(
            step,
            StepStatus.NOT_STARTED,
            "The displayed solid was imported, so it has no parameters: this "
            "application does not recover a parametric history from a STEP file. "
            "The parameters below describe a meander it could generate instead.",
            next_action=None,
        )

    return StepState(
        step,
        StepStatus.IN_PROGRESS,
        "The parameters describe a buildable meander, but no solid has been "
        "generated from them yet.",
        "Press 'Build and display' to generate the CAD.",
    )


def _joint_axis(facts: WorkflowFacts) -> StepState:
    step = WorkflowStep.JOINT_AXIS

    if not facts.has_model:
        return StepState(
            step,
            StepStatus.BLOCKED,
            "There is no geometry to define an axis on.",
            limitation=_AXIS_LIMITATION,
        )

    if facts.joint_axis_confirmed:
        origin = facts.joint_axis_origin
        where = (
            f" Origin ({origin[0]:.4f}, {origin[1]:.4f}, {origin[2]:.4f})."
            if origin is not None
            else ""
        )
        return StepState(
            step,
            StepStatus.COMPLETE,
            "An axis has been confirmed and written into the analysis panels."
            + where
            + " It is the midpoint of two surface picks, not a measurement of where "
            "the joint rotates -- a two-millimetre error in it changes the reported "
            "stiffness substantially.",
            limitation=_AXIS_LIMITATION,
        )

    return StepState(
        step,
        StepStatus.NOT_STARTED,
        "No joint axis has been confirmed. Nothing will use one until it is: an axis "
        "typed into the analysis panels by hand is still yours to check.",
        "In the Measure dock choose 'Joint axis from two points', pick two points "
        "either side of the joint, and press Confirm.",
        limitation=_AXIS_LIMITATION,
    )


def _readiness(facts: WorkflowFacts) -> StepState:
    step = WorkflowStep.READINESS

    if not facts.has_model:
        return StepState(
            step,
            StepStatus.BLOCKED,
            "There is nothing to analyse.",
        )

    if facts.generation_warning:
        return StepState(
            step,
            StepStatus.BLOCKED,
            "The generated solid does not match its parameters, so analysing it "
            "would answer a question about a part nobody designed.",
            "Regenerate the geometry -- see the Geometry step.",
        )

    if not facts.analysis_ready:
        reasons = "\n".join(f"- {r}" for r in facts.readiness_reasons)
        return StepState(
            step,
            StepStatus.BLOCKED,
            "The geometry is not ready, so the prerequisites cannot be met:\n"
            + reasons,
            "Fix the geometry first -- see the Geometry step.",
        )

    solver_note = (
        f"CalculiX: {facts.solver_description}."
        if facts.solver_available and facts.solver_description
        else "CalculiX: available."
        if facts.solver_available
        else "CalculiX was not found, so only the reduced-order model can be run."
    )
    solver_limitation = (
        None
        if facts.solver_available
        else "CalculiX is a separate native executable and is not installed. FEA is "
        "unavailable, and the reduced-order model is not substituted for it."
    )

    if not facts.joint_axis_confirmed:
        # Blocked rather than Needs attention, and the distinction matters for where
        # the user is sent. Readiness is a gate, not a task: there is nothing to do
        # *here*, and the thing to do is the Joint axis step in Design. Reporting
        # Needs attention made this step outrank the step that actually fixes it, so
        # the workflow bar pointed at Analyse to solve a Design problem.
        return StepState(
            step,
            StepStatus.BLOCKED,
            "The geometry is ready, but no joint axis has been confirmed. "
            + solver_note,
            "Confirm a joint axis in Design -- see the Joint axis step.",
            limitation=solver_limitation,
        )

    return StepState(
        step,
        StepStatus.COMPLETE,
        "Geometry ready, joint axis confirmed. " + solver_note,
        limitation=solver_limitation,
    )


def _analysis(facts: WorkflowFacts) -> StepState:
    step = WorkflowStep.ANALYSIS

    material_note = (
        "The material is a provisional modulus, not calibrated TPU, so every absolute "
        "torque is an assumption and only the ranking between designs is sound."
    )

    if not facts.has_model or not facts.analysis_ready or facts.generation_warning:
        return StepState(
            step,
            StepStatus.BLOCKED,
            "Readiness is not met, so no analysis can be submitted.",
            "See the Readiness step.",
            limitation=material_note,
        )

    if facts.analysis_running:
        return StepState(
            step,
            StepStatus.IN_PROGRESS,
            "An analysis is running. Its progress and diagnostics are in the Analyse "
            "workspace.",
            "Wait, or cancel it.",
            limitation=material_note,
        )

    if facts.fea_failure:
        return StepState(
            step,
            StepStatus.NEEDS_ATTENTION,
            f"The last solve produced no usable result: {facts.fea_failure}",
            "Read the diagnostics, change the setup, and resubmit. A failed solve is "
            "not a zero-stiffness design.",
            limitation=material_note,
        )

    if facts.stale_reason:
        return StepState(
            step,
            StepStatus.NEEDS_ATTENTION,
            "The results on screen are out of date: " + facts.stale_reason,
            "Re-run the analysis. The previous result is kept, but it is not a "
            "result for the current inputs.",
            limitation=material_note,
        )

    if facts.has_any_result:
        which = []
        if facts.reduced_order_stiffness is not None:
            which.append(
                f"reduced-order {facts.reduced_order_stiffness:.6g} N.mm/rad"
            )
        if facts.fea_stiffness is not None:
            which.append(f"CalculiX {facts.fea_stiffness:.6g} N.mm/rad")
        return StepState(
            step,
            StepStatus.COMPLETE,
            "Current for the inputs on screen: " + ", ".join(which) + ".",
            limitation=material_note,
        )

    return StepState(
        step,
        StepStatus.NOT_STARTED,
        "No analysis has been run against this geometry.",
        "Run the reduced-order model for a ranking, or CalculiX for a number."
        if facts.solver_available
        else "Run the reduced-order model. CalculiX was not found, so FEA is "
        "unavailable.",
        limitation=material_note,
    )


def _comparison(facts: WorkflowFacts) -> StepState:
    step = WorkflowStep.COMPARISON

    if not facts.has_base_design:
        return StepState(
            step,
            StepStatus.BLOCKED,
            "A sweep varies parameters around a base design, and there is no base "
            "design: one is set when a flexure is generated from parameters.",
            "Generate a flexure in Design first.",
            limitation=_VARIANT_LIMITATION,
        )

    if facts.sweep_row_count > 0:
        return StepState(
            step,
            StepStatus.COMPLETE,
            f"{facts.sweep_row_count} candidate designs evaluated, with the "
            "non-dominated set identified. Where the objectives conflict no winner "
            "is named, because that choice is a trade-off and not a calculation.",
            limitation=_VARIANT_LIMITATION,
        )

    return StepState(
        step,
        StepStatus.NOT_STARTED,
        "No candidates have been compared.",
        "Choose a sweep axis and a range in Compare, then run the sweep.",
        limitation=_VARIANT_LIMITATION,
    )
