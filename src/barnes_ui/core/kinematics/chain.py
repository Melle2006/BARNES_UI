"""Forward kinematics for a serial chain of revolute joints.

A finger is a serial chain: MCP, then PIP, then DIP, each carrying everything distal
to it. Rotating the PIP moves the middle phalanx, the distal phalanx and the DIP's own
axis; rotating the DIP moves only the distal phalanx. That nesting is the whole of the
kinematics, and getting it right is mostly bookkeeping.

Two things here are not bookkeeping.

**Joint axes move.** The DIP axis is attached to the middle phalanx, so flexing the
PIP carries it along. A chain that rotates every joint about its *as-imported* axis
produces a hand that looks almost right and is wrong by a growing amount down the
chain. :meth:`SerialChain.pose` composes transforms outward from the base precisely so
that each joint acts about its axis *as currently placed*.

**Every axis must be confirmed.** :class:`SerialChain` calls ``require_axis()`` on
every joint when it is built, so an unconfirmed guess cannot reach an animation. See
:mod:`barnes_ui.core.assembly.joint`.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from ..assembly.joint import Joint, JointError
from ..assembly.model import Placement
from ..mechanics.curved_beam import JointAxis
from .modes import KinematicPose, SimulationMode

logger = logging.getLogger(__name__)

__all__ = [
    "rotation_placement",
    "SerialChain",
    "ChainError",
    "OutOfRangeError",
]


class ChainError(ValueError):
    """A chain that cannot be built or posed."""


class OutOfRangeError(ChainError):
    """A requested angle lies outside a joint's stated range of motion."""


