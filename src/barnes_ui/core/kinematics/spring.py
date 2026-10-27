"""Condensing an FEA torque-angle curve into a joint spring.

What this is for
----------------

A nonlinear FEA of the A3 flexure takes about half an hour per angle. A whole-hand
animation needs a torque at thousands of poses. The bridge is to run the FEA at a
handful of angles, fit a curve through them, and evaluate that curve instead -- fidelity
level L4 in ``docs/04-architecture.md``.

That is a real approximation and it is sound exactly while the joint's torque depends
on angle alone. It stops being true when the contact state changes mid-motion, when
loading history matters -- which for a viscoelastic material it does -- or when the
flexure interacts with another deformable part. Risk R9. Every value this module
produces therefore carries :data:`REDUCED_ORDER_CAVEATS`, attached by construction
rather than by whoever remembered.

Why extrapolation is refused rather than warned about
-----------------------------------------------------

A fitted spring outside its fitted range is not a worse estimate; it is an arbitrary
one. A polynomial that fits beautifully from 0 to 60 degrees can curve the wrong way at
70, and a flexure's torque genuinely does stiffen sharply as turns begin to close --
behaviour no fit over gentler angles can know about.

So :meth:`JointSpring.torque` raises outside the fitted range unless the caller passes
``allow_extrapolation=True``, which attaches a caveat that travels with the value.
Phase 5 criterion 2 asks for a visible warning; this makes the warning part of the
number rather than part of the UI.

Measuring the fit against full scale, not point by point
--------------------------------------------------------

The torque passes through zero at the neutral angle, so a point-by-point relative error
is meaningless there -- a 1e-9 N.mm absolute error on a 1e-12 N.mm value is a
100,000 per cent relative error and tells nobody anything. Fit quality is therefore
reported relative to the largest torque in the data, which is the convention
instrumentation uses for the same reason.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

import numpy as np

from ..provenance import Caveat, Provenance, TaggedValue
from .modes import REDUCED_ORDER_CAVEATS, SimulationMode

logger = logging.getLogger(__name__)

__all__ = [
    "SpringFitKind",
    "JointSpring",
    "JointResponse",
    "SpringFitError",
    "ExtrapolationError",
    "fit_joint_spring",
    "CAVEAT_EXTRAPOLATED",
    "CAVEAT_FITTED_FROM_FEA",
]


CAVEAT_EXTRAPOLATED = Caveat(
    "extrapolated_spring",
    "This torque was evaluated outside the angular range the FEA covered. A fitted "
    "curve outside its data is an arbitrary number, not a worse estimate -- a real "
    "flexure stiffens sharply as its turns begin to close, and no fit over gentler "
    "angles can know that.",
)
CAVEAT_FITTED_FROM_FEA = Caveat(
    "fitted_joint_spring",
    "The joint is represented by a curve fitted to FEA results at a few angles, not "
    "by a deformable model. It inherits every limitation of the FEA it came from.",
)


class SpringFitError(ValueError):
    """Data that cannot be fitted, or a fit that is not good enough to use."""


class ExtrapolationError(ValueError):
    """An evaluation outside the fitted range, where the fit means nothing."""


class SpringFitKind(Enum):
    """How the curve is fitted through the FEA points.

    INTERPOLATED
        Shape-preserving piecewise cubic (PCHIP). Passes through every data point
        exactly and cannot overshoot between them, which matters because a plain cubic
        spline through a stiffening curve will invent a local softening that the FEA
        never showed. The default.

    ODD_POLYNOMIAL
        Least-squares fit of ``a1*x + a3*x^3 + a5*x^5 + ...``, with no constant term.
        For a flexure that is symmetric about its neutral position, the torque is an
        odd function of angle, and a fit that enforces that uses the data twice as
        efficiently. Choose it when the design really is symmetric; it is a modelling
        statement, not a smoothing preference.
    """

    INTERPOLATED = "interpolated"
    ODD_POLYNOMIAL = "odd_polynomial"


@dataclass
class JointSpring:
    """A torque-angle law for one joint, fitted to FEA samples.

    Angles are radians, torques N.mm. Positive torque opposes positive rotation --
    that is, this is the *restoring* torque, which is the sign convention the rest of
    the application uses.
    """

    name: str
    #: The FEA samples this was fitted to, sorted by angle.
    sample_angles: np.ndarray
    sample_torques: np.ndarray
    kind: SpringFitKind
    #: Where the samples came from, verbatim: run ids, mesh, material. Shown in the
    #: assumptions panel, because "fitted to FEA" is not traceable and
    #: "fitted to runs d54c262a, 8f10ab21 at 0.5 mm elements" is.
    source: str
    #: Weakest provenance among the inputs. An FEA on an assumed material is still an
    #: assumption, and the spring fitted to it is no stronger.
    provenance: Provenance = Provenance.REDUCED_ORDER_PREDICTION
    caveats: tuple[Caveat, ...] = ()
    notes: list[str] = field(default_factory=list)
    _evaluator: Any = None
    _coefficients: np.ndarray | None = None

    # -- range -----------------------------------------------------------------

    @property
    def minimum_angle(self) -> float:
        return float(self.sample_angles[0])

    @property
    def maximum_angle(self) -> float:
        return float(self.sample_angles[-1])

    @property
    def fitted_range_degrees(self) -> tuple[float, float]:
        return (math.degrees(self.minimum_angle), math.degrees(self.maximum_angle))

    def covers(self, angle: float, tolerance: float = 1.0e-9) -> bool:
        return (
            self.minimum_angle - tolerance <= angle <= self.maximum_angle + tolerance
        )

    # -- evaluation ------------------------------------------------------------

    def _raw(self, angle: np.ndarray | float) -> np.ndarray:
        x = np.atleast_1d(np.asarray(angle, dtype=float))
        if self.kind is SpringFitKind.INTERPOLATED:
            return np.asarray(self._evaluator(x), dtype=float)
        powers = np.arange(1, 2 * len(self._coefficients), 2)
        return np.asarray(
            (x[:, None] ** powers[None, :]) @ self._coefficients, dtype=float
        )

    def torque(
        self, angle: float, allow_extrapolation: bool = False
    ) -> TaggedValue:
        """Restoring torque at ``angle`` radians, as a tagged value.

        Raises :class:`ExtrapolationError` outside the fitted range unless
        ``allow_extrapolation`` is set, in which case the returned value carries
        :data:`CAVEAT_EXTRAPOLATED`.
        """
        angle = float(angle)
        caveats = self.caveats
        if not self.covers(angle):
            low, high = self.fitted_range_degrees
            if not allow_extrapolation:
                raise ExtrapolationError(
                    f"Joint spring {self.name!r} was fitted over {low:.1f} to "
                    f"{high:.1f} deg and was asked for "
                    f"{math.degrees(angle):.1f} deg. Run the FEA at the angle you "
                    "need, or pass allow_extrapolation=True and accept a number the "
                    "data does not support."
                )
            caveats = caveats + (CAVEAT_EXTRAPOLATED,)
            logger.warning(
                "Extrapolating joint spring %r to %.2f deg, outside its fitted "
                "%.1f to %.1f deg.", self.name, math.degrees(angle), low, high,
            )
        return TaggedValue(
            value=float(self._raw(angle)[0]),
            unit="N.mm",
            provenance=self.provenance,
            caveats=caveats,
            label=f"{self.name} restoring torque at {math.degrees(angle):.1f} deg",
        )

    def tangent_stiffness(self, angle: float, step: float = 1.0e-5) -> TaggedValue:
        """Local slope of the torque-angle curve, N.mm/rad.

        Central difference on the fit, with the step clipped so that it never samples
        outside the fitted range -- an extrapolated endpoint would otherwise leak into
        a value the caller believes is interpolated.
        """
        angle = float(angle)
        if not self.covers(angle):
            raise ExtrapolationError(
                f"Joint spring {self.name!r} cannot report a stiffness at "
                f"{math.degrees(angle):.1f} deg, outside its fitted range."
            )
        low = max(self.minimum_angle, angle - step)
        high = min(self.maximum_angle, angle + step)
        if high <= low:  # pragma: no cover - needs a zero-width fitted range
            raise SpringFitError("The fitted range is too narrow to differentiate.")
        slope = float((self._raw(high)[0] - self._raw(low)[0]) / (high - low))
        return TaggedValue(
            value=slope, unit="N.mm/rad", provenance=self.provenance,
            caveats=self.caveats,
            label=f"{self.name} tangent stiffness at {math.degrees(angle):.1f} deg",
        )

    def strain_energy(self, angle: float, samples: int = 201) -> TaggedValue:
        """Work done against the spring from the neutral angle to ``angle``.

        Reported in millijoules, since the project's canonical units give torque in
        N.mm and angle in radians, and 1 N.mm times 1 rad is exactly 1 mJ. Stated
        rather than assumed: a silent factor of 1000 between N.mm and N.m is the
        textbook form of risk R8.
        """
        angle = float(angle)
        if not self.covers(angle):
            raise ExtrapolationError(
                f"Joint spring {self.name!r} cannot report energy at "
                f"{math.degrees(angle):.1f} deg, outside its fitted range."
            )
        neutral = 0.0 if self.covers(0.0) else self.minimum_angle
        grid = np.linspace(neutral, angle, samples)
        energy = float(np.trapezoid(self._raw(grid), grid))
        return TaggedValue(
            value=energy, unit="mJ", provenance=self.provenance,
            caveats=self.caveats,
            label=f"{self.name} strain energy at {math.degrees(angle):.1f} deg",
        )

    # -- fit quality -----------------------------------------------------------

    @property
    def full_scale(self) -> float:
        return float(np.max(np.abs(self.sample_torques)))

    @property
    def residuals(self) -> np.ndarray:
        return self._raw(self.sample_angles) - self.sample_torques

    @property
    def max_relative_residual(self) -> float:
        """Worst fit error at a sample point, relative to the largest sampled torque.

        Phase 5 criterion 2's quantity. Relative to full scale rather than point by
        point, because the curve passes through zero -- see the module docstring.
        """
        scale = self.full_scale
        if scale <= 0.0:
            raise SpringFitError(
                "Every sampled torque is zero, so there is no scale to measure a fit "
                "against. This is a null FEA result, not a very soft joint."
            )
        return float(np.max(np.abs(self.residuals)) / scale)

    def describe(self) -> str:
        low, high = self.fitted_range_degrees
        return (
            f"Joint spring {self.name!r}: {self.kind.value} fit through "
            f"{len(self.sample_angles)} FEA points over {low:.1f} to {high:.1f} deg, "
            f"worst residual {self.max_relative_residual * 100:.4f} % of full scale "
            f"({self.full_scale:.4g} N.mm). Source: {self.source}"
        )

    def as_rows(self) -> list[dict[str, float]]:
        """Sample points plus fitted values, for CSV export."""
        fitted = self._raw(self.sample_angles)
        return [
            {
                "angle_deg": math.degrees(a),
                "fea_torque_n_mm": float(t),
                "fitted_torque_n_mm": float(f),
                "residual_n_mm": float(f - t),
            }
            for a, t, f in zip(self.sample_angles, self.sample_torques, fitted)
        ]


@dataclass(frozen=True)
class JointResponse:
    """A Mode 2 result at one pose: angle in, torque out, caveats attached."""

    joint: str
    angle: float
    torque: TaggedValue
    mode: SimulationMode = SimulationMode.REDUCED_ORDER

    @property
    def angle_degrees(self) -> float:
        return math.degrees(self.angle)

    @property
    def banner(self) -> str:
        return self.mode.banner

    @property
    def caveat_messages(self) -> list[str]:
        """What the UI must display beside this number. Never empty."""
        return [c.message for c in self.torque.caveats]


def fit_joint_spring(
    angles: Sequence[float],
    torques: Sequence[float],
    source: str,
    name: str = "joint",
    kind: SpringFitKind = SpringFitKind.INTERPOLATED,
    polynomial_terms: int = 3,
    provenance: Provenance = Provenance.FEA_RESULT,
    inherited_caveats: Sequence[Caveat] = (),
    maximum_residual: float = 0.01,
) -> JointSpring:
    """Fit a torque-angle law through FEA samples.

    ``provenance`` is the provenance of the FEA results being fitted, which is itself
    no stronger than the material they used. The spring is tagged one step weaker than
    that -- a reduced-order prediction -- because condensing a deformable body into a
    scalar spring is an approximation on top of whatever the FEA already was.

    Raises :class:`SpringFitError` if the fit misses its own data by more than
    ``maximum_residual`` (default 1 per cent of full scale, Phase 5 criterion 2). A
    spring that cannot reproduce the curve it was fitted to has no business being
    evaluated at angles in between.
    """
    x = np.asarray(angles, dtype=float)
    y = np.asarray(torques, dtype=float)
    if x.shape != y.shape:
        raise SpringFitError(
            f"{x.size} angles but {y.size} torques. They have to pair up."
        )
    if x.size < 3:
        raise SpringFitError(
            f"Only {x.size} FEA point(s). A joint spring needs at least three to say "
            "anything about the shape of the curve between them; with two you have a "
            "straight line and should say so explicitly."
        )
    order = np.argsort(x)
    x, y = x[order], y[order]
    if np.any(np.diff(x) <= 0.0):
        raise SpringFitError(
            "Two FEA samples share an angle. Which torque is correct at that angle is "
            "not something this function can decide."
        )

    spring = JointSpring(
        name=name,
        sample_angles=x,
        sample_torques=y,
        kind=kind,
        source=source,
        # min() takes the weakest: an FEA on an assumed material cannot produce a
        # spring stronger than an assumption.
        provenance=min(provenance, Provenance.REDUCED_ORDER_PREDICTION),
        caveats=tuple(inherited_caveats) + (CAVEAT_FITTED_FROM_FEA,)
        + REDUCED_ORDER_CAVEATS,
    )

    if kind is SpringFitKind.INTERPOLATED:
        from scipy.interpolate import PchipInterpolator

        spring._evaluator = PchipInterpolator(x, y, extrapolate=True)
    elif kind is SpringFitKind.ODD_POLYNOMIAL:
        if polynomial_terms < 1:
            raise SpringFitError("An odd polynomial needs at least one term.")
        if polynomial_terms > x.size:
            raise SpringFitError(
                f"{polynomial_terms} polynomial terms cannot be fitted to {x.size} "
                "points without interpolating noise."
            )
        powers = np.arange(1, 2 * polynomial_terms, 2)
        design = x[:, None] ** powers[None, :]
        coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
        spring._coefficients = coefficients
    else:  # pragma: no cover - the enum has no other members
        raise SpringFitError(f"Unknown fit kind {kind!r}")

    residual = spring.max_relative_residual
    if residual > maximum_residual:
        raise SpringFitError(
            f"The {kind.value} fit misses its own FEA data by "
            f"{residual * 100:.3f} % of full scale, above the "
            f"{maximum_residual * 100:.1f} % limit. A spring that cannot reproduce "
            "the points it was fitted to must not be evaluated between them. Use "
            "more polynomial terms, or the interpolating fit."
        )
    spring.notes.append(
        f"worst residual {residual * 100:.4f} % of {spring.full_scale:.4g} N.mm "
        "full scale"
    )
    return spring
