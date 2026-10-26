"""Mesh-convergence studies.

A single mesh cannot tell you how far its answer is from the converged one. Running the
same problem on a sequence of refinements and watching the quantity of interest settle
is the only way to bound the discretisation error, and
``docs/05-development-plan.md`` makes it Phase 3 acceptance criterion 3.

It is also the only practical detector for element locking (risk R7). A locked mesh
converges cleanly on every increment and simply reports the part as too stiff; what it
cannot do is *settle* as the mesh refines, because the locking eases as elements shrink.
A quantity that keeps drifting with refinement is the signature.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["ConvergenceStudy", "ConvergencePoint", "run_mesh_convergence"]


@dataclass
class ConvergencePoint:
    """One mesh in a refinement sequence."""

    elements_through_thickness: int
    element_count: int
    degrees_of_freedom: int
    value: float
    element_size: float


@dataclass
class ConvergenceStudy:
    """A refinement sequence and what it says about discretisation error."""

    quantity: str
    unit: str
    points: list[ConvergencePoint] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def values(self) -> np.ndarray:
        return np.array([p.value for p in self.points])

    @property
    def relative_changes(self) -> np.ndarray:
        """Fractional change between successive meshes."""
        values = self.values
        if values.size < 2:
            return np.array([])
        return np.abs(np.diff(values)) / np.abs(values[1:])

    @property
    def final_change(self) -> float:
        """Change between the two finest meshes, as a fraction."""
        changes = self.relative_changes
        return float(changes[-1]) if changes.size else float("nan")

    def is_converged(self, tolerance: float = 0.02) -> bool:
        """Whether the two finest meshes agree within ``tolerance``.

        The default 2 per cent is Phase 3 criterion 3. It is a necessary condition, not
        a sufficient one: two coarse meshes can agree with each other and both be wrong.
        """
        changes = self.relative_changes
        return bool(changes.size and changes[-1] < tolerance)

    def is_monotonic(self) -> bool:
        """Whether the quantity moves consistently in one direction.

        Monotonic refinement is the expected behaviour and is reassuring. A value that
        oscillates suggests mesh-dependent artefacts rather than smooth convergence, and
        is worth investigating before the result is quoted.
        """
        values = self.values
        if values.size < 3:
            return True
        deltas = np.diff(values)
        return bool(np.all(deltas > 0) or np.all(deltas < 0))

    def richardson_estimate(self) -> float | None:
        """Extrapolated value from the three finest meshes, if available.

        Assumes the error falls as a power of element size and estimates the limit from
        three points. Returns ``None`` when the sequence does not support it -- a
        non-monotonic or stalled sequence gives a meaningless extrapolation, and a
        meaningless number is worse than none.
        """
        values = self.values
        if values.size < 3:
            return None
        v1, v2, v3 = values[-3], values[-2], values[-1]
        denominator = (v3 - v2) - (v2 - v1)
        if abs(denominator) < 1.0e-15:
            return None
        estimate = v3 - (v3 - v2) ** 2 / denominator
        if not np.isfinite(estimate):
            return None
        return float(estimate)

    def summary(self) -> str:
        if not self.points:
            return "No meshes were run."
        lines = [
            f"Mesh convergence of {self.quantity} [{self.unit}]:",
            f"  {'el/thk':>7}{'elements':>10}{'DOF':>10}{'value':>14}{'change':>10}",
        ]
        changes = self.relative_changes
        for index, point in enumerate(self.points):
            change = (
                f"{changes[index - 1] * 100:9.3f}%" if index > 0 and changes.size else
                f"{'-':>10}"
            )
            lines.append(
                f"  {point.elements_through_thickness:>7}{point.element_count:>10}"
                f"{point.degrees_of_freedom:>10}{point.value:>14.6g}{change}"
            )
        lines.append(
            f"  Final change between the two finest meshes: "
            f"{self.final_change * 100:.3f}%"
        )
        lines.append(f"  Monotonic: {self.is_monotonic()}")
        extrapolated = self.richardson_estimate()
        if extrapolated is not None:
            lines.append(f"  Richardson extrapolation: {extrapolated:.6g} {self.unit}")
        return "\n".join(lines)


def run_mesh_convergence(
    solve_at: Callable[[int], tuple[float, int, int, float]],
    refinements: Sequence[int] = (2, 3, 4, 5),
    quantity: str = "quantity of interest",
    unit: str = "",
    progress: Callable[[float, str], None] | None = None,
) -> ConvergenceStudy:
    """Run a refinement sequence.

    ``solve_at(n)`` takes a number of elements through the thickness and returns
    ``(value, element_count, degrees_of_freedom, element_size)``. Keeping the solve
    behind a callable means the same study works for the verification backend and for
    CalculiX without this module knowing which is in use.
    """
    study = ConvergenceStudy(quantity=quantity, unit=unit)

    for index, refinement in enumerate(refinements):
        if progress:
            progress(
                index / max(1, len(refinements)),
                f"Meshing and solving at {refinement} elements through thickness...",
            )
        value, element_count, dof, size = solve_at(refinement)
        study.points.append(
            ConvergencePoint(
                elements_through_thickness=refinement,
                element_count=element_count,
                degrees_of_freedom=dof,
                value=value,
                element_size=size,
            )
        )
        logger.info(
            "Convergence point: %d el/thk, %d elements, value %.6g",
            refinement, element_count, value,
        )

    if not study.is_converged():
        study.notes.append(
            f"NOT CONVERGED: the two finest meshes differ by "
            f"{study.final_change * 100:.2f}%, above the 2% criterion. Refine further "
            "before quoting this quantity."
        )
    if not study.is_monotonic():
        study.notes.append(
            "The sequence is not monotonic, which suggests mesh-dependent artefacts "
            "rather than smooth convergence. Investigate before relying on the value."
        )
    if progress:
        progress(1.0, "Convergence study complete.")
    return study
