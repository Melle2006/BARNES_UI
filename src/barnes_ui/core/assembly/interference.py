"""Interference and clearance checking across a joint's range of motion.

What this does and does not claim
---------------------------------

This is a **geometric** check on rigid bodies, and it is tagged
``GEOMETRIC_MEASUREMENT`` for exactly that reason: it measures the volume shared by two
solids at a given pose, which is a fact about the CAD model. It is not a statement
about the real mechanism, for two reasons worth stating before anyone relies on it.

First, the flexure deforms and the phalanges do not. Rotating the distal phalanx
rigidly about the joint axis is a kinematic preview (fidelity level L1), so what it
checks is whether the *rigid* parts collide. Where the flexure itself is one of the
moving bodies, a rigid rotation of it is wrong by construction -- it is going to bend,
not swing -- and the check will report interference that will not happen, or miss
interference that will. The sweep refuses to include a body flagged as deformable.

Second, clearance is reported as measured, with no allowance for print tolerance,
assembly slop or deflection under load. A 0.05 mm clearance in CAD is not a 0.05 mm
clearance in a printed part.

Cost
----

A boolean common is not cheap on real geometry. The sweep therefore screens with
bounding boxes first and only runs the boolean on pairs whose boxes overlap, which on
a finger assembly discards most pairs at most angles for almost nothing.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

from ..cad._occ import occ, require_kernel
from ..cad.inspect import bounding_box, volume_properties
from ..cad.model import BoundingBox
from ..mechanics.curved_beam import JointAxis
from ..provenance import Provenance, TaggedValue

logger = logging.getLogger(__name__)

__all__ = [
    "rotate_shape",
    "InterferenceAtAngle",
    "InterferenceReport",
    "pair_interference",
    "minimum_clearance",
    "sweep_interference",
]


def rotate_shape(shape: Any, axis: JointAxis, angle: float) -> Any:
    """Rigidly rotate ``shape`` about ``axis`` by ``angle`` radians."""
    require_kernel()
    if abs(angle) < 1.0e-15:
        return shape
    origin, direction = axis.as_arrays()
    transform = occ.gp_Trsf()
    transform.SetRotation(
        occ.gp_Ax1(
            occ.gp_Pnt(float(origin[0]), float(origin[1]), float(origin[2])),
            occ.gp_Dir(float(direction[0]), float(direction[1]), float(direction[2])),
        ),
        float(angle),
    )
    return occ.BRepBuilderAPI_Transform(shape, transform, True).Shape()


def pair_interference(first: Any, second: Any) -> float:
    """Volume shared by two solids, in mm^3. Zero when they do not overlap.

    Uses a boolean common rather than a distance query because touching and
    overlapping are different things and only the second one is a collision.
    """
    require_kernel()
    algorithm = occ.BRepAlgoAPI_Common(first, second)
    if not algorithm.IsDone():
        raise RuntimeError(
            "The boolean intersection failed. This usually means one of the solids is "
            "invalid; check the geometry report before trusting any clearance result."
        )
    common = algorithm.Shape()
    if common is None or common.IsNull():
        return 0.0
    volume, _, _ = volume_properties(common)
    return max(0.0, float(volume))


def minimum_clearance(first: Any, second: Any) -> float:
    """Shortest distance between two solids, in mm. Zero when they touch or overlap."""
    require_kernel()
    distance = occ.BRepExtrema_DistShapeShape(first, second)
    distance.Perform()
    if not distance.IsDone():
        raise RuntimeError("The distance computation did not complete.")
    return float(distance.Value())


@dataclass
class InterferenceAtAngle:
    """What was found at one pose."""

    angle: float
    #: ``(moving label, static label) -> overlap volume in mm^3``, only where non-zero.
    overlaps: dict[tuple[str, str], float] = field(default_factory=dict)
    #: ``(moving label, static label) -> clearance in mm`` for every checked pair.
    clearances: dict[tuple[str, str], float] = field(default_factory=dict)

    @property
    def angle_degrees(self) -> float:
        return math.degrees(self.angle)

    @property
    def has_interference(self) -> bool:
        return bool(self.overlaps)

    @property
    def worst_overlap(self) -> float:
        return max(self.overlaps.values(), default=0.0)

    @property
    def tightest_clearance(self) -> float:
        return min(self.clearances.values(), default=float("inf"))


@dataclass
class InterferenceReport:
    """The result of sweeping a joint through a range of angles."""

    joint_name: str
    samples: list[InterferenceAtAngle] = field(default_factory=list)
    #: Pairs skipped by the bounding-box screen, for transparency about what was run.
    screened_out: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_clear(self) -> bool:
        return not any(s.has_interference for s in self.samples)

    def first_interference(self) -> InterferenceAtAngle | None:
        for sample in self.samples:
            if sample.has_interference:
                return sample
        return None

    @property
    def tightest_clearance(self) -> float:
        return min((s.tightest_clearance for s in self.samples), default=float("inf"))

    def tagged_tightest_clearance(self) -> TaggedValue:
        return TaggedValue(
            value=self.tightest_clearance,
            unit="mm",
            provenance=Provenance.GEOMETRIC_MEASUREMENT,
            label=f"tightest clearance across {self.joint_name}'s range",
        )

    def summary(self) -> str:
        if not self.samples:
            return f"{self.joint_name}: no angles were checked."
        first = self.first_interference()
        angles = [s.angle_degrees for s in self.samples]
        head = (
            f"{self.joint_name}: {len(self.samples)} poses from {angles[0]:.1f} to "
            f"{angles[-1]:.1f} deg."
        )
        if first is None:
            return (
                f"{head} No interference. Tightest clearance "
                f"{self.tightest_clearance:.4f} mm."
            )
        worst = max(first.overlaps.items(), key=lambda kv: kv[1])
        return (
            f"{head} INTERFERENCE from {first.angle_degrees:.1f} deg: "
            f"{worst[0][0]} into {worst[0][1]}, {worst[1]:.4f} mm^3."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "joint": self.joint_name,
            "is_clear": self.is_clear,
            "tightest_clearance_mm": (
                None if math.isinf(self.tightest_clearance)
                else self.tightest_clearance
            ),
            "samples": [
                {
                    "angle_deg": s.angle_degrees,
                    "overlaps": {f"{a} | {b}": v for (a, b), v in s.overlaps.items()},
                    "tightest_clearance_mm": (
                        None if math.isinf(s.tightest_clearance)
                        else s.tightest_clearance
                    ),
                }
                for s in self.samples
            ],
            "screened_out_pairs": self.screened_out,
            "notes": list(self.notes),
        }


def sweep_interference(
    moving: Sequence[tuple[str, Any]],
    stationary: Sequence[tuple[str, Any]],
    axis: JointAxis,
    angles: Iterable[float],
    joint_name: str = "joint",
    clearance_of_interest: float = 1.0,
    deformable_labels: Sequence[str] = (),
) -> InterferenceReport:
    """Rotate every moving body through each angle and check it against the fixed ones.

    ``moving`` and ``stationary`` are ``(label, shape)`` pairs; the labels appear in
    the report. ``clearance_of_interest`` limits how much distance computation is done:
    pairs whose bounding boxes are further apart than this are not measured, since
    their exact clearance is not interesting and the query is not free.

    ``deformable_labels`` names bodies that must not be swept rigidly -- the flexure,
    typically. Naming one raises, rather than quietly producing a plausible animation
    of a part bending in a way it cannot.
    """
    require_kernel()

    named = {label for label, _ in moving} | {label for label, _ in stationary}
    offenders = sorted(set(deformable_labels) & named)
    if offenders:
        raise ValueError(
            f"Cannot sweep {', '.join(offenders)} as a rigid body: it is marked "
            "deformable. Rotating a flexure rigidly about the joint axis produces a "
            "pose the part never takes, so any interference result would be fiction. "
            "Exclude it from the sweep, or use an FEA deformed shape."
        )

    report = InterferenceReport(joint_name=joint_name)
    static_boxes = [(label, shape, bounding_box(shape)) for label, shape in stationary]

    for angle in angles:
        sample = InterferenceAtAngle(angle=float(angle))
        for label, shape in moving:
            posed = rotate_shape(shape, axis, float(angle))
            posed_box = bounding_box(posed)
            for other_label, other_shape, other_box in static_boxes:
                gap = _box_separation(posed_box, other_box)
                if gap > clearance_of_interest:
                    report.screened_out += 1
                    continue
                overlap = pair_interference(posed, other_shape)
                if overlap > 0.0:
                    sample.overlaps[(label, other_label)] = overlap
                    sample.clearances[(label, other_label)] = 0.0
                else:
                    sample.clearances[(label, other_label)] = minimum_clearance(
                        posed, other_shape
                    )
        report.samples.append(sample)

    if report.screened_out:
        report.notes.append(
            f"{report.screened_out} body pairs were screened out by bounding box as "
            f"further apart than {clearance_of_interest:g} mm; their exact clearance "
            "was not measured."
        )
    return report


def _box_separation(first: BoundingBox, second: BoundingBox) -> float:
    """Lower bound on the distance between two solids, from their boxes.

    Zero when the boxes overlap, which means nothing about the solids and simply says
    the cheap test cannot decide.
    """
    gaps = [
        max(second.xmin - first.xmax, first.xmin - second.xmax, 0.0),
        max(second.ymin - first.ymax, first.ymin - second.ymax, 0.0),
        max(second.zmin - first.zmax, first.zmin - second.zmax, 0.0),
    ]
    return float(np.linalg.norm(gaps))
