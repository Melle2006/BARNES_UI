"""How far a conclusion moves when the material is not what we assumed.

Phase 7 criterion 4: sensitivity analysis reports how much the optimum shifts under
stated material uncertainty.

The finding this module exists to make quantitative
----------------------------------------------------

Both the reduced-order beam model and a small-strain FEA are **linear in the elastic
modulus**. A modulus uncertainty therefore multiplies every design's stiffness by the
same factor, and cancels out of any comparison between designs. The ranking is
invariant; the absolute values are not.

That is worth stating precisely because it decides what this tool can be used for
today. The material is uncalibrated and will stay uncalibrated until a specimen is
tested -- item 7 of docs/06-required-inputs.md -- and yet design selection is
available *now*, because selection depends on the ranking and the ranking does not
depend on the modulus.

:func:`modulus_sensitivity` establishes it by running the search at the low, nominal
and high ends of a stated modulus range and comparing the resulting optima, rather
than asserting it from the algebra. If a future objective breaks the linearity -- a
strain-limited objective with a fixed allowable, say, or anything hyperelastic at
large strain -- the invariance stops holding and this function reports that it has.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from ..provenance import Caveat
from .objectives import Evaluation, Objective, OptimisationError
from .pareto import ParetoFront, pareto_front

logger = logging.getLogger(__name__)

__all__ = [
    "MaterialRange",
    "SensitivityCase",
    "SensitivityReport",
    "modulus_sensitivity",
    "CAVEAT_UNCALIBRATED_RANGE",
]


CAVEAT_UNCALIBRATED_RANGE = Caveat(
    "uncalibrated_modulus_range",
    "The modulus range used for this sensitivity study is itself an assumption. It "
    "describes how much the answer moves across a range somebody chose, not how "
    "uncertain the real material is.",
)


@dataclass(frozen=True)
class MaterialRange:
    """A stated range for the elastic modulus, in MPa.

    There is no default. Phase 7's criterion is about *stated* uncertainty, and a
    default range would be a number nobody stated.
    """

    low: float
    nominal: float
    high: float
    source: str = ""

    def __post_init__(self) -> None:
        if not (self.low < self.nominal < self.high):
            raise OptimisationError(
                f"A modulus range must satisfy low < nominal < high; got "
                f"{self.low}, {self.nominal}, {self.high}."
            )
        if self.low <= 0.0:
            raise OptimisationError("Modulus must be positive.")
        if not self.source.strip():
            raise OptimisationError(
                "A modulus range needs a stated source -- a datasheet, a supplier "
                "range, a guess written down as one. An unattributed range turns "
                "into a fact the moment it is plotted."
            )

    @property
    def values(self) -> tuple[float, float, float]:
        return (self.low, self.nominal, self.high)

    @property
    def spread(self) -> float:
        """Half-width as a fraction of nominal."""
        return (self.high - self.low) / (2.0 * self.nominal)

    def describe(self) -> str:
        return (
            f"{self.nominal:g} MPa, range {self.low:g} to {self.high:g} "
            f"({self.spread * 100:.0f} % either way). Source: {self.source}"
        )


@dataclass
class SensitivityCase:
    """The search re-run at one modulus."""

    modulus: float
    front: ParetoFront

    @property
    def member_names(self) -> tuple[str, ...]:
        return tuple(sorted(m.design.named() for m in self.front.members))


@dataclass
class SensitivityReport:
    """What changed, and what did not, across the modulus range."""

    material_range: MaterialRange
    cases: list[SensitivityCase] = field(default_factory=list)
    objectives: tuple[Objective, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def nominal_case(self) -> SensitivityCase:
        for case in self.cases:
            if case.modulus == self.material_range.nominal:
                return case
        raise OptimisationError("The nominal case was not run.")

    @property
    def front_is_invariant(self) -> bool:
        """Whether the same designs are non-dominated at every modulus.

        The headline. True means design selection is available despite the material
        being uncalibrated.
        """
        if not self.cases:
            return False
        reference = self.cases[0].member_names
        return all(case.member_names == reference for case in self.cases)

    def optimum_shift(self) -> dict[str, float]:
        """For each objective, the spread of the nominal optimum's value.

        Reported as a fraction of the nominal value. For an objective that is linear
        in the modulus this comes out equal to the modulus spread; for a purely
        geometric objective it comes out zero. Both are useful to see side by side,
        because the contrast is the finding.
        """
        shifts: dict[str, float] = {}
        if not self.cases:
            return shifts

        nominal_design = None
        try:
            nominal_design = self.nominal_case.front.members[0].design.named()
        except (OptimisationError, IndexError):
            return shifts

        for objective in self.objectives:
            values = []
            for case in self.cases:
                for member in case.front.members:
                    if member.design.named() == nominal_design:
                        values.append(member.value(objective.name))
                        break
            if len(values) < 2:
                continue
            reference = abs(float(np.mean(values)))
            if reference <= 0.0:
                shifts[objective.name] = 0.0
            else:
                shifts[objective.name] = float(
                    (max(values) - min(values)) / (2.0 * reference)
                )
        return shifts

    def summary(self) -> str:
        lines = [
            f"Sensitivity to the elastic modulus: {self.material_range.describe()}",
            f"  {len(self.cases)} case(s) run.",
        ]
        if self.front_is_invariant:
            lines.append(
                "  The Pareto front is IDENTICAL at every modulus in the range, so "
                "design selection does not depend on the material being calibrated. "
                "Absolute values do."
            )
        else:
            lines.append(
                "  The Pareto front CHANGES across the modulus range, so design "
                "selection here is not safe until the material is characterised. "
                "This happens when an objective is not linear in the modulus -- a "
                "fixed strain or force allowable, typically."
            )
        for name, shift in self.optimum_shift().items():
            lines.append(
                f"  {name}: the chosen design's value moves "
                f"{shift * 100:.1f} % across the range"
            )
        for note in self.notes:
            lines.append(f"  note: {note}")
        lines.append(f"  caveat: {CAVEAT_UNCALIBRATED_RANGE.message}")
        return "\n".join(lines)


def modulus_sensitivity(
    search: Callable[[float], Sequence[Evaluation]],
    objectives: Sequence[Objective],
    material_range: MaterialRange,
    extra_moduli: Sequence[float] = (),
) -> SensitivityReport:
    """Re-run a search at several moduli and compare the fronts.

    ``search(modulus)`` returns the evaluations for that modulus. Keeping the search
    behind a callable means this works identically whether the stiffness comes from
    the reduced-order model, a fitted joint spring or a table of FEA results -- and
    it means this module never has to know which, so it cannot quietly assume
    linearity on behalf of a model that does not have it.
    """
    if not objectives:
        raise OptimisationError("Sensitivity analysis needs objectives.")

    moduli = list(material_range.values) + [float(m) for m in extra_moduli]
    report = SensitivityReport(
        material_range=material_range, objectives=tuple(objectives)
    )
    for modulus in sorted(set(moduli)):
        evaluations = list(search(modulus))
        if not evaluations:
            raise OptimisationError(
                f"The search returned nothing at {modulus} MPa."
            )
        report.cases.append(
            SensitivityCase(
                modulus=float(modulus),
                front=pareto_front(evaluations, objectives),
            )
        )

    if not report.front_is_invariant:
        report.notes.append(
            "Design ranking is modulus-dependent in this study. Check which "
            "objective breaks the linearity before trusting any selection."
        )
    return report
