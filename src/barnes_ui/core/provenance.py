"""Provenance tagging for every number the application reports.

Why this module exists
----------------------

A finite element run that converges, renders a smooth deformed shape and prints
"restoring torque 14.3 N.mm" is extremely persuasive. It is also worth nothing if the
material coefficients were guessed. The number looks identical either way.

The defence is to make the *origin* of a value travel with the value, through every
function it passes through, all the way into the plot, the CSV and the report. A
provisional estimate that passes through three calculations must still be recognisable
as a provisional estimate at the other end. Without that, an assumption gets laundered
into an apparent measurement simply by being used.

This is deliberately intrusive. It is meant to be.

The rules
---------

1. Every value carries a :class:`Provenance` tag.
2. Combining values yields the *weakest* tag among the inputs. Multiplying a measured
   length by a guessed modulus does not give you a measurement.
3. Caveats accumulate and are never dropped.
4. Nothing is ever promoted to EXPERIMENTALLY_VALIDATED by a calculation. That tag is
   applied by a human who compared a prediction against a physical measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Callable, Iterable, Sequence

__all__ = [
    "Provenance",
    "Caveat",
    "TaggedValue",
    "combine_provenance",
    "weakest",
]


class Provenance(IntEnum):
    """How a value was obtained, ordered from least to most trustworthy.

    Ordering by IntEnum is what makes "take the weakest input" a ``min()`` call, and it
    means the ranking is stated in exactly one place: here.

    UNVALIDATED_ASSUMPTION
        A placeholder. A material parameter nobody has measured, a dimension taken off a
        screenshot, a default the user has not reviewed. Anything computed from one of
        these inherits the tag.

    REDUCED_ORDER_PREDICTION
        Output of the beam/rod model. Fast, useful for ranking design variants, and
        carrying an unknown error for tightly curved geometry until it has been measured
        against FEA. A screening tool, not a predictor.

    ANALYTICAL_ESTIMATE
        A closed-form result, valid strictly inside its own assumptions. Trustworthy for
        a straight beam in small deflection; inapplicable the moment those assumptions
        are left behind.

    FEA_RESULT
        A converged finite element solution. Good, conditional on the material being
        calibrated and the mesh having been shown to converge. Convergence alone is a
        numerical property and says nothing about physical validity.

    GEOMETRIC_MEASUREMENT
        Read from the CAD model itself. Bounded only by the fidelity of the import, so
        exact for B-rep formats and approximate for anything mesh-derived.

    EXPERIMENTALLY_VALIDATED
        Compared against a physical measurement. The only tag that cannot be produced by
        software, and the only one that closes the loop.
    """

    UNVALIDATED_ASSUMPTION = 10
    REDUCED_ORDER_PREDICTION = 20
    ANALYTICAL_ESTIMATE = 30
    FEA_RESULT = 40
    GEOMETRIC_MEASUREMENT = 50
    EXPERIMENTALLY_VALIDATED = 60

    @property
    def label(self) -> str:
        """Short human-readable name, for table columns and badges."""
        return {
            Provenance.UNVALIDATED_ASSUMPTION: "Assumption",
            Provenance.REDUCED_ORDER_PREDICTION: "Reduced-order",
            Provenance.ANALYTICAL_ESTIMATE: "Analytical",
            Provenance.FEA_RESULT: "FEA",
            Provenance.GEOMETRIC_MEASUREMENT: "Measured",
            Provenance.EXPERIMENTALLY_VALIDATED: "Validated",
        }[self]

    @property
    def description(self) -> str:
        """One-line explanation, for tooltips and report legends."""
        return {
            Provenance.UNVALIDATED_ASSUMPTION:
                "Assumed value. Not measured, not validated. Treat as a placeholder.",
            Provenance.REDUCED_ORDER_PREDICTION:
                "Reduced-order beam model. For screening and ranking only; "
                "error against FEA is unknown until measured.",
            Provenance.ANALYTICAL_ESTIMATE:
                "Closed-form result, valid only within its stated assumptions.",
            Provenance.FEA_RESULT:
                "Converged finite element result. Validity depends on material "
                "calibration and mesh convergence.",
            Provenance.GEOMETRIC_MEASUREMENT:
                "Measured from the imported CAD geometry.",
            Provenance.EXPERIMENTALLY_VALIDATED:
                "Compared against physical measurement.",
        }[self]

    @property
    def is_quantitatively_trustworthy(self) -> bool:
        """Whether an absolute number with this tag may be acted on.

        Reduced-order predictions are excluded deliberately. They are good at saying
        design A is stiffer than design B and unreliable at saying by how much.
        """
        return self >= Provenance.FEA_RESULT

    @property
    def requires_warning_banner(self) -> bool:
        return self <= Provenance.REDUCED_ORDER_PREDICTION


@dataclass(frozen=True)
class Caveat:
    """A limitation attached to a value.

    ``key`` lets duplicates be removed when the same caveat arrives through several
    inputs -- a torque computed from two assumed parameters should not display
    "material parameters are assumed" twice.
    """

    key: str
    message: str

    def __str__(self) -> str:
        return self.message


# Caveats raised often enough to be worth naming once, so that the wording stays
# consistent everywhere they appear and they deduplicate correctly.
CAVEAT_ASSUMED_MATERIAL = Caveat(
    "assumed_material",
    "Material parameters are assumed, not calibrated against test data. "
    "Absolute force and stress values are not validated predictions.",
)
CAVEAT_UNCONFIRMED_UNITS = Caveat(
    "unconfirmed_units",
    "The source file did not declare its units; a default was assumed. "
    "Confirm the unit before relying on any dimension.",
)
CAVEAT_MESH_DERIVED = Caveat(
    "mesh_derived",
    "Geometry came from a tessellated (mesh) file, so exact surfaces are not "
    "available. Curvature, arc length and bend radius are approximations whose error "
    "depends on the export tolerance used.",
)
CAVEAT_SMALL_STRAIN = Caveat(
    "small_strain",
    "Small-strain, linear-elastic kinematics assumed. Not valid for the large "
    "deflections a finger flexure actually undergoes.",
)
CAVEAT_SLENDER_BEAM = Caveat(
    "slender_beam",
    "Slender-beam theory assumed: cross-section small relative to the radius of "
    "curvature, shear deformation neglected. Both assumptions are weak in a tight "
    "meander turn.",
)
CAVEAT_NO_VISCOELASTICITY = Caveat(
    "no_viscoelasticity",
    "Purely hyperelastic material. Hysteresis, stress relaxation, rate dependence and "
    "permanent set are not modelled.",
)
CAVEAT_MESH_NOT_CONVERGED = Caveat(
    "mesh_not_converged",
    "No mesh-convergence study was performed for this result, so the discretisation "
    "error is unknown.",
)


@dataclass(frozen=True)
class TaggedValue:
    """A number, its unit, where it came from, and what is wrong with it.

    Immutable on purpose: arithmetic returns a new instance rather than mutating, so a
    value cannot have its provenance quietly upgraded by a function it was passed to.

    The arithmetic operators are provided because the alternative -- unwrapping to a
    float to do the maths and re-wrapping afterwards -- is exactly how provenance gets
    lost in practice. Making the tracked path the convenient path is the point.

    >>> length = TaggedValue(10.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
    >>> modulus = TaggedValue(12.0, "MPa", Provenance.UNVALIDATED_ASSUMPTION,
    ...                       caveats=(CAVEAT_ASSUMED_MATERIAL,))
    >>> product = length * modulus
    >>> product.provenance is Provenance.UNVALIDATED_ASSUMPTION
    True
    """

    value: float
    unit: str
    provenance: Provenance
    caveats: tuple[Caveat, ...] = ()
    label: str = ""

    def __post_init__(self) -> None:
        # Normalise caveats to a deduplicated tuple so equality and display behave.
        if self.caveats:
            object.__setattr__(self, "caveats", _dedupe(self.caveats))

    # -- display ---------------------------------------------------------------

    def formatted(self, significant: int = 6) -> str:
        from .units import format_quantity

        return format_quantity(self.value, self.unit, significant)

    def __str__(self) -> str:
        return f"{self.formatted()} [{self.provenance.label}]"

    # -- arithmetic ------------------------------------------------------------
    #
    # Each operation takes the weakest provenance of its inputs and the union of
    # their caveats. The unit handling is intentionally minimal: this is not a
    # full dimensional-analysis system, it composes unit strings so that the
    # result is at least readable and obviously wrong if something is mismatched.

    def _binary(
        self,
        other: "TaggedValue | float | int",
        op: Callable[[float, float], float],
        unit_op: Callable[[str, str], str],
    ) -> "TaggedValue":
        if isinstance(other, TaggedValue):
            return TaggedValue(
                value=op(self.value, other.value),
                unit=unit_op(self.unit, other.unit),
                provenance=weakest((self.provenance, other.provenance)),
                caveats=_dedupe(self.caveats + other.caveats),
            )
        if isinstance(other, (int, float)):
            # A plain number is treated as an exact scalar, so it neither weakens
            # the provenance nor contributes a caveat.
            return replace(self, value=op(self.value, float(other)), label="")
        return NotImplemented

    def __add__(self, other: "TaggedValue | float | int") -> "TaggedValue":
        if isinstance(other, TaggedValue) and other.unit != self.unit:
            raise ValueError(
                f"Cannot add {self.unit} to {other.unit} -- convert to a common unit "
                "first. This is almost always a bug rather than an intent."
            )
        return self._binary(other, lambda a, b: a + b, lambda u, _: u)

    def __sub__(self, other: "TaggedValue | float | int") -> "TaggedValue":
        if isinstance(other, TaggedValue) and other.unit != self.unit:
            raise ValueError(
                f"Cannot subtract {other.unit} from {self.unit} -- convert to a common "
                "unit first."
            )
        return self._binary(other, lambda a, b: a - b, lambda u, _: u)

    def __mul__(self, other: "TaggedValue | float | int") -> "TaggedValue":
        return self._binary(other, lambda a, b: a * b, _multiply_units)

    __rmul__ = __mul__

    def __truediv__(self, other: "TaggedValue | float | int") -> "TaggedValue":
        return self._binary(other, lambda a, b: a / b, _divide_units)

    def __neg__(self) -> "TaggedValue":
        return replace(self, value=-self.value)

    # -- provenance manipulation -----------------------------------------------

    def with_caveat(self, caveat: Caveat) -> "TaggedValue":
        """Return a copy with one more caveat attached."""
        return replace(self, caveats=_dedupe(self.caveats + (caveat,)))

    def downgraded_to(self, provenance: Provenance) -> "TaggedValue":
        """Return a copy with a weaker provenance.

        Only ever weakens. Attempting to strengthen a tag raises, because a calculation
        is not allowed to improve the standing of its own inputs -- that is the exact
        laundering this module exists to prevent. Promotion to
        EXPERIMENTALLY_VALIDATED happens through a deliberate validation workflow, not
        through arithmetic.
        """
        if provenance > self.provenance:
            raise ValueError(
                f"Refusing to upgrade provenance from {self.provenance.label} to "
                f"{provenance.label}. Provenance can only be weakened by calculation."
            )
        return replace(self, provenance=provenance)

    def relabelled(self, label: str) -> "TaggedValue":
        return replace(self, label=label)


def weakest(provenances: Iterable[Provenance]) -> Provenance:
    """The least trustworthy provenance in a collection.

    Raises on an empty collection rather than inventing a default, since there is no
    honest answer to "how trustworthy is nothing".
    """
    items = list(provenances)
    if not items:
        raise ValueError("weakest() requires at least one provenance")
    return min(items)


def combine_provenance(values: Sequence[TaggedValue]) -> tuple[Provenance, tuple[Caveat, ...]]:
    """Resolve the provenance and caveats of a result computed from ``values``.

    Use this when a calculation is too involved to express with the arithmetic
    operators -- compute the number however is natural, then call this to work out what
    tag and caveats the answer has to carry.
    """
    if not values:
        raise ValueError("combine_provenance() requires at least one value")
    tag = weakest(v.provenance for v in values)
    caveats: tuple[Caveat, ...] = ()
    for value in values:
        caveats += value.caveats
    return tag, _dedupe(caveats)


def _dedupe(caveats: Sequence[Caveat]) -> tuple[Caveat, ...]:
    """Drop duplicate caveats by key, preserving first-seen order."""
    seen: set[str] = set()
    out: list[Caveat] = []
    for caveat in caveats:
        if caveat.key not in seen:
            seen.add(caveat.key)
            out.append(caveat)
    return tuple(out)


def _multiply_units(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return f"{left}.{right}"


def _divide_units(left: str, right: str) -> str:
    if not right:
        return left
    return f"{left}/{right}"


def describe_caveats(values: Iterable[TaggedValue]) -> list[str]:
    """Collect the distinct caveat messages across several values.

    Used by the assumptions panel, which must never be empty for a result that has
    caveats attached.
    """
    collected: list[Caveat] = []
    for value in values:
        collected.extend(value.caveats)
    return [c.message for c in _dedupe(collected)]
