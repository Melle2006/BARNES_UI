"""Time-based motion profiles for driving a chain.

These generate *angles over time*, nothing else. They are the input to both modes: in
Mode 1 the profile drives an animation, in Mode 2 the same profile drives the same
animation with a torque evaluated at each pose.

A profile is kinematic by definition -- it says where the joint is at each instant,
not what made it go there. Nothing here solves an equation of motion, and a profile
must never be presented as a dynamic response. Phase 6 is where force-driven motion
would live, if it turns out to be achievable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

import numpy as np

__all__ = [
    "MotionProfile",
    "ConstantAngle",
    "LinearRamp",
    "SinusoidalCycle",
    "TrapezoidalProfile",
    "ProfileError",
    "sample_profiles",
]


class ProfileError(ValueError):
    """A profile that cannot be evaluated."""


class MotionProfile(Protocol):
    """Anything that can say what angle a joint is at, at a time."""

    duration: float

    def angle_at(self, time: float) -> float:
        ...


@dataclass(frozen=True)
class ConstantAngle:
    """A joint held still. Useful for the joints a study is not varying."""

    angle: float
    duration: float = 1.0

    def angle_at(self, time: float) -> float:
        return float(self.angle)


@dataclass(frozen=True)
class LinearRamp:
    """Constant angular velocity from ``start`` to ``end``.

    Discontinuous in velocity at both ends, so it is not a motion any real actuator
    produces. It is the right default anyway: for a quasi-static study the time axis
    is a parameterisation, not a physical schedule, and a linear ramp samples the
    angular range evenly, which is what makes the resulting torque-angle plot read
    correctly.
    """

    start: float
    end: float
    duration: float = 1.0

    def __post_init__(self) -> None:
        if self.duration <= 0.0:
            raise ProfileError(f"duration must be positive, got {self.duration}.")

    def angle_at(self, time: float) -> float:
        fraction = min(1.0, max(0.0, float(time) / self.duration))
        return float(self.start + (self.end - self.start) * fraction)


@dataclass(frozen=True)
class SinusoidalCycle:
    """Smooth flexion and return, one full cycle over ``duration``.

    Starts and ends at ``start`` with zero velocity, peaking at ``end`` halfway
    through. The usual choice for a cyclic-loading preview.

    It is worth being explicit that running this profile through a hyperelastic model
    gives a curve that retraces itself exactly on the way back. A real TPU part does
    not: it shows hysteresis, and the area inside the loop is energy it turned into
    heat. The model has no viscoelasticity, so a closing-and-opening animation shows
    no hysteresis -- which is a property of the model, not a finding about the part.
    """

    start: float
    end: float
    duration: float = 1.0

    def __post_init__(self) -> None:
        if self.duration <= 0.0:
            raise ProfileError(f"duration must be positive, got {self.duration}.")

    def angle_at(self, time: float) -> float:
        phase = 2.0 * math.pi * float(time) / self.duration
        shape = 0.5 * (1.0 - math.cos(phase))
        return float(self.start + (self.end - self.start) * shape)


@dataclass(frozen=True)
class TrapezoidalProfile:
    """Ramp up, hold, ramp down. The shape a tendon-driven grasp roughly follows."""

    start: float
    end: float
    duration: float = 1.0
    ramp_fraction: float = 0.25

    def __post_init__(self) -> None:
        if self.duration <= 0.0:
            raise ProfileError(f"duration must be positive, got {self.duration}.")
        if not 0.0 < self.ramp_fraction <= 0.5:
            raise ProfileError(
                f"ramp_fraction must be in (0, 0.5], got {self.ramp_fraction}. Two "
                "ramps cannot occupy more than the whole profile."
            )

    def angle_at(self, time: float) -> float:
        t = min(1.0, max(0.0, float(time) / self.duration))
        ramp = self.ramp_fraction
        if t < ramp:
            shape = t / ramp
        elif t > 1.0 - ramp:
            shape = (1.0 - t) / ramp
        else:
            shape = 1.0
        return float(self.start + (self.end - self.start) * shape)


def sample_profiles(
    profiles: Mapping[str, MotionProfile],
    steps: int = 51,
    duration: float | None = None,
) -> list[tuple[float, dict[str, float]]]:
    """Evaluate several joints' profiles on one shared time grid.

    ``duration`` defaults to the longest profile's, so a short profile holds at its
    end value rather than the schedule being truncated to it.
    """
    if not profiles:
        raise ProfileError("No profiles were given.")
    if steps < 2:
        raise ProfileError(f"steps must be at least 2, got {steps}.")
    span = duration if duration is not None else max(
        float(p.duration) for p in profiles.values()
    )
    if span <= 0.0:
        raise ProfileError(f"duration must be positive, got {span}.")

    grid = np.linspace(0.0, span, steps)
    return [
        (float(t), {name: float(p.angle_at(float(t))) for name, p in profiles.items()})
        for t in grid
    ]
