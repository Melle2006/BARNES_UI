"""Parameter sweeps over the flexure template.

Phase 7 criterion 1 asks that a sweep reproduce results obtained for designs analysed
individually. That sounds trivial and is not: the usual way it breaks is that the
sweep path applies a default the individual path did not, or caches an evaluator
across points that was not meant to be reused. :func:`run_sweep` therefore calls
exactly the same :func:`~.objectives.evaluate_design` a single analysis would, with
the same arguments, and the test for criterion 1 compares the two paths' outputs value
for value.

Invalid points are kept, not dropped
-------------------------------------

A sweep across a width range will walk off the manufacturable end of it. Dropping
those points silently leaves a plot with a cliff at an unexplained location; keeping
them, marked invalid and excluded from every ranking, puts the boundary on the chart
where it belongs. :attr:`SweepResult.invalid` is the count, and the summary says it
out loud.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

from ..flexure.templates.meander import MeanderError, MeanderParameters
from ..provenance import Caveat, Provenance
from .objectives import (
    DesignPoint,
    Evaluation,
    Objective,
    OptimisationError,
    evaluate_design,
)

logger = logging.getLogger(__name__)

__all__ = ["SweepAxis", "SweepResult", "run_sweep", "grid_designs"]

#: Parameters a sweep may vary. Anything else is either derived (turn radius) or not
#: a parameter of the template at all, and naming it is a mistake worth catching.
SWEEPABLE = (
    "run_length", "n_runs", "pitch", "width", "thickness", "tab_length", "tab_width"
)


@dataclass(frozen=True)
class SweepAxis:
    """One parameter and the values to try."""

    parameter: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.parameter not in SWEEPABLE:
            raise OptimisationError(
                f"{self.parameter!r} is not a sweepable template parameter. "
                f"Sweepable: {', '.join(SWEEPABLE)}. Derived quantities such as the "
                "turn radius follow from these and cannot be set independently."
            )
        if not self.values:
            raise OptimisationError(f"Axis {self.parameter!r} has no values.")

    @property
    def size(self) -> int:
        return len(self.values)


@dataclass
class SweepResult:
    """Every point a sweep evaluated, valid and invalid alike."""

    axes: tuple[SweepAxis, ...]
    evaluations: list[Evaluation] = field(default_factory=list)
    #: Designs the template itself refused to build, with the reason.
    rejected: list[tuple[dict[str, float], str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def valid(self) -> list[Evaluation]:
        return [e for e in self.evaluations if e.is_valid]

    @property
    def invalid(self) -> list[Evaluation]:
        return [e for e in self.evaluations if not e.is_valid]

    @property
    def provenance(self) -> Provenance:
        """Weakest tag anywhere in the sweep.

        A sweep is a lot of numbers, and the risk a sweep carries is that volume
        reads as rigour. One tag for the whole study is the honest headline.
        """
        if not self.evaluations:
            raise OptimisationError("The sweep evaluated nothing.")
        return min(e.provenance for e in self.evaluations)

    @property
    def caveats(self) -> tuple[Caveat, ...]:
        seen: dict[str, Caveat] = {}
        for evaluation in self.evaluations:
            for caveat in evaluation.caveats:
                seen.setdefault(caveat.key, caveat)
        return tuple(seen.values())

    def best(self, objective: Objective) -> Evaluation:
        """The best *valid* point for one objective.

        Single-objective only. When objectives conflict there is no best point, and
        ParetoFront is what that situation produces.
        """
        candidates = self.valid
        if not candidates:
            raise OptimisationError(
                "Every point in this sweep failed its validity checks, so there is "
                "no best design. Widen the ranges or relax the minimum feature size "
                "-- deliberately."
            )
        return min(
            candidates,
            key=lambda e: objective.direction.sign * e.value(objective.name),
        )

    def values(self, objective: str, valid_only: bool = True) -> np.ndarray:
        source = self.valid if valid_only else self.evaluations
        return np.array([e.value(objective) for e in source])

    def as_rows(self) -> list[dict[str, object]]:
        return [e.as_row() for e in self.evaluations]

    def summary(self) -> str:
        shape = " x ".join(f"{a.parameter}({a.size})" for a in self.axes)
        lines = [
            f"Sweep {shape}: {len(self.evaluations)} points evaluated, "
            f"{len(self.valid)} valid, {len(self.invalid)} inadmissible"
            + (f", {len(self.rejected)} not buildable" if self.rejected else "")
            + ".",
        ]
        if self.evaluations:
            lines.append(f"  Weakest provenance across the sweep: "
                         f"{self.provenance.label}")
        for caveat in self.caveats:
            lines.append(f"  caveat: {caveat.message}")
        return "\n".join(lines)


def grid_designs(
    base: MeanderParameters, axes: Sequence[SweepAxis]
) -> Iterable[tuple[dict[str, float], MeanderParameters | None, str]]:
    """Yield ``(changes, parameters, error)`` for the full Cartesian product.

    ``parameters`` is ``None`` and ``error`` non-empty when the template refuses the
    combination -- a pitch below the width, say. That is not an exceptional case in a
    sweep; it is the edge of the design space, and it is reported rather than raised
    so the rest of the grid still runs.
    """
    from dataclasses import replace

    names = [axis.parameter for axis in axes]
    for combination in itertools.product(*(axis.values for axis in axes)):
        changes = {
            name: (int(value) if name == "n_runs" else float(value))
            for name, value in zip(names, combination)
        }
        try:
            yield changes, replace(base, **changes), ""
        except MeanderError as exc:
            yield changes, None, str(exc)


def run_sweep(
    base: MeanderParameters,
    axes: Sequence[SweepAxis],
    objectives: Sequence[Objective],
    minimum_feature_size: float = 0.4,
    progress: Callable[[float, str], None] | None = None,
) -> SweepResult:
    """Evaluate every combination of the given axes.

    The call into :func:`evaluate_design` is identical to the one a single analysis
    makes, which is what criterion 1 turns on.
    """
    if not axes:
        raise OptimisationError("A sweep needs at least one axis.")
    if not objectives:
        raise OptimisationError(
            "A sweep needs at least one objective. Evaluating designs against "
            "nothing produces a table that cannot be ranked."
        )
    duplicates = {a.parameter for a in axes}
    if len(duplicates) != len(axes):
        raise OptimisationError(
            "Two axes vary the same parameter, so the grid is not well defined."
        )

    result = SweepResult(axes=tuple(axes))
    total = 1
    for axis in axes:
        total *= axis.size

    for index, (changes, parameters, error) in enumerate(grid_designs(base, axes)):
        if progress:
            progress(index / max(1, total), f"Evaluating {changes}")
        if parameters is None:
            result.rejected.append((changes, error))
            continue
        label = ", ".join(f"{k}={v:g}" for k, v in changes.items())
        result.evaluations.append(
            evaluate_design(
                DesignPoint(parameters=parameters, label=label),
                objectives,
                minimum_feature_size=minimum_feature_size,
            )
        )

    if result.rejected:
        result.notes.append(
            f"{len(result.rejected)} combination(s) could not be built at all: the "
            "template refused them as geometrically impossible. They are listed in "
            "SweepResult.rejected with the reason."
        )
    if result.invalid:
        result.notes.append(
            f"{len(result.invalid)} point(s) are inadmissible on manufacturability "
            "and are excluded from every ranking. They are kept so that the edge of "
            "the feasible region appears on a plot rather than as an unexplained "
            "cliff."
        )
    return result
