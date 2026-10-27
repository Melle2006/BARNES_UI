"""Pareto fronts: what to do when objectives disagree.

Phase 7 criterion 3: conflicting objectives produce a Pareto front, not a single
declared winner.

The whole content of that criterion is a refusal. It is trivial to weight several
objectives into one number and report its minimum, and doing so hides the actual
decision -- the weights -- inside a calculation that looks objective. A flexure that
is softer is also thinner, and how much manufacturing margin a given softness is worth
is not something this code can know.

So :meth:`ParetoFront.winner` raises whenever the front has more than one member, and
says what information would be needed to choose. A caller who really does want a
single answer has to supply weights explicitly, through
:meth:`ParetoFront.best_by_weights`, which records them in the result.

Dominance
---------

Design A dominates B when A is at least as good as B on every objective and strictly
better on at least one. The front is the set of designs nothing dominates. Comparison
is done on the raw objective values with the direction's sign applied, so no scaling
is involved and no scale-dependent artefacts can creep in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from ..provenance import Caveat, Provenance
from .objectives import Evaluation, Objective, OptimisationError

logger = logging.getLogger(__name__)

__all__ = ["ParetoFront", "pareto_front", "dominates"]


def dominates(
    first: Evaluation, second: Evaluation, objectives: Sequence[Objective]
) -> bool:
    """Whether ``first`` dominates ``second``."""
    at_least_as_good = True
    strictly_better = False
    for objective in objectives:
        sign = objective.direction.sign
        a = sign * first.value(objective.name)
        b = sign * second.value(objective.name)
        if a > b:
            at_least_as_good = False
            break
        if a < b:
            strictly_better = True
    return at_least_as_good and strictly_better


@dataclass
class ParetoFront:
    """The non-dominated designs, and a refusal to pick between them."""

    objectives: tuple[Objective, ...]
    members: list[Evaluation] = field(default_factory=list)
    #: Valid designs that were considered but dominated.
    dominated: int = 0
    #: Designs excluded before ranking because they failed their validity checks.
    excluded_invalid: int = 0

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def provenance(self) -> Provenance:
        if not self.members:
            raise OptimisationError("An empty front has no provenance.")
        return min(m.provenance for m in self.members)

    @property
    def caveats(self) -> tuple[Caveat, ...]:
        seen: dict[str, Caveat] = {}
        for member in self.members:
            for caveat in member.caveats:
                seen.setdefault(caveat.key, caveat)
        return tuple(seen.values())

    @property
    def objectives_conflict(self) -> bool:
        """Whether more than one design survives -- the definition of a trade-off."""
        return self.size > 1

    def winner(self) -> Evaluation:
        """The single best design, when and only when there is one.

        Raises when the front has more than one member. That is criterion 3: a
        conflicting set of objectives has no winner, and naming one would be
        smuggling a weighting in without saying so.
        """
        if not self.members:
            raise OptimisationError(
                "The Pareto front is empty: no valid design was evaluated."
            )
        if self.size > 1:
            names = ", ".join(m.design.named() for m in self.members[:5])
            more = "" if self.size <= 5 else f" and {self.size - 5} more"
            raise OptimisationError(
                f"These objectives conflict: {self.size} designs are non-dominated "
                f"({names}{more}), so there is no best one. Choosing between them "
                "requires a trade-off that is not in the objectives -- how much "
                "manufacturing margin a given softness is worth, for instance. Use "
                "best_by_weights() with weights you are prepared to write down, or "
                "add the missing objective and re-run."
            )
        return self.members[0]

    def best_by_weights(self, weights: Mapping[str, float]) -> Evaluation:
        """Pick one member using explicit weights on normalised objectives.

        Objectives are normalised across the front to [0, 1] before weighting, since
        a volume in mm^3 and a strain as a fraction are not otherwise comparable.
        Weights must be given for every objective: an omitted weight is an implicit
        zero, and an implicit zero is the kind of silent choice this module exists to
        stop.
        """
        if not self.members:
            raise OptimisationError("The Pareto front is empty.")
        missing = [o.name for o in self.objectives if o.name not in weights]
        if missing:
            raise OptimisationError(
                f"No weight given for objective(s) {', '.join(missing)}. An omitted "
                "weight is an implicit zero, which is a decision rather than an "
                "oversight -- state it."
            )
        if any(w < 0 for w in weights.values()):
            raise OptimisationError("Negative weights invert an objective's direction; "
                                    "change its Direction instead.")

        scores = np.zeros(self.size)
        for objective in self.objectives:
            raw = np.array([m.value(objective.name) for m in self.members])
            spread = float(raw.max() - raw.min())
            if spread <= 0.0:
                continue        # this objective does not discriminate on the front
            normalised = (raw - raw.min()) / spread
            if objective.direction.sign < 0:
                normalised = 1.0 - normalised
            scores += float(weights[objective.name]) * normalised

        chosen = self.members[int(np.argmin(scores))]
        logger.info(
            "Chose %s from a %d-member front using weights %s",
            chosen.design.named(), self.size, dict(weights),
        )
        return chosen

    def as_rows(self) -> list[dict[str, object]]:
        return [m.as_row() for m in self.members]

    def summary(self) -> str:
        names = ", ".join(o.name for o in self.objectives)
        lines = [
            f"Pareto front over [{names}]: {self.size} non-dominated design(s), "
            f"{self.dominated} dominated"
            + (f", {self.excluded_invalid} excluded as inadmissible"
               if self.excluded_invalid else "")
            + ".",
        ]
        if self.members:
            lines.append(f"  Weakest provenance on the front: "
                         f"{self.provenance.label}")
        if self.objectives_conflict:
            lines.append(
                "  These objectives conflict, so no single design is best. The "
                "trade-off between them is a decision, not a calculation."
            )
        for member in self.members:
            values = ", ".join(
                f"{o.name}={member.value(o.name):.6g} {o.unit}".rstrip()
                for o in self.objectives
            )
            lines.append(f"  {member.design.named()}: {values}")
        return "\n".join(lines)


def pareto_front(
    evaluations: Sequence[Evaluation], objectives: Sequence[Objective]
) -> ParetoFront:
    """Non-dominated designs among the *valid* evaluations.

    Invalid designs are excluded before ranking rather than penalised. A design with
    a sub-manufacturable wall is not a poor design; it is not a design.
    """
    if not objectives:
        raise OptimisationError("A Pareto front needs at least one objective.")

    valid = [e for e in evaluations if e.is_valid]
    front = ParetoFront(
        objectives=tuple(objectives),
        excluded_invalid=len(evaluations) - len(valid),
    )
    for candidate in valid:
        if any(dominates(other, candidate, objectives) for other in valid):
            front.dominated += 1
        else:
            front.members.append(candidate)

    # Deterministic ordering, by the first objective, so repeated runs and committed
    # outputs do not churn.
    first = objectives[0]
    front.members.sort(
        key=lambda e: first.direction.sign * e.value(first.name)
    )
    return front
