"""Design points, objectives and the validity gate.

Phase 7 criterion 2 says optimisation must *refuse to run* on a model that has not
passed its validity checks. :func:`evaluate_design` is where that happens: a design
with a blocking safety issue is evaluated into an :class:`Evaluation` marked invalid,
and :func:`require_valid` raises on it. Nothing downstream -- sweep, Pareto front,
sensitivity -- accepts an invalid evaluation.

The reason it is a refusal rather than a penalty is that a penalised objective still
returns a number, and an optimiser handed a number will happily report a design with a
0.15 mm wall as "third best". There is no third best. The design does not exist.

Objectives carry a direction and a unit
---------------------------------------

An objective without a direction is ambiguous -- is a high peak strain good? -- and
one without a unit cannot be plotted honestly beside another. Both are required, and
the evaluation returns a :class:`~barnes_ui.core.provenance.TaggedValue`, so a sweep
of four hundred points still knows that every one of them rests on an uncalibrated
modulus.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Sequence

from ..flexure.adaptation import (
    SafetyIssue,
    manufacturability_issues,
    required_peak_strain,
)
from ..flexure.templates.meander import MeanderParameters
from ..provenance import Caveat, Provenance, TaggedValue, combine_provenance

logger = logging.getLogger(__name__)

__all__ = [
    "Direction",
    "DesignPoint",
    "Objective",
    "Evaluation",
    "OptimisationError",
    "InvalidDesignError",
    "evaluate_design",
    "require_valid",
    "peak_strain",
    "material_volume",
    "minimum_feature",
    "centreline_length",
    "stiffness_from",
    "STANDARD_OBJECTIVES",
]


class OptimisationError(ValueError):
    """A search that cannot be set up or run as asked."""


class InvalidDesignError(OptimisationError):
    """A design that failed its validity checks and must not be optimised over."""


class Direction(Enum):
    """Whether more of an objective is better or worse."""

    MINIMISE = "minimise"
    MAXIMISE = "maximise"

    @property
    def sign(self) -> float:
        """+1 when smaller is better, so that every objective can be minimised."""
        return 1.0 if self is Direction.MINIMISE else -1.0


@dataclass(frozen=True)
class DesignPoint:
    """One candidate design: a parameter set and a name for it."""

    parameters: MeanderParameters
    label: str = ""

    def named(self) -> str:
        if self.label:
            return self.label
        p = self.parameters
        return (
            f"n{p.n_runs}_L{p.run_length:g}_p{p.pitch:g}_w{p.width:g}_"
            f"t{p.thickness:g}"
        )

    def with_values(self, **changes: float) -> "DesignPoint":
        return DesignPoint(
            parameters=replace(self.parameters, **changes), label=""
        )


@dataclass(frozen=True)
class Objective:
    """A quantity to be pushed in a stated direction."""

    name: str
    unit: str
    direction: Direction
    evaluate: Callable[[DesignPoint], TaggedValue]
    description: str = ""

    def score(self, design: DesignPoint) -> TaggedValue:
        return self.evaluate(design)


@dataclass
class Evaluation:
    """What every objective said about one design, and whether it is admissible."""

    design: DesignPoint
    values: dict[str, TaggedValue] = field(default_factory=dict)
    issues: list[SafetyIssue] = field(default_factory=list)

    @property
    def blocking_issues(self) -> list[SafetyIssue]:
        return [i for i in self.issues if i.blocking]

    @property
    def is_valid(self) -> bool:
        return not self.blocking_issues

    @property
    def provenance(self) -> Provenance:
        """The weakest tag among the objective values.

        A design is only as trustworthy as its least trustworthy objective, and in
        practice that is whichever one touches the material.
        """
        if not self.values:
            raise OptimisationError(
                f"{self.design.named()} has no objective values to combine."
            )
        tag, _ = combine_provenance(list(self.values.values()))
        return tag

    @property
    def caveats(self) -> tuple[Caveat, ...]:
        if not self.values:
            return ()
        _, caveats = combine_provenance(list(self.values.values()))
        return caveats

    def value(self, objective: str) -> float:
        try:
            return self.values[objective].value
        except KeyError as exc:
            raise OptimisationError(
                f"{self.design.named()} was not evaluated for objective "
                f"{objective!r}. Evaluated: {sorted(self.values)}"
            ) from exc

    def as_row(self) -> dict[str, object]:
        row: dict[str, object] = {"design": self.design.named()}
        p = self.design.parameters
        row.update({
            "run_length": p.run_length, "n_runs": p.n_runs, "pitch": p.pitch,
            "width": p.width, "thickness": p.thickness,
        })
        row.update({name: value.value for name, value in self.values.items()})
        row["valid"] = self.is_valid
        row["provenance"] = self.provenance.label if self.values else ""
        return row


def evaluate_design(
    design: DesignPoint,
    objectives: Sequence[Objective],
    minimum_feature_size: float = 0.4,
    extra_checks: Sequence[Callable[[DesignPoint], Sequence[SafetyIssue]]] = (),
) -> Evaluation:
    """Score one design and record whether it is admissible.

    Validity is assessed first and the objectives are evaluated anyway, because the
    numbers are informative when diagnosing *why* a region of the design space is
    inadmissible. What the invalid flag prevents is the design taking part in a
    ranking, not the numbers being looked at.
    """
    evaluation = Evaluation(design=design)
    evaluation.issues.extend(
        manufacturability_issues(design.parameters, minimum_feature_size)
    )
    for check in extra_checks:
        evaluation.issues.extend(check(design))

    for objective in objectives:
        evaluation.values[objective.name] = objective.score(design)
    return evaluation


def require_valid(evaluation: Evaluation) -> Evaluation:
    """Return the evaluation, or raise naming every blocking issue.

    Phase 7 criterion 2.
    """
    if evaluation.is_valid:
        return evaluation
    reasons = "; ".join(i.message for i in evaluation.blocking_issues)
    raise InvalidDesignError(
        f"{evaluation.design.named()} failed its validity checks and will not be "
        f"optimised over: {reasons} A design that cannot be made has no ranking."
    )


# ----------------------------------------------------------- built-in objectives


def peak_strain(joint_angle: float = math.radians(100.0)) -> Objective:
    """Peak bending strain at a target joint angle, to be minimised.

    An ``ANALYTICAL_ESTIMATE`` from a uniform-curvature assumption, which understates
    the true peak. Usable for ranking designs against each other, where the same
    assumption applies to all of them; not usable as a strain prediction.
    """
    return Objective(
        name="peak_strain",
        unit="",
        direction=Direction.MINIMISE,
        evaluate=lambda d: required_peak_strain(d.parameters, joint_angle),
        description=(
            f"Uniform-curvature peak bending strain at "
            f"{math.degrees(joint_angle):.0f} deg."
        ),
    )


def material_volume() -> Objective:
    """Solid volume, to be minimised: print time and material cost.

    Exact, from the template's closed form, so it is a geometric measurement rather
    than a prediction.
    """
    return Objective(
        name="material_volume",
        unit="mm^3",
        direction=Direction.MINIMISE,
        evaluate=lambda d: TaggedValue(
            d.parameters.expected_volume, "mm^3",
            Provenance.GEOMETRIC_MEASUREMENT,
            label=f"{d.named()} volume",
        ),
        description="Solid volume from the template's exact closed form.",
    )


def minimum_feature() -> Objective:
    """Smallest printable feature, to be maximised: manufacturing margin."""
    return Objective(
        name="minimum_feature",
        unit="mm",
        direction=Direction.MAXIMISE,
        evaluate=lambda d: TaggedValue(
            d.parameters.minimum_feature_size, "mm",
            Provenance.GEOMETRIC_MEASUREMENT,
            label=f"{d.named()} smallest feature",
        ),
        description="Lesser of strap width and inner turn radius.",
    )


def centreline_length() -> Objective:
    """Centreline arc length, to be maximised: more length is more compliance."""
    return Objective(
        name="centreline_length",
        unit="mm",
        direction=Direction.MAXIMISE,
        evaluate=lambda d: TaggedValue(
            d.parameters.centreline_length, "mm",
            Provenance.GEOMETRIC_MEASUREMENT,
            label=f"{d.named()} centreline",
        ),
        description="Exact centreline arc length from the template.",
    )


def stiffness_from(
    evaluator: Callable[[MeanderParameters], TaggedValue],
    direction: Direction = Direction.MINIMISE,
    name: str = "rotational_stiffness",
) -> Objective:
    """Rotational stiffness from a caller-supplied model.

    Deliberately not implemented here. Whether the stiffness comes from the
    reduced-order beam model, from a fitted joint spring or from an FEA run is the
    single most consequential choice in the whole search -- the three differ by 24 per
    cent on the A3 flexure -- and burying it inside an objective factory would hide
    it. The caller passes the evaluator and the resulting value's provenance says
    which one was used.
    """
    return Objective(
        name=name,
        unit="N.mm/rad",
        direction=direction,
        evaluate=lambda d: evaluator(d.parameters),
        description="Rotational stiffness from a caller-supplied model.",
    )


#: The objectives that need no model: pure geometry, all exactly known.
STANDARD_OBJECTIVES: tuple[Objective, ...] = (
    material_volume(),
    minimum_feature(),
    centreline_length(),
)
