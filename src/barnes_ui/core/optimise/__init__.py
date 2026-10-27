"""Design-space search, trade-off analysis and sensitivity.

Phase 7. Three things here are easy to get wrong in ways that look like success.

**A sweep launders assumptions at scale.** Running one reduced-order analysis and
labelling it provisional is honest. Running four hundred, plotting a smooth surface
and picking the minimum produces something that looks like an optimisation result and
carries exactly the same provisional material underneath. Every value in this package
keeps its provenance tag, and the Pareto front reports the weakest tag it contains.

**An optimum is not a design.** The best point in a sweep is the best *of the points
that were evaluated*, under *the objectives that were written down*, with *the model
that was used*. :class:`~barnes_ui.core.optimise.pareto.ParetoFront` refuses to name a
single winner when the objectives conflict, because that choice is a human trade-off
and not a calculation.

**Ranking survives material uncertainty; absolute values do not.** Both the
reduced-order model and a small-strain FEA are linear in the elastic modulus, so a
modulus uncertainty scales every design's stiffness by the same factor and cancels out
of a comparison. :mod:`~barnes_ui.core.optimise.sensitivity` makes that quantitative
rather than assumed, and distinguishes the objectives it is true of from the ones it
is not.
"""

from __future__ import annotations

__all__: list[str] = []
