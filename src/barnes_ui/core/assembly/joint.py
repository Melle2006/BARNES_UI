"""Joint definition: suggested axes, explicit confirmation, motion limits.

The rule this module enforces
-----------------------------

**A joint axis is never inferred.** STEP contains no mates, so there is nothing in the
file that says "these two components rotate about this line". Any axis the software
produces is a guess derived from geometry -- usually the axis of a cylindrical face --
and a guess that is a millimetre off or a degree skewed changes the torque-angle curve
without changing anything visible on screen.

So :func:`find_axis_candidates` returns *candidates*, ranked, each with the evidence
that produced it, and :class:`Joint` refuses to be used for analysis until
:meth:`Joint.confirm` has been called. The confirmation is a deliberate act by a person
who looked at the axis in the viewport. Risk R4 says plainly that a user can confirm a
wrong axis and that the visual preview is the main defence; this module's job is to
make sure the confirmation happens at all.

Why cylindrical faces, and why that is weak evidence
----------------------------------------------------

A revolute joint is usually built around a pin, a boss or a bore, so a cylinder's axis
is often the joint axis. It is also often a screw hole, a cable route or a fillet. The
candidate ranking is therefore honest about being a heuristic: it ranks by how much
cylindrical surface area shares the axis, which favours a real bearing surface over an
M2 clearance hole, and it says so in ``evidence`` rather than presenting a score as a
probability.

A compliant flexure joint has no pin at all. For those, the axis is the line about
which the designer intends rotation to occur, and no amount of geometry inspection will
reveal it -- it has to be typed in or picked. :func:`axis_from_two_points` exists for
that case.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

from ..cad._occ import occ, require_kernel, static
from ..cad.inspect import bounding_box
from ..mechanics.curved_beam import JointAxis
from ..provenance import Caveat

logger = logging.getLogger(__name__)

__all__ = [
    "AxisCandidate",
    "Joint",
    "JointError",
    "UnconfirmedAxisError",
    "find_axis_candidates",
    "axis_from_two_points",
    "CAVEAT_UNCONFIRMED_AXIS",
]


CAVEAT_UNCONFIRMED_AXIS = Caveat(
    "unconfirmed_axis",
    "The joint axis was suggested from cylindrical geometry and has not been "
    "confirmed by a person. An axis that is slightly wrong changes the torque-angle "
    "curve without looking wrong.",
)


class JointError(ValueError):
    """A joint definition that cannot be used."""


class UnconfirmedAxisError(JointError):
    """Raised when an unconfirmed joint is asked for its axis."""


@dataclass(frozen=True)
class AxisCandidate:
    """A possible joint axis, with the evidence that suggested it."""

    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    #: Total area of the cylindrical faces sharing this axis, mm^2.
    supporting_area: float
    #: How many cylindrical faces share it.
    face_count: int
    #: Radii observed on this axis, smallest first.
    radii: tuple[float, ...]
    #: Extent of the supporting faces along the axis, mm.
    axial_extent: float

    @property
    def evidence(self) -> str:
        radii = ", ".join(f"{r:.3f}" for r in self.radii)
        return (
            f"{self.face_count} cylindrical face(s), {self.supporting_area:.2f} mm^2 "
            f"total area, radii [{radii}] mm, {self.axial_extent:.3f} mm along the axis"
        )

    def as_joint_axis(self) -> JointAxis:
        return JointAxis(origin=self.origin, direction=self.direction)

    def angle_to(self, direction: Sequence[float]) -> float:
        """Angle between this candidate's direction and ``direction``, in radians."""
        a = _unit(np.asarray(self.direction, dtype=float))
        b = _unit(np.asarray(direction, dtype=float))
        return float(math.acos(min(1.0, abs(float(np.dot(a, b))))))


