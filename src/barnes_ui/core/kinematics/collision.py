"""Interference checking along a kinematic trajectory.

Phase 5 criterion 3: motion through a full range either completes without interference
or reports where it occurs. "Reports where" is the operative half -- a boolean answer
is nearly useless for a design decision, whereas "the distal phalanx hits the proximal
one from 78 degrees onward" tells you what to change.

This sits in :mod:`barnes_ui.core.kinematics` rather than in
:mod:`barnes_ui.core.assembly` because it depends on the chain, and the chain depends
on the assembly. The geometric primitives it uses all come from
:mod:`barnes_ui.core.assembly.interference`.

The flexure is excluded by default and deliberately
---------------------------------------------------

Placing a flexure by a joint's rigid rotation shows the part in a pose it never takes:
in reality it bends, with its two ends following their respective links. Including it
in a rigid sweep would produce confident interference results about a shape that does
not exist. Components named in ``deformable`` are therefore skipped, and the report
says so, so that "no interference" is never read as covering a part that was not
checked.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..assembly.interference import (
    box_separation,
    minimum_clearance,
    pair_interference,
    place_shape,
)
from ..assembly.model import Placement
from ..cad.inspect import bounding_box
from ..provenance import Provenance, TaggedValue
from .modes import KinematicPose

logger = logging.getLogger(__name__)

__all__ = ["TrajectoryClash", "TrajectoryReport", "check_trajectory"]


@dataclass
class TrajectoryClash:
    """One colliding pair at one instant."""

    time: float
    first: int
    second: int
    volume: float
    angles: dict[str, float] = field(default_factory=dict)

    def describe(self) -> str:
        pose = ", ".join(
            f"{name} {math.degrees(value):.1f} deg"
            for name, value in self.angles.items()
        )
        return (
            f"t={self.time:.3f}s ({pose}): components {self.first} and "
            f"{self.second} overlap by {self.volume:.4g} mm^3"
        )


@dataclass
class TrajectoryReport:
    """What a whole trajectory did, geometrically."""

    clashes: list[TrajectoryClash] = field(default_factory=list)
    #: Tightest clearance seen between any checked pair, over the whole trajectory.
    tightest_clearance: float = float("inf")
    tightest_at: float | None = None
    poses_checked: int = 0
    pairs_per_pose: int = 0
    skipped_components: tuple[int, ...] = ()
    screened_out: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_clear(self) -> bool:
        return not self.clashes

    def first_clash(self) -> TrajectoryClash | None:
        return min(self.clashes, key=lambda c: c.time) if self.clashes else None

    def tagged_clearance(self) -> TaggedValue:
        return TaggedValue(
            value=self.tightest_clearance,
            unit="mm",
            provenance=Provenance.GEOMETRIC_MEASUREMENT,
            label="tightest clearance over the trajectory",
        )

    def summary(self) -> str:
        lines = [
            f"{self.poses_checked} pose(s), {self.pairs_per_pose} body pair(s) each."
        ]
        if self.skipped_components:
            lines.append(
                f"  NOT CHECKED: component(s) "
                f"{', '.join(map(str, self.skipped_components))} were excluded as "
                "deformable. A clear result does not cover them."
            )
        if self.is_clear:
            lines.append(
                f"  Clear. Tightest clearance {self.tightest_clearance:.4f} mm"
                + (f" at t={self.tightest_at:.3f}s." if self.tightest_at is not None
                   else ".")
            )
        else:
            first = self.first_clash()
            lines.append(f"  INTERFERENCE, first at {first.describe()}")
            lines.append(f"  {len(self.clashes)} clashing pair-poses in total.")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


def check_trajectory(
    poses: Sequence[KinematicPose],
    shapes: Mapping[int, Any],
    deformable: Sequence[int] = (),
    clearance_of_interest: float = 2.0,
    ignore_pairs: Sequence[tuple[int, int]] = (),
) -> TrajectoryReport:
    """Check every pose of a trajectory for interference between rigid bodies.

    ``shapes`` maps component index to its geometry *in the assembly's rest pose*;
    each pose's placements are applied here. Only components present in both
    ``shapes`` and the pose are checked.

    ``ignore_pairs`` is for bodies that are meant to touch -- a pin in its bore, a
    flexure's tab bonded into a collar. Listing a pair is a modelling statement and
    appears in the report.
    """
    skipped = tuple(sorted(set(deformable) & set(shapes)))
    checkable = [index for index in sorted(shapes) if index not in set(deformable)]
    ignored = {tuple(sorted(pair)) for pair in ignore_pairs}

    report = TrajectoryReport(
        skipped_components=skipped,
        poses_checked=len(poses),
    )
    if skipped:
        report.notes.append(
            "Deformable components are excluded from rigid sweeps because a rigid "
            "rotation puts them in a pose the real part never takes."
        )
    if ignored:
        report.notes.append(
            f"{len(ignored)} pair(s) were declared as intentionally touching and not "
            "checked."
        )

    pairs = [
        (a, b)
        for i, a in enumerate(checkable)
        for b in checkable[i + 1:]
        if (a, b) not in ignored
    ]
    report.pairs_per_pose = len(pairs)

    for pose in poses:
        placed: dict[int, Any] = {}
        boxes: dict[int, Any] = {}
        for index in checkable:
            matrix = pose.placements.get(index)
            placement = (
                Placement.from_matrix(matrix) if matrix is not None
                else Placement.identity()
            )
            moved = place_shape(shapes[index], placement)
            placed[index] = moved
            boxes[index] = bounding_box(moved)

        for first, second in pairs:
            gap = box_separation(boxes[first], boxes[second])
            if gap > clearance_of_interest:
                report.screened_out += 1
                continue
            overlap = pair_interference(placed[first], placed[second])
            if overlap > 0.0:
                report.clashes.append(
                    TrajectoryClash(
                        time=pose.time, first=first, second=second,
                        volume=overlap, angles=dict(pose.angles),
                    )
                )
                if report.tightest_clearance > 0.0:
                    report.tightest_clearance = 0.0
                    report.tightest_at = pose.time
                continue
            clearance = minimum_clearance(placed[first], placed[second])
            if clearance < report.tightest_clearance:
                report.tightest_clearance = clearance
                report.tightest_at = pose.time

    return report
