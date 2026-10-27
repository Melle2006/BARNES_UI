"""Adapting a parametric flexure to a new joint, with a report of what changed.

The rule
--------

**Regenerate, never scale.** Stretching an imported solid to span a new distance
changes its cross-section, and bending stiffness goes as the cube of width, so a 10 %
distortion in width is a 33 % change in stiffness that nobody asked for and nobody
sees. Risk R5. Every adaptation in this module produces a new
:class:`~barnes_ui.core.flexure.templates.meander.MeanderParameters` and rebuilds from
it, so the section is whatever the parameters say and nothing else.

The second rule is that every change is reported. An adaptation that quietly altered
the width while the user was asking for a different span would be indistinguishable
from one that did not, in the viewport and in the stiffness number. So the output is
not just a new parameter set but an :class:`AdaptationReport` listing each parameter
that moved, by how much, and whether the move was asked for.

What "safety checks" means here
-------------------------------

Three screens, with very different standing, and they are deliberately not merged:

* **Manufacturability** is geometric and reliable. A 0.15 mm feature on a 0.4 mm
  nozzle will not print. Tagged ``GEOMETRIC_MEASUREMENT``.
* **Required strain** is a crude closed-form screen, tagged ``ANALYTICAL_ESTIMATE``.
  It assumes the centreline takes a uniform curvature, which it does not. It is good
  for catching "this design needs 180 % strain", useless for distinguishing 18 % from
  22 %, and must not be used in place of an FEA.
* **Self-intersection** is checked by rebuilding the solid and comparing its measured
  volume against the analytically exact ``width * thickness * centreline_length``.
  Overlapping turns fuse and the volume comes out *low*, which makes a volume check a
  reliable detector rather than a proxy for one.

A design that fails any blocking check is not auto-approved. It is returned, with the
reason, for a person to decide about.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from ..provenance import Caveat, Provenance, TaggedValue
from .templates.meander import MeanderParameters

logger = logging.getLogger(__name__)

__all__ = [
    "ParameterChange",
    "SafetyIssue",
    "AdaptationReport",
    "AdaptationError",
    "adapt_to_span",
    "manufacturability_issues",
    "required_peak_strain",
    "verify_regeneration",
    "CAVEAT_UNIFORM_CURVATURE",
]


CAVEAT_UNIFORM_CURVATURE = Caveat(
    "uniform_curvature",
    "Required strain was estimated by assuming the flexure's centreline takes a "
    "uniform curvature. A real meander concentrates curvature in its turns, so the "
    "true peak strain is higher -- use this only to reject obviously impossible "
    "designs, never to approve marginal ones.",
)


class AdaptationError(ValueError):
    """An adaptation that cannot be performed as asked."""


@dataclass(frozen=True)
class ParameterChange:
    """One parameter that moved during an adaptation."""

    name: str
    before: float
    after: float
    unit: str
    #: True when the caller asked for this parameter to change; False when it moved as
    #: a consequence of something else. The distinction is the whole point of the
    #: report: an unintended change is the one worth reading.
    intended: bool
    reason: str = ""

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def relative(self) -> float:
        return self.delta / self.before if self.before else float("inf")

    def __str__(self) -> str:
        marker = "" if self.intended else "  <- not requested"
        return (
            f"{self.name}: {self.before:.6g} -> {self.after:.6g} {self.unit} "
            f"({self.relative * 100:+.2f} %){marker}"
        )


@dataclass(frozen=True)
class SafetyIssue:
    """A reason a design should not be accepted without a human decision."""

    key: str
    message: str
    #: Blocking issues prevent automatic approval. Non-blocking ones are warnings.
    blocking: bool
    measured: float | None = None
    limit: float | None = None

    def __str__(self) -> str:
        prefix = "BLOCKING" if self.blocking else "WARNING"
        return f"[{prefix}] {self.message}"


@dataclass
class AdaptationReport:
    """Everything that happened during one adaptation."""

    base: MeanderParameters
    adapted: MeanderParameters
    changes: list[ParameterChange] = field(default_factory=list)
    issues: list[SafetyIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def unintended_changes(self) -> list[ParameterChange]:
        return [c for c in self.changes if not c.intended]

    @property
    def blocking_issues(self) -> list[SafetyIssue]:
        return [i for i in self.issues if i.blocking]

    @property
    def is_auto_approvable(self) -> bool:
        """Whether the adapted design may be used without someone agreeing to it.

        False whenever anything is blocking. Phase 4 criterion 5 requires that a
        design with a sub-manufacturable feature is flagged and *not* auto-approved,
        so this property is the thing the UI and any batch sweep must consult.
        """
        return not self.blocking_issues

    def changed(self, name: str) -> bool:
        return any(c.name == name for c in self.changes)

    def summary(self) -> str:
        lines = [f"Adaptation of {self.base.n_runs}-run meander:"]
        if not self.changes:
            lines.append("  no parameter changed")
        for change in self.changes:
            lines.append(f"  {change}")
        for issue in self.issues:
            lines.append(f"  {issue}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        lines.append(
            f"  auto-approvable: {self.is_auto_approvable}"
        )
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "changes": [
                {
                    "name": c.name, "before": c.before, "after": c.after,
                    "unit": c.unit, "intended": c.intended, "reason": c.reason,
                }
                for c in self.changes
            ],
            "issues": [
                {
                    "key": i.key, "message": i.message, "blocking": i.blocking,
                    "measured": i.measured, "limit": i.limit,
                }
                for i in self.issues
            ],
            "auto_approvable": self.is_auto_approvable,
            "notes": list(self.notes),
        }


def _diff(base: MeanderParameters, adapted: MeanderParameters,
          intended: Sequence[str], reason: str) -> list[ParameterChange]:
    """Every parameter that differs, marked intended or not."""
    units = {
        "run_length": "mm", "n_runs": "", "pitch": "mm", "width": "mm",
        "thickness": "mm", "tab_length": "mm", "tab_width": "mm",
    }
    changes: list[ParameterChange] = []
    for name, unit in units.items():
        before = float(getattr(base, name))
        after = float(getattr(adapted, name))
        if before != after:
            changes.append(
                ParameterChange(
                    name=name, before=before, after=after, unit=unit,
                    intended=name in intended,
                    reason=reason if name in intended else "consequence of the above",
                )
            )
    return changes


def adapt_to_span(
    base: MeanderParameters,
    target_span: float,
    strategy: str = "pitch",
    minimum_feature_size: float = 0.4,
    joint_angle: float = math.radians(100.0),
    strain_limit: float = 0.30,
) -> AdaptationReport:
    """Adapt a meander to bridge ``target_span`` millimetres between attachments.

    The span is the meander's extent along Y -- ``(n_runs - 1) * pitch + width`` --
    which is the direction the member bridges.

    ``strategy`` chooses what gives:

    ``"pitch"``
        Keep the run count, change the spacing. Preserves the number of turns and
        therefore the character of the design, and changes the turn radius, which
        changes the peak strain.
    ``"runs"``
        Keep the pitch, change the run count to the nearest whole number that fits,
        then absorb the remainder in the pitch. Preserves turn radius, so the strain
        per turn is unchanged, at the cost of a different number of turns.

    Thickness and width are never touched by either strategy. That is the contract of
    Phase 4 criterion 3, and it is enforced by assertion at the end of this function
    rather than merely intended.
    """
    if target_span <= 0.0:
        raise AdaptationError(f"target_span must be positive, got {target_span}.")

    current_span = base.envelope[1]

    if strategy == "pitch":
        if base.n_runs < 2:  # pragma: no cover - MeanderParameters already refuses
            raise AdaptationError("A meander needs at least two runs.")
        pitch = (target_span - base.width) / (base.n_runs - 1)
        if pitch <= base.width:
            raise AdaptationError(
                f"Spanning {target_span:g} mm with {base.n_runs} runs needs a pitch of "
                f"{pitch:.4f} mm, which is not greater than the {base.width:g} mm "
                "width -- adjacent runs would merge into a solid block. Use more runs, "
                "a narrower strap, or strategy='runs'."
            )
        adapted = replace(base, pitch=pitch)
        intended = ("pitch",)
        reason = f"span {current_span:.4f} -> {target_span:.4f} mm at fixed run count"

    elif strategy == "runs":
        ideal = (target_span - base.width) / base.pitch + 1.0
        n_runs = max(2, int(round(ideal)))
        pitch = (target_span - base.width) / (n_runs - 1)
        if pitch <= base.width:
            raise AdaptationError(
                f"Spanning {target_span:g} mm needs {n_runs} runs at {pitch:.4f} mm "
                f"pitch, which is not greater than the {base.width:g} mm width."
            )
        adapted = replace(base, n_runs=n_runs, pitch=pitch)
        intended = ("n_runs", "pitch")
        reason = (
            f"span {current_span:.4f} -> {target_span:.4f} mm at approximately "
            f"constant pitch"
        )

    else:
        raise AdaptationError(
            f"Unknown strategy {strategy!r}. Use 'pitch' or 'runs'."
        )

    report = AdaptationReport(base=base, adapted=adapted)
    report.changes = _diff(base, adapted, intended, reason)

    achieved = adapted.envelope[1]
    report.notes.append(
        f"span {current_span:.4f} -> {achieved:.4f} mm "
        f"(target {target_span:.4f} mm, error {achieved - target_span:+.2e} mm)"
    )
    report.notes.append(
        f"centreline {base.centreline_length:.4f} -> "
        f"{adapted.centreline_length:.4f} mm"
    )

    # The contract, checked rather than trusted. If a future strategy forgets it, this
    # is where it is caught, not in a stiffness number that looks plausible.
    if adapted.thickness != base.thickness:
        raise AdaptationError(
            "Internal error: the adaptation changed the thickness from "
            f"{base.thickness} to {adapted.thickness} mm. Thickness is preserved "
            "exactly unless explicitly varied."
        )
    if adapted.width != base.width:
        raise AdaptationError(
            "Internal error: the adaptation changed the width from "
            f"{base.width} to {adapted.width} mm."
        )

    report.issues.extend(manufacturability_issues(adapted, minimum_feature_size))
    strain = required_peak_strain(adapted, joint_angle)
    if strain.value > strain_limit:
        report.issues.append(
            SafetyIssue(
                key="excessive_strain",
                message=(
                    f"Estimated peak bending strain {strain.value * 100:.1f} % at "
                    f"{math.degrees(joint_angle):.0f} deg exceeds the "
                    f"{strain_limit * 100:.0f} % limit. This is a uniform-curvature "
                    "estimate and the true peak is higher, so treat it as a floor."
                ),
                blocking=True,
                measured=strain.value,
                limit=strain_limit,
            )
        )
    report.notes.append(
        f"estimated peak strain {strain.value * 100:.2f} % at "
        f"{math.degrees(joint_angle):.0f} deg [{strain.provenance.label}]"
    )
    return report


def manufacturability_issues(
    parameters: MeanderParameters,
    minimum_feature_size: float = 0.4,
    minimum_turn_radius_ratio: float = 0.0,
) -> list[SafetyIssue]:
    """Geometric printability checks.

    ``minimum_feature_size`` defaults to 0.4 mm, a common FDM nozzle diameter. A
    feature narrower than one extrusion width is not a thin feature, it is an absent
    one: the slicer drops it, and the printed part is not the part that was analysed.
    """
    issues: list[SafetyIssue] = []

    if parameters.width < minimum_feature_size:
        issues.append(
            SafetyIssue(
                key="width_below_minimum",
                message=(
                    f"Strap width {parameters.width:.3f} mm is below the "
                    f"{minimum_feature_size:.3f} mm minimum feature size. The slicer "
                    "will not produce this wall, so the printed part would not be the "
                    "part analysed."
                ),
                blocking=True,
                measured=parameters.width,
                limit=minimum_feature_size,
            )
        )
    if parameters.thickness < minimum_feature_size:
        issues.append(
            SafetyIssue(
                key="thickness_below_minimum",
                message=(
                    f"Extrusion thickness {parameters.thickness:.3f} mm is below the "
                    f"{minimum_feature_size:.3f} mm minimum feature size."
                ),
                blocking=True,
                measured=parameters.thickness,
                limit=minimum_feature_size,
            )
        )
    if parameters.inner_radius < minimum_feature_size:
        issues.append(
            SafetyIssue(
                key="inner_radius_below_minimum",
                message=(
                    f"Inner turn radius {parameters.inner_radius:.3f} mm is below the "
                    f"{minimum_feature_size:.3f} mm minimum feature size. The gap "
                    "between adjacent runs will close up in print."
                ),
                blocking=True,
                measured=parameters.inner_radius,
                limit=minimum_feature_size,
            )
        )

    if minimum_turn_radius_ratio > 0.0:
        ratio = parameters.turn_radius / parameters.width
        if ratio < minimum_turn_radius_ratio:
            issues.append(
                SafetyIssue(
                    key="tight_turn_stress_concentration",
                    message=(
                        f"Turn radius is only {ratio:.2f} times the strap width. Below "
                        f"{minimum_turn_radius_ratio:.2f} the turn is a stress "
                        "concentrator and beam theory stops applying, so the "
                        "reduced-order stiffness for this design is not trustworthy "
                        "even for ranking."
                    ),
                    blocking=False,
                    measured=ratio,
                    limit=minimum_turn_radius_ratio,
                )
            )
    return issues


def required_peak_strain(
    parameters: MeanderParameters, joint_angle: float
) -> TaggedValue:
    """Crude estimate of the peak bending strain at a given joint rotation.

    Spreads the rotation uniformly over the centreline, giving a curvature of
    ``theta / L``, and takes the outer-fibre strain as ``kappa * width / 2``.

    This is a floor, not a prediction. A real meander concentrates curvature in its
    turns, so the true peak is higher -- on the A3 twin strap the equivalent
    calculation gave 42 % where the member is nothing like uniformly curved. Its only
    legitimate use is rejecting designs that cannot possibly work.
    """
    length = parameters.centreline_length
    curvature = abs(joint_angle) / length
    strain = curvature * parameters.width / 2.0
    return TaggedValue(
        value=float(strain),
        unit="",
        provenance=Provenance.ANALYTICAL_ESTIMATE,
        caveats=(CAVEAT_UNIFORM_CURVATURE,),
        label=f"peak bending strain at {math.degrees(joint_angle):.0f} deg",
    )


def verify_regeneration(
    parameters: MeanderParameters,
    measured_volume: float,
    tolerance: float = 0.005,
) -> SafetyIssue | None:
    """Compare a rebuilt solid's measured volume against the exact expected value.

    Phase 4 criterion 2 in its general form: regenerating at a given parameter set must
    reproduce the volume those parameters imply. ``None`` means it did.

    This is also the self-intersection detector. Turns that overlap fuse into one body
    and the union's volume comes out *below* the sum of its parts, so a volume deficit
    is direct evidence of overlap rather than a proxy for it.
    """
    expected = parameters.expected_volume
    if expected <= 0.0:  # pragma: no cover - MeanderParameters refuses this
        raise AdaptationError("Expected volume is not positive.")
    error = (measured_volume - expected) / expected
    if abs(error) <= tolerance:
        return None
    direction = (
        "below -- the usual cause is turns overlapping and fusing, which removes "
        "material the parameters account for"
        if error < 0 else
        "above -- the usual cause is tabs or another body being included in the "
        "measurement"
    )
    return SafetyIssue(
        key="regeneration_volume_mismatch",
        message=(
            f"Regenerated volume {measured_volume:.6g} mm^3 differs from the exact "
            f"{expected:.6g} mm^3 implied by the parameters by {error * 100:+.3f} %, "
            f"outside the {tolerance * 100:.1f} % tolerance. That is {direction}."
        ),
        blocking=True,
        measured=measured_volume,
        limit=expected,
    )