@dataclass
class Joint:
    """A revolute joint between two groups of components.

    ``proximal`` does not move; ``distal`` rotates about the axis. Which is which is a
    modelling choice -- the physics is the same either way, but every reaction and
    every plot in the rest of the application is expressed relative to the proximal
    side, so it has to be stated once and stuck to.
    """

    name: str
    proximal: tuple[int, ...]
    distal: tuple[int, ...]
    #: Radians. Negative is extension, positive is flexion, by convention.
    minimum_angle: float = 0.0
    maximum_angle: float = math.radians(100.0)
    #: None until an axis is chosen.
    axis: JointAxis | None = None
    #: How the axis was arrived at, for the assumptions panel.
    axis_source: str = ""
    confirmed: bool = False
    candidates: tuple[AxisCandidate, ...] = ()
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.proximal:
            raise JointError(f"Joint {self.name!r} has no proximal components.")
        if not self.distal:
            raise JointError(f"Joint {self.name!r} has no distal components.")
        overlap = set(self.proximal) & set(self.distal)
        if overlap:
            raise JointError(
                f"Joint {self.name!r} lists component(s) {sorted(overlap)} on both "
                "sides. A component cannot be both the thing that moves and the thing "
                "it moves relative to."
            )
        if self.minimum_angle >= self.maximum_angle:
            raise JointError(
                f"Joint {self.name!r} has an empty range of motion: "
                f"{self.minimum_angle:.4f} to {self.maximum_angle:.4f} rad."
            )

    @property
    def range_of_motion(self) -> float:
        return self.maximum_angle - self.minimum_angle

    @property
    def range_degrees(self) -> tuple[float, float]:
        return (math.degrees(self.minimum_angle), math.degrees(self.maximum_angle))

    def propose(self, candidate: AxisCandidate) -> None:
        """Adopt a candidate as the axis, unconfirmed."""
        self.axis = candidate.as_joint_axis()
        self.axis_source = f"suggested from geometry: {candidate.evidence}"
        self.confirmed = False

    def set_axis(self, axis: JointAxis, source: str) -> None:
        """Set the axis from an explicit definition, still unconfirmed.

        ``source`` is recorded verbatim in the assumptions panel, so it should say
        where the numbers came from -- "typed from the drawing", "picked two vertices",
        "copied from the MCP joint" are all useful; "user" is not.
        """
        if not source.strip():
            raise JointError("An axis needs a stated source. See the docstring.")
        self.axis = axis
        self.axis_source = source
        self.confirmed = False

    def confirm(self, by: str = "") -> None:
        """Mark the axis as reviewed by a person.

        There is no automatic path to this method anywhere in the codebase, and there
        must not be one.
        """
        if self.axis is None:
            raise JointError(
                f"Joint {self.name!r} has no axis to confirm. Propose or set one first."
            )
        self.confirmed = True
        if by:
            self.notes.append(f"Axis confirmed by {by}.")

    def require_axis(self) -> JointAxis:
        """The axis, or an explanation of why there isn't a usable one."""
        if self.axis is None:
            raise UnconfirmedAxisError(
                f"Joint {self.name!r} has no axis. STEP carries no mates, so the axis "
                "must be chosen: call find_axis_candidates() and propose one, or set "
                "it explicitly."
            )
        if not self.confirmed:
            raise UnconfirmedAxisError(
                f"Joint {self.name!r} has an unconfirmed axis ({self.axis_source}). "
                "Look at it in the viewport and call confirm(). A suggested axis is a "
                "guess from geometry, and a wrong one changes every torque this "
                "application will report."
            )
        return self.axis

    def caveats(self) -> tuple[Caveat, ...]:
        return () if self.confirmed else (CAVEAT_UNCONFIRMED_AXIS,)

    def clamp(self, angle: float) -> float:
        return float(min(self.maximum_angle, max(self.minimum_angle, angle)))

    def contains(self, angle: float, tolerance: float = 1.0e-9) -> bool:
        return (self.minimum_angle - tolerance) <= angle <= (self.maximum_angle + tolerance)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "proximal": list(self.proximal),
            "distal": list(self.distal),
            "minimum_angle_deg": math.degrees(self.minimum_angle),
            "maximum_angle_deg": math.degrees(self.maximum_angle),
            "axis": (
                {
                    "origin": list(self.axis.origin),
                    "direction": list(self.axis.direction),
                }
                if self.axis else None
            ),
            "axis_source": self.axis_source,
            "confirmed": self.confirmed,
            "notes": list(self.notes),
        }


def axis_from_two_points(
    first: Sequence[float], second: Sequence[float]
) -> JointAxis:
    """An axis through two picked points.

    The route for a compliant joint, which has no pin for a cylinder detector to find.
    """
    a = np.asarray(first, dtype=float)
    b = np.asarray(second, dtype=float)
    delta = b - a
    length = float(np.linalg.norm(delta))
    if length < 1.0e-9:
        raise JointError(
            "The two points defining the axis are coincident "
            f"(separated by {length:.3g} mm), so they do not define a direction."
        )
    return JointAxis(
        origin=(float(a[0]), float(a[1]), float(a[2])),
        direction=tuple(float(x) for x in delta / length),
    )


