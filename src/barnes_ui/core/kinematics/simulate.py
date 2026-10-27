"""Mode 2: driving a chain through a motion and reporting restoring torque.

What a Mode 2 run is
--------------------

A sequence of poses from :mod:`.chain`, each with a torque per joint from a
:class:`~.spring.JointSpring`. Quasi-static: no inertia, no damping, no contact state
change. The output is a torque-angle history and the total work done, both tagged
``REDUCED_ORDER_PREDICTION`` and both carrying the caveats that come with condensing a
deformable body to a scalar spring.

What it is not
--------------

It is not a dynamic simulation. Nothing here integrates an equation of motion; the
motion is prescribed and the torque is what the spring says at each prescribed angle.
Calling the result "the force needed to close the hand" would be wrong twice over --
it omits inertia, and it omits everything the joint spring omits.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from ..provenance import Caveat, TaggedValue, combine_provenance
from .chain import SerialChain
from .modes import KinematicPose, SimulationMode, require_mode
from .spring import ExtrapolationError, JointResponse, JointSpring

logger = logging.getLogger(__name__)

__all__ = [
    "TimeStep",
    "SimulationResult",
    "SimulationError",
    "simulate_reduced_order",
    "preview_kinematics",
]


class SimulationError(RuntimeError):
    """A run that cannot be completed as specified."""


@dataclass
class TimeStep:
    """One instant: where everything is, and what torque each joint is carrying."""

    time: float
    pose: KinematicPose
    responses: dict[str, JointResponse] = field(default_factory=dict)

    @property
    def total_torque_magnitude(self) -> float:
        """Sum of absolute joint torques. A crude but useful single number."""
        return float(sum(abs(r.torque.value) for r in self.responses.values()))


@dataclass
class SimulationResult:
    """A whole Mode 2 run."""

    chain_name: str
    steps: list[TimeStep] = field(default_factory=list)
    mode: SimulationMode = SimulationMode.REDUCED_ORDER
    notes: list[str] = field(default_factory=list)
    #: Angles at which a joint was asked for a torque outside its spring's range.
    extrapolated_at: list[tuple[str, float]] = field(default_factory=list)

    @property
    def banner(self) -> str:
        return self.mode.banner

    @property
    def times(self) -> np.ndarray:
        return np.array([s.time for s in self.steps])

    def angles(self, joint: str) -> np.ndarray:
        return np.array([s.pose.angles[joint] for s in self.steps])

    def torques(self, joint: str) -> np.ndarray:
        return np.array([s.responses[joint].torque.value for s in self.steps])

    def caveats(self) -> tuple[Caveat, ...]:
        """Every caveat in force across the run. Phase 5 criterion 5.

        Never empty for a Mode 2 result: the reduced-order caveats are attached to
        every spring at fit time.
        """
        values = [
            step.responses[joint].torque
            for step in self.steps
            for joint in step.responses
        ]
        if not values:
            return ()
        _, caveats = combine_provenance(values)
        return caveats

    def peak_torque(self, joint: str) -> TaggedValue:
        torques = self.torques(joint)
        index = int(np.argmax(np.abs(torques)))
        return self.steps[index].responses[joint].torque

    def work_done(self, joint: str) -> TaggedValue:
        """Work done against one joint's spring over the path, in mJ.

        Integrated along the actual trajectory rather than taken from the spring's
        own energy function, so a profile that goes out and comes back reports the
        net work -- which for a purely elastic spring is zero, and for a real
        viscoelastic part would not be. The model has no viscoelasticity, so a zero
        here is a statement about the model.
        """
        angles = self.angles(joint)
        torques = self.torques(joint)
        value = float(np.trapezoid(torques, angles))
        tag, caveats = combine_provenance(
            [s.responses[joint].torque for s in self.steps]
        )
        return TaggedValue(
            value=value, unit="mJ", provenance=tag, caveats=caveats,
            label=f"net work against {joint} over the trajectory",
        )

    def as_rows(self) -> list[dict[str, float]]:
        """Flat table for CSV export, one row per time step per joint."""
        rows: list[dict[str, float]] = []
        for step in self.steps:
            for joint, response in step.responses.items():
                rows.append({
                    "time_s": step.time,
                    "joint": joint,
                    "angle_deg": response.angle_degrees,
                    "torque_n_mm": response.torque.value,
                    "provenance": response.torque.provenance.label,
                })
        return rows

    def summary(self) -> str:
        if not self.steps:
            return f"{self.chain_name}: no steps."
        lines = [
            self.banner,
            f"{self.chain_name}: {len(self.steps)} steps from "
            f"{self.steps[0].time:.3f} to {self.steps[-1].time:.3f} s.",
        ]
        for joint in self.steps[0].responses:
            peak = self.peak_torque(joint)
            angles = np.degrees(self.angles(joint))
            lines.append(
                f"  {joint}: {angles.min():.1f} to {angles.max():.1f} deg, "
                f"peak |torque| {abs(peak.value):.4g} N.mm [{peak.provenance.label}]"
            )
        if self.extrapolated_at:
            lines.append(
                f"  WARNING: {len(self.extrapolated_at)} evaluation(s) outside a "
                "spring's fitted range."
            )
        for caveat in self.caveats():
            lines.append(f"  caveat: {caveat.message}")
        return "\n".join(lines)


def preview_kinematics(
    chain: SerialChain,
    schedule: Sequence[tuple[float, Mapping[str, float]]],
) -> list[KinematicPose]:
    """Mode 1. Poses only.

    Exists as its own function, returning a type with no torque field, so that a
    caller who wants an animation cannot accidentally obtain forces along with it.
    """
    return [chain.pose(angles, time) for time, angles in schedule]


def simulate_reduced_order(
    chain: SerialChain,
    springs: Mapping[str, JointSpring],
    schedule: Sequence[tuple[float, Mapping[str, float]]],
    allow_extrapolation: bool = False,
) -> SimulationResult:
    """Mode 2. Poses plus a restoring torque per joint at each pose.

    Every joint in the chain must have a spring. A chain with a torque for two of its
    three joints would produce a total that looks like a total and is not one, so a
    missing spring is an error rather than a skipped joint.
    """
    require_mode(SimulationMode.REDUCED_ORDER, SimulationMode.REDUCED_ORDER)

    missing = [name for name in chain.joint_names if name not in springs]
    if missing:
        raise SimulationError(
            f"No joint spring for {', '.join(missing)}. Run the FEA for "
            "those joints, or drop them from the chain. A partial torque total is "
            "worse than none, because it looks like a total."
        )

    result = SimulationResult(chain_name=chain.name)
    for time, angles in schedule:
        pose = chain.pose(angles, time)
        step = TimeStep(time=float(time), pose=pose)
        for name in chain.joint_names:
            angle = float(angles[name])
            spring = springs[name]
            if not spring.covers(angle):
                result.extrapolated_at.append((name, angle))
                if not allow_extrapolation:
                    low, high = spring.fitted_range_degrees
                    raise ExtrapolationError(
                        f"The trajectory reaches {math.degrees(angle):.1f} deg at "
                        f"joint {name!r}, outside the {low:.1f} to {high:.1f} deg "
                        "its spring was fitted over. Either run the FEA across the "
                        "full range of motion, or pass allow_extrapolation=True and "
                        "accept that part of the curve is unsupported."
                    )
            step.responses[name] = JointResponse(
                joint=name,
                angle=angle,
                torque=spring.torque(angle, allow_extrapolation=allow_extrapolation),
            )
        result.steps.append(step)

    if result.extrapolated_at:
        joints = sorted({name for name, _ in result.extrapolated_at})
        result.notes.append(
            f"{len(result.extrapolated_at)} pose(s) were extrapolated beyond the "
            f"fitted range of joint(s) {', '.join(joints)}."
        )
    return result