def rotation_placement(axis: JointAxis, angle: float) -> Placement:
    """A :class:`Placement` rotating by ``angle`` radians about ``axis``.

    The translation part is ``p - R p``, which is what makes the rotation happen about
    the axis line rather than about the world origin. Forgetting it produces a hand
    whose fingers orbit the origin.
    """
    origin, direction = axis.as_arrays()
    direction = direction / np.linalg.norm(direction)
    cross = np.array([
        [0.0, -direction[2], direction[1]],
        [direction[2], 0.0, -direction[0]],
        [-direction[1], direction[0], 0.0],
    ])
    rotation = (
        np.eye(3) * math.cos(angle)
        + math.sin(angle) * cross
        + (1.0 - math.cos(angle)) * np.outer(direction, direction)
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = origin - rotation @ origin
    return Placement.from_matrix(matrix)


@dataclass
class SerialChain:
    """An ordered chain of revolute joints, base first.

    ``joints[i]``'s distal set must contain ``joints[i + 1]``'s distal set: that is
    what makes the chain serial, and it is checked rather than assumed, because a
    mis-ordered chain produces plausible motion with the wrong parts moving.
    """

    name: str
    joints: list[Joint] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.joints:
            raise ChainError(f"Chain {self.name!r} has no joints.")

        names = [j.name for j in self.joints]
        if len(set(names)) != len(names):
            raise ChainError(
                f"Chain {self.name!r} has duplicate joint names: {names}. Angles are "
                "addressed by name, so duplicates would be ambiguous."
            )

        for joint in self.joints:
            try:
                joint.require_axis()
            except JointError as exc:
                raise ChainError(
                    f"Chain {self.name!r} cannot be built: {exc}"
                ) from exc

        for outer, inner in zip(self.joints, self.joints[1:]):
            if not set(inner.distal) <= set(outer.distal):
                missing = sorted(set(inner.distal) - set(outer.distal))
                raise ChainError(
                    f"Chain {self.name!r} is not serial: joint {inner.name!r} moves "
                    f"component(s) {missing} that joint {outer.name!r}, which is "
                    "closer to the base, does not. List the joints base-first, or "
                    "model this as a tree rather than a chain."
                )

    @property
    def joint_names(self) -> tuple[str, ...]:
        return tuple(j.name for j in self.joints)

    def joint(self, name: str) -> Joint:
        for candidate in self.joints:
            if candidate.name == name:
                return candidate
        raise KeyError(
            f"Chain {self.name!r} has no joint {name!r}. It has "
            f"{', '.join(self.joint_names)}."
        )

    def neutral_angles(self) -> dict[str, float]:
        return {j.name: 0.0 if j.contains(0.0) else j.minimum_angle
                for j in self.joints}

    def check_angles(self, angles: Mapping[str, float]) -> None:
        """Raise if any angle is outside its joint's range, or any joint is missing."""
        missing = sorted(set(self.joint_names) - set(angles))
        if missing:
            raise ChainError(
                f"No angle given for joint(s) {', '.join(missing)}. A pose has to "
                "state every joint; defaulting a missing one to zero would quietly "
                "produce a different pose than the caller asked for."
            )
        extra = sorted(set(angles) - set(self.joint_names))
        if extra:
            raise ChainError(
                f"Angle(s) given for joint(s) {', '.join(extra)}, which are not in "
                f"chain {self.name!r}."
            )
        for joint in self.joints:
            value = float(angles[joint.name])
            if not joint.contains(value):
                low, high = joint.range_degrees
                raise OutOfRangeError(
                    f"Joint {joint.name!r} was asked for "
                    f"{math.degrees(value):.2f} deg, outside its stated range "
                    f"{low:.1f} to {high:.1f} deg. Widen the range deliberately if "
                    "the mechanism really goes there."
                )

    def placements(self, angles: Mapping[str, float]) -> dict[int, Placement]:
        """World placement of every moving component at the given joint angles.

        Composed from the base outward. Each joint's rotation is taken about its axis
        *as placed by the joints proximal to it*, so the axis travels with the link it
        is attached to.
        """
        self.check_angles(angles)

        result: dict[int, Placement] = {}
        accumulated = Placement.identity()

        for joint in self.joints:
            axis = joint.require_axis()
            moved_origin = accumulated.apply_point(axis.origin)
            moved_direction = accumulated.apply_direction(axis.direction)
            placed_axis = JointAxis(origin=moved_origin, direction=moved_direction)

            accumulated = rotation_placement(
                placed_axis, float(angles[joint.name])
            ).compose(accumulated)

            for index in joint.distal:
                result[index] = accumulated

        # Proximal components of the base joint do not move, and are reported at the
        # identity so a caller can place the whole assembly from one dictionary.
        for index in self.joints[0].proximal:
            result.setdefault(index, Placement.identity())
        return result

    def pose(self, angles: Mapping[str, float], time: float = 0.0) -> KinematicPose:
        """A Mode 1 pose. Carries no force, by the type's construction."""
        return KinematicPose(
            angles=dict(angles),
            placements={
                index: placement.matrix
                for index, placement in self.placements(angles).items()
            },
            time=float(time),
            mode=SimulationMode.KINEMATIC_PREVIEW,
        )

    def trajectory(
        self, schedule: Sequence[tuple[float, Mapping[str, float]]]
    ) -> list[KinematicPose]:
        """Poses at a sequence of ``(time, angles)`` samples."""
        return [self.pose(angles, time) for time, angles in schedule]

    def sweep_one_joint(
        self, name: str, steps: int = 21,
        others: Mapping[str, float] | None = None,
    ) -> list[KinematicPose]:
        """Poses across one joint's whole range, everything else held fixed.

        The motion a range-of-motion interference check runs over.
        """
        joint = self.joint(name)
        base = dict(self.neutral_angles())
        if others:
            base.update(others)
        poses: list[KinematicPose] = []
        for index in range(steps):
            fraction = index / max(1, steps - 1)
            angles = dict(base)
            angles[name] = (
                joint.minimum_angle + fraction * joint.range_of_motion
            )
            poses.append(self.pose(angles, time=fraction))
        return poses

    def describe(self) -> str:
        lines = [f"Chain {self.name!r}, {len(self.joints)} joints, base first:"]
        for joint in self.joints:
            low, high = joint.range_degrees
            lines.append(
                f"  {joint.name}: {low:.0f} to {high:.0f} deg, "
                f"{len(joint.distal)} distal component(s), "
                f"axis {'confirmed' if joint.confirmed else 'UNCONFIRMED'}"
            )
        return "\n".join(lines)