def find_axis_candidates(
    shapes: Iterable[Any],
    minimum_radius: float = 0.0,
    maximum_radius: float = float("inf"),
    angular_tolerance_deg: float = 1.0,
    position_tolerance: float = 0.05,
    limit: int = 10,
) -> list[AxisCandidate]:
    """Collect and rank candidate joint axes from cylindrical faces.

    Faces whose axes are parallel to within ``angular_tolerance_deg`` and whose lines
    are within ``position_tolerance`` of each other are merged, so a through-hole in
    two parts reports once rather than twice.

    The ranking is by supporting cylindrical area, which prefers a bearing surface over
    a small fastener hole. It is a heuristic and is labelled as one everywhere it is
    shown.
    """
    require_kernel()
    groups: list[_AxisGroup] = []
    angular_tolerance = math.radians(angular_tolerance_deg)

    for shape in shapes:
        if shape is None:
            continue
        explorer = occ.TopExp_Explorer(shape, occ.TopAbs_ShapeEnum.TopAbs_FACE)
        while explorer.More():
            face = static(occ.TopoDS, "Face")(explorer.Current())
            explorer.Next()
            adaptor = occ.BRepAdaptor_Surface(face)
            if adaptor.GetType() != occ.GeomAbs_SurfaceType.GeomAbs_Cylinder:
                continue
            cylinder = adaptor.Cylinder()
            radius = float(cylinder.Radius())
            if not (minimum_radius <= radius <= maximum_radius):
                continue
            axis = cylinder.Axis()
            location = axis.Location()
            direction = axis.Direction()
            origin = np.array(
                [location.X(), location.Y(), location.Z()], dtype=float
            )
            vector = _unit(
                np.array([direction.X(), direction.Y(), direction.Z()], dtype=float)
            )
            area = _face_area(face)
            extent = _axial_extent(face, origin, vector)

            for group in groups:
                if group.matches(origin, vector, angular_tolerance, position_tolerance):
                    group.add(origin, vector, radius, area, extent)
                    break
            else:
                group = _AxisGroup(origin, vector)
                group.add(origin, vector, radius, area, extent)
                groups.append(group)

    candidates = [group.to_candidate() for group in groups]
    candidates.sort(key=lambda c: (-c.supporting_area, -c.face_count))
    return candidates[:limit]


class _AxisGroup:
    """Cylindrical faces judged to share one axis line."""

    def __init__(self, origin: np.ndarray, direction: np.ndarray) -> None:
        self.direction = direction
        self.reference = origin
        self.points: list[np.ndarray] = []
        self.radii: list[float] = []
        self.area = 0.0
        self.extent = 0.0

    def matches(self, origin: np.ndarray, direction: np.ndarray,
                angular_tolerance: float, position_tolerance: float) -> bool:
        cosine = abs(float(np.dot(self.direction, direction)))
        if cosine < math.cos(angular_tolerance):
            return False
        # Perpendicular distance between the two axis lines' reference points.
        delta = origin - self.reference
        perpendicular = delta - np.dot(delta, self.direction) * self.direction
        return float(np.linalg.norm(perpendicular)) <= position_tolerance

    def add(self, origin: np.ndarray, direction: np.ndarray, radius: float,
            area: float, extent: float) -> None:
        # Keep the direction consistently oriented so averaging does not cancel.
        if float(np.dot(self.direction, direction)) < 0.0:
            direction = -direction
        self.points.append(origin)
        self.radii.append(radius)
        self.area += area
        self.extent = max(self.extent, extent)

    def to_candidate(self) -> AxisCandidate:
        # Project the collected origins onto the axis and take their mean position as
        # the reported origin, so the point sits in the middle of the evidence rather
        # than wherever the first face happened to be parameterised.
        points = np.array(self.points)
        mean = points.mean(axis=0)
        offset = mean - self.reference
        along = float(np.dot(offset, self.direction))
        origin = self.reference + along * self.direction
        return AxisCandidate(
            origin=tuple(float(x) for x in origin),
            direction=tuple(float(x) for x in self.direction),
            supporting_area=float(self.area),
            face_count=len(self.radii),
            radii=tuple(sorted(float(r) for r in self.radii)),
            axial_extent=float(self.extent),
        )


def _face_area(face: Any) -> float:
    props = occ.GProp_GProps()
    static(occ.BRepGProp, "SurfaceProperties")(face, props)
    return float(props.Mass())


def _axial_extent(face: Any, origin: np.ndarray, direction: np.ndarray) -> float:
    """How far the face reaches along its own axis.

    A long bore is better evidence of a bearing than a short chamfer of the same area,
    and this is the cheap way to tell them apart.
    """
    try:
        box = bounding_box(face, optimal=False)
    except ValueError:  # pragma: no cover - an empty face has no extent
        return 0.0
    corners = np.array(
        [
            [x, y, z]
            for x in (box.xmin, box.xmax)
            for y in (box.ymin, box.ymax)
            for z in (box.zmin, box.zmax)
        ]
    )
    projected = (corners - origin) @ direction
    return float(projected.max() - projected.min())


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < 1.0e-15:
        raise JointError("Zero-length direction vector.")
    return vector / norm
