"""Comparing two flexure designs on one set of axes, with provenance visible.

Phase 5 criterion 4. The point of the criterion is not the plot; it is that two curves
on one axis invite a reader to compare their *values*, and that comparison is only
legitimate when both were produced the same way. A reduced-order curve beside an FEA
curve looks like two designs; it is actually two methods.

So :class:`DesignComparison` refuses to rank designs whose curves have different
provenance, and :meth:`DesignComparison.legend_entries` puts the tag in the legend
text rather than leaving it to a tooltip nobody hovers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
import numpy as np

from ..provenance import Caveat, Provenance, TaggedValue

__all__ = ["DesignCurve", "DesignComparison", "ComparisonError"]


class ComparisonError(ValueError):
    """A comparison that would mislead."""


@dataclass
class DesignCurve:
    """One design's torque-angle curve, with how it was obtained."""

    name: str
    angles: np.ndarray
    torques: np.ndarray
    provenance: Provenance
    caveats: tuple[Caveat, ...] = ()
    #: Free text naming the run, mesh and material. Shown under the plot.
    source: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.angles = np.asarray(self.angles, dtype=float)
        self.torques = np.asarray(self.torques, dtype=float)
        if self.angles.shape != self.torques.shape:
            raise ComparisonError(
                f"{self.name}: {self.angles.size} angles but "
                f"{self.torques.size} torques."
            )
        if self.angles.size < 2:
            raise ComparisonError(f"{self.name}: a curve needs at least two points.")

    @property
    def angles_degrees(self) -> np.ndarray:
        return np.degrees(self.angles)

    @property
    def common_range(self) -> tuple[float, float]:
        return (float(self.angles.min()), float(self.angles.max()))

    def torque_at(self, angle: float) -> float:
        """Linear interpolation within the curve's own range.

        Refuses outside it, for the same reason a fitted spring does: a curve beyond
        its data is an arbitrary number.
        """
        low, high = self.common_range
        if not low - 1e-12 <= angle <= high + 1e-12:
            raise ComparisonError(
                f"{self.name} covers {math.degrees(low):.1f} to "
                f"{math.degrees(high):.1f} deg and was asked for "
                f"{math.degrees(angle):.1f} deg."
            )
        return float(np.interp(angle, self.angles, self.torques))

    def legend_text(self) -> str:
        return f"{self.name} [{self.provenance.label}]"


@dataclass
class DesignComparison:
    """Several designs' curves, to be shown together."""

    curves: list[DesignCurve] = field(default_factory=list)
    title: str = "Design comparison"

    def add(self, curve: DesignCurve) -> None:
        if any(c.name == curve.name for c in self.curves):
            raise ComparisonError(f"Duplicate design name {curve.name!r}.")
        self.curves.append(curve)

    @property
    def provenances(self) -> set[Provenance]:
        return {c.provenance for c in self.curves}

    @property
    def is_like_for_like(self) -> bool:
        """Whether every curve was produced by the same kind of calculation."""
        return len(self.provenances) <= 1

    @property
    def overlap(self) -> tuple[float, float]:
        """Angular range all curves cover. Comparison outside it is not possible."""
        if not self.curves:
            raise ComparisonError("No curves to compare.")
        low = max(c.common_range[0] for c in self.curves)
        high = min(c.common_range[1] for c in self.curves)
        if high <= low:
            raise ComparisonError(
                "The curves do not overlap in angle, so there is no range over which "
                "to compare them."
            )
        return (low, high)

    def legend_entries(self) -> list[str]:
        """Legend text with the provenance tag baked in. Criterion 4."""
        return [c.legend_text() for c in self.curves]

    def rank_at(self, angle: float) -> list[tuple[str, float]]:
        """Designs ordered softest first at one angle.

        Raises when the curves do not share a provenance. Ranking a reduced-order
        curve against an FEA curve measures the difference between the methods at
        least as much as the difference between the designs -- on the A3 flexure that
        difference is 24 per cent, which is larger than many design changes.
        """
        if not self.is_like_for_like:
            tags = ", ".join(sorted(p.label for p in self.provenances))
            raise ComparisonError(
                f"Refusing to rank designs computed by different methods ({tags}). "
                "Plot them together if you like -- the curves are still informative "
                "-- but the ordering would be an artefact of the methods as much as "
                "of the designs."
            )
        low, high = self.overlap
        if not low - 1e-12 <= angle <= high + 1e-12:
            raise ComparisonError(
                f"{math.degrees(angle):.1f} deg is outside the range all curves "
                f"cover ({math.degrees(low):.1f} to {math.degrees(high):.1f} deg)."
            )
        scored = [(c.name, c.torque_at(angle)) for c in self.curves]
        scored.sort(key=lambda item: abs(item[1]))
        return scored

    def stiffness_ratio(self, reference: str, other: str, angle: float) -> TaggedValue:
        """``other`` torque divided by ``reference`` torque at one angle.

        Deliberately available even across provenances, because the cross-method
        ratio is itself the useful quantity -- it is how Phase 3 criterion 7 was
        reported. The returned value carries the weaker of the two tags and both
        sets of caveats, so it cannot be mistaken for a measurement.
        """
        first = self._curve(reference)
        second = self._curve(other)
        denominator = first.torque_at(angle)
        if abs(denominator) < 1.0e-15:
            raise ComparisonError(
                f"{reference} has zero torque at {math.degrees(angle):.1f} deg, so "
                "the ratio is undefined. Compare at a non-neutral angle."
            )
        return TaggedValue(
            value=second.torque_at(angle) / denominator,
            unit="",
            provenance=min(first.provenance, second.provenance),
            caveats=tuple(dict.fromkeys(first.caveats + second.caveats)),
            label=f"{other} / {reference} at {math.degrees(angle):.1f} deg",
        )

    def _curve(self, name: str) -> DesignCurve:
        for curve in self.curves:
            if curve.name == name:
                return curve
        raise ComparisonError(
            f"No design named {name!r}. Have: "
            f"{', '.join(c.name for c in self.curves)}."
        )

    def summary(self) -> str:
        lines = [self.title]
        for curve in self.curves:
            low, high = curve.common_range
            lines.append(
                f"  {curve.legend_text()}: {math.degrees(low):.1f} to "
                f"{math.degrees(high):.1f} deg, peak "
                f"{np.max(np.abs(curve.torques)):.4g} N.mm"
                + (f" -- {curve.source}" if curve.source else "")
            )
        if not self.is_like_for_like:
            lines.append(
                "  NOTE: these curves were produced by different methods, so their "
                "ordering is not purely a property of the designs."
            )
        return "\n".join(lines)
