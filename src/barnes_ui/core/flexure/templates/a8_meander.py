"""Parametric template for the A8 PIP meander family, as it is actually drawn.

This is a different family from :mod:`.meander`. That template is a planar
serpentine of straight runs and half-circle turns that doubles back on itself, built
to have analytically known properties. The A8 parts exported from SolidWorks
(``A8_PIP_Meander_2turn_2mm``, ``..._3turn_2mm``, ``..._3turn_2mm_2``) are none of
those things, and the differences decide their stiffness:

* **The path never doubles back.** It is a snake whose lateral position ``x`` is a
  smooth function of the span coordinate ``y``. Every plane ``y = const`` between the
  two rings cuts the strip exactly once -- measured on all three exports at 120
  stations each.
* **The section is drawn in the y-plane, not normal to the path.** Each y-slice is a
  2.000 mm (x) by 1.200 mm (z) rectangle, on all three exports to within 0.2 %. So
  the "2 mm" in the file names is the strip's width measured *across the finger*,
  and the true width normal to the path is ``2.0 * cos(phi)``, where ``phi`` is the
  path's angle to the span axis. Where the path crosses steeply that is 0.92 mm on
  the 2-turn part and 0.75 mm on the 3-turn, and adding turns makes it thinner
  again. This is the single most consequential fact about the family, and it is not
  visible from the file name or a plan view.
* **The spine is a circular arc.** The strip's centroid height ``z(y)`` fits an arc
  through the two end points to 0.015 mm (2-turn, 3-turn) and 0.093 mm (3-turn v2),
  so "curvature of the spine" is fully described by one number, the arc's sagitta.

So the solid is built the way the section is defined: a loft through axis-aligned
rectangles placed on y-planes. Its volume is therefore ``2.0 * 1.2 * span`` whatever
the path or spine -- 61.94 mm^3 for the A8 span -- which is the independent check on
the generated solid. The integrated y-slice volume of all three exports is
61.95 to 62.04 mm^3, which agrees. (OpenCASCADE's own volume of the exported strips
reads 60.5, 66.8 and 51.3 mm^3: its surface integration over these B-spline solids is
not reliable, and the slice integral is the number to trust.)

Plan-path presets
-----------------

The 2- and 3-turn plan paths are not pure sines: lobe amplitudes differ (the 3-turn
part's lobes peak at +3.5, -4.7, +2.9, -4.7, +3.5 mm). Each preset is a least-squares
fit ``x = a + b*s + sum_k c_k sin(k*pi*s)`` with ``s`` running 0 to 1 across the span,
to the measured slice centroids: 0.010 mm RMS for the 2-turn part and 0.033 mm for the
3-turn. Both 3-turn exports share one plan path to within 0.02 mm; they differ only in
the spine.

There is no 4-turn export. :func:`sine_plan` builds one from a pure sine, and that is
an extrapolation of the family, not a measurement of anything.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ...cad._occ import require_kernel

logger = logging.getLogger(__name__)

__all__ = [
    "A8MeanderError",
    "A8MeanderParameters",
    "build_a8_meander",
    "sine_plan",
    "A8_SPAN_START_Y",
    "A8_SPAN_END_Y",
    "A8_PLAN_2TURN",
    "A8_PLAN_3TURN",
    "A8_MEASURED_SAGITTA",
]

#: Span between the ring faces, in the exports' own coordinates (mm). The strip's
#: proximal end cap is the plane y = 3.000 (the proximal ring's face); its distal end
#: sits at y = 28.77 to 28.85 against the distal ring face at 28.86.
A8_SPAN_START_Y = 3.0
A8_SPAN_END_Y = 28.81

#: Centroid height of the strip at each end (mm). The strip's top face is flush with
#: each ring's top -- z = 4.70 proximal, 3.10 distal -- and the section is 1.2 mm tall.
A8_END_Z = (4.10, 2.50)

#: Plan-path coefficients (a, b, c_1 .. c_12), fitted to the exports. See module
#: docstring for the residuals.
A8_PLAN_2TURN: tuple[float, ...] = (
    -0.143, -0.124,
    0.883, -0.027, 4.381, -0.021, -0.102, 0.001, 0.193, -0.001, 0.018, 0.001, 0.033, 0.0,
)
A8_PLAN_3TURN: tuple[float, ...] = (
    0.058, 0.003,
    -0.697, 0.021, 1.006, 0.066, 3.545, -0.111, -0.977, 0.030, 0.054, 0.006, 0.167,
    -0.009,
)

#: Spine sagitta fitted to each export (mm), perpendicular to the end-to-end chord.
A8_MEASURED_SAGITTA = {
    "A8_PIP_Meander_2turn_2mm": 0.751,
    "A8_PIP_Meander_3turn_2mm": 1.140,
    "A8_PIP_Meander_3turn_2mm_2": 2.173,
}


class A8MeanderError(ValueError):
    """The parameters do not describe a buildable A8-family strip."""


def sine_plan(n_turns: int, amplitude: float) -> tuple[float, ...]:
    """Plan coefficients for a pure-sine path with ``2 * n_turns - 1`` lobes.

    The exports' naming counts turns this way: the 2-turn part has three lateral
    lobes and the 3-turn part five, so a 4-turn part has seven.
    """
    if n_turns < 1:
        raise A8MeanderError("n_turns must be at least 1.")
    harmonic = 2 * n_turns - 1
    coefficients = [0.0] * (2 + max(harmonic, 12))
    coefficients[2 + harmonic - 1] = float(amplitude)
    return tuple(coefficients)


@dataclass(frozen=True)
class A8MeanderParameters:
    """One A8-family strip. Lengths in mm."""

    #: Plan-path coefficients ``(a, b, c_1, c_2, ...)``. See module docstring.
    plan: tuple[float, ...]
    #: Spine sagitta, perpendicular to the end-to-end chord. Zero is a straight spine;
    #: positive bulges away from the finger.
    sagitta: float
    #: Turn count, as the exports name it. Informational; the plan defines the path.
    n_turns: int
    #: Section width across the finger, measured in the y-plane.
    width_x: float = 2.0
    #: Section height, measured vertically in the y-plane.
    height_z: float = 1.2
    y_start: float = A8_SPAN_START_Y
    y_end: float = A8_SPAN_END_Y
    z_start: float = A8_END_Z[0]
    z_end: float = A8_END_Z[1]
    #: Loft stations per lobe. Twenty-four keeps the loft within 2 microns of the
    #: analytical path on the 7-lobe case.
    stations_per_lobe: int = 24
    #: When set, the section is drawn square to the path with this true width, instead
    #: of ``width_x`` across the finger. See :func:`build_a8_meander`.
    true_width: float | None = None
    #: Length over which a path-normal section turns to face the span axis at each end,
    #: so the end caps stay flat against the collars (mm).
    end_blend: float = 1.5
    label: str = ""
    notes: list[str] = field(default_factory=list, compare=False)

    def __post_init__(self) -> None:
        if len(self.plan) < 3:
            raise A8MeanderError("plan needs at least (a, b, c_1).")
        if self.width_x <= 0 or self.height_z <= 0:
            raise A8MeanderError("width_x and height_z must be positive.")
        if self.true_width is not None:
            if self.true_width <= 0:
                raise A8MeanderError("true_width must be positive.")
            tightest = self.min_plan_radius()
            if self.true_width / 2.0 >= tightest:
                raise A8MeanderError(
                    f"A {self.true_width} mm strip cannot follow a lobe whose centreline "
                    f"radius is {tightest:.3f} mm: its inner edge would fold over itself."
                )
        if self.y_end <= self.y_start:
            raise A8MeanderError("y_end must exceed y_start.")
        if self.sagitta < 0:
            raise A8MeanderError(
                "A negative sagitta bows the strip into the finger, which the rings "
                "sit on; it is not a feasible member of this family."
            )
        chord = self.chord_length
        if self.sagitta >= chord / 2.0:
            raise A8MeanderError(
                f"A sagitta of {self.sagitta} mm is at least half the {chord:.2f} mm "
                "chord, which is more than a semicircle."
            )

    # -- the path --------------------------------------------------------------

    @property
    def span(self) -> float:
        return self.y_end - self.y_start

    @property
    def chord_length(self) -> float:
        return math.hypot(self.span, self.z_end - self.z_start)

    @property
    def spine_radius(self) -> float:
        """Radius of the spine arc (mm); infinite for a straight spine."""
        if self.sagitta == 0.0:
            return math.inf
        half = self.chord_length / 2.0
        return (self.sagitta ** 2 + half ** 2) / (2.0 * self.sagitta)

    def plan_x(self, y: np.ndarray) -> np.ndarray:
        s = (np.asarray(y, dtype=float) - self.y_start) / self.span
        a, b, *harmonics = self.plan
        x = a + b * s
        for k, c in enumerate(harmonics, start=1):
            if c:
                x = x + c * np.sin(k * math.pi * s)
        return x

    def plan_slope(self, y: np.ndarray) -> np.ndarray:
        """dx/dy of the plan path."""
        s = (np.asarray(y, dtype=float) - self.y_start) / self.span
        a, b, *harmonics = self.plan
        slope = np.full_like(s, b)
        for k, c in enumerate(harmonics, start=1):
            if c:
                slope = slope + c * k * math.pi * np.cos(k * math.pi * s)
        return slope / self.span

    def spine_z(self, y: np.ndarray) -> np.ndarray:
        """Centroid height of the section at ``y``: a circular arc through the ends."""
        y = np.asarray(y, dtype=float)
        dy, dz = self.span, self.z_end - self.z_start
        if self.sagitta == 0.0:
            return self.z_start + (y - self.y_start) * dz / dy
        chord = self.chord_length
        tangent = np.array([dy, dz]) / chord
        normal = np.array([-tangent[1], tangent[0]])
        if normal[1] < 0:
            normal = -normal
        radius = self.spine_radius
        mid = np.array([(self.y_start + self.y_end) / 2.0, (self.z_start + self.z_end) / 2.0])
        centre = mid + normal * (self.sagitta - radius)
        return centre[1] + np.sqrt(radius ** 2 - (y - centre[0]) ** 2)

    @property
    def path_normal(self) -> bool:
        return self.true_width is not None

    def min_plan_radius(self, samples: int = 8001) -> float:
        """Smallest radius of curvature of the plan path (mm)."""
        y = np.linspace(self.y_start, self.y_end, samples)
        slope = self.plan_slope(y)
        curvature = np.abs(np.gradient(slope, y)) / (1.0 + slope ** 2) ** 1.5
        return float(1.0 / max(curvature.max(), 1e-12))

    def spine_slope(self, y: np.ndarray) -> np.ndarray:
        y = np.asarray(y, dtype=float)
        step = 1e-4
        return (self.spine_z(np.clip(y + step, self.y_start, self.y_end))
                - self.spine_z(np.clip(y - step, self.y_start, self.y_end))) / (
            np.clip(y + step, self.y_start, self.y_end)
            - np.clip(y - step, self.y_start, self.y_end))

    def stations(self) -> np.ndarray:
        """Loft station y-coordinates."""
        lobes = max(1, 2 * self.n_turns - 1)
        count = max(40, self.stations_per_lobe * lobes) + 1
        return np.linspace(self.y_start, self.y_end, count)

    # -- derived properties ----------------------------------------------------

    @property
    def expected_volume(self) -> float:
        """Volume (mm^3).

        Drawn across the finger, exact: every y-plane cuts one width_x by height_z
        rectangle. Drawn square to the path, true_width * height_z * centreline length,
        which is exact for a constant section swept without twist and is what the
        loft is checked against.
        """
        if self.path_normal:
            y = np.linspace(self.y_start, self.y_end, 8001)
            pts = np.column_stack([self.plan_x(y), y, self.spine_z(y)])
            length = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
            return self.true_width * self.height_z * length
        return self.width_x * self.height_z * self.span

    def path_metrics(self, samples: int = 4001) -> dict[str, float]:
        """Geometric quantities that bear on stiffness and printability.

        ``min_true_width`` is the strip width normal to the path at its steepest
        crossing, ``width_x * cos(phi_max)``. It is the narrowest wall the printer has
        to lay down and the place bending strain concentrates.
        """
        y = np.linspace(self.y_start, self.y_end, samples)
        x = self.plan_x(y)
        z = self.spine_z(y)
        slope = self.plan_slope(y)
        phi = np.arctan(np.abs(slope))
        points = np.column_stack([x, y, z])
        length = float(np.sum(np.linalg.norm(np.diff(points, axis=0), axis=1)))
        if self.path_normal:
            true = np.full_like(y, self.true_width)
            half_x = self.true_width / 2.0 / np.cos(phi)
        else:
            true = self.width_x * np.cos(phi)
            half_x = np.full_like(y, self.width_x / 2.0)
        return {
            "centreline_length_mm": length,
            "max_path_angle_deg": float(np.degrees(phi.max())),
            "min_true_width_mm": float(true.min()),
            "mean_true_width_mm": float(true.mean()),
            "lateral_extent_mm": float((x + half_x).max() - (x - half_x).min()),
            "x_min_mm": float((x - half_x).min()),
            "x_max_mm": float((x + half_x).max()),
            "min_plan_radius_mm": self.min_plan_radius(),
            "spine_apex_top_z_mm": float((z + self.height_z / 2.0).max()),
            "spine_radius_mm": self.spine_radius,
            "volume_mm3": self.expected_volume,
        }

    def describe(self) -> str:
        metrics = self.path_metrics()
        radius = "straight" if math.isinf(self.spine_radius) else f"R {self.spine_radius:.1f} mm"
        return (
            f"A8 meander {self.label or ''} {self.n_turns}-turn, spine sagitta "
            f"{self.sagitta:.2f} mm ({radius}); centreline "
            f"{metrics['centreline_length_mm']:.2f} mm, min true width "
            f"{metrics['min_true_width_mm']:.3f} mm."
        ).replace("  ", " ")


def build_a8_meander(parameters: A8MeanderParameters) -> Any:
    """Build the strip as an OpenCASCADE solid by lofting y-plane rectangles.

    A loft rather than a pipe sweep because the section is defined in the y-plane: a
    sweep holds the profile normal to the path, which is a different (and wider-at-
    the-crossings) part. Raises :class:`A8MeanderError` rather than returning an
    invalid or open body.
    """
    require_kernel()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.gp import gp_Pnt

    p = parameters
    ys = p.stations()
    xs = p.plan_x(ys)
    zs = p.spine_z(ys)
    hw, hh = p.width_x / 2.0, p.height_z / 2.0

    loft = BRepOffsetAPI_ThruSections(True, False, 1.0e-6)
    loft.CheckCompatibility(False)
    for x, y, z, corners in zip(xs, ys, zs, _section_corners(p, xs, ys, zs, hw, hh)):
        polygon = BRepBuilderAPI_MakePolygon()
        for corner in corners:
            polygon.Add(gp_Pnt(*(float(c) for c in corner)))
        polygon.Close()
        loft.AddWire(polygon.Wire())
    loft.Build()
    if not loft.IsDone():
        raise A8MeanderError("The loft through the strip's sections failed.")
    shape = loft.Shape()
    if not BRepCheck_Analyzer(shape).IsValid():
        raise A8MeanderError("The lofted strip is not a valid solid.")
    return shape


def _section_corners(p: A8MeanderParameters, xs, ys, zs, hw, hh):
    """The four corners of each loft section.

    Drawn across the finger: an axis-aligned rectangle in the plane y = const.

    Drawn square to the path: a rectangle of the true width, in the plane normal to
    the centreline, with its height along the spine's own normal. Near each end the
    section plane turns smoothly (over ``end_blend``) until it faces the span axis, so
    the end caps are flat against the collar faces and can be tied there; the width
    in a tilted plane is the true width over the cosine of the tilt, so the strip's
    true width stays constant through the turn.
    """
    if not p.path_normal:
        return [[(x - hw, y, z - hh), (x + hw, y, z - hh), (x + hw, y, z + hh),
                 (x - hw, y, z + hh)] for x, y, z in zip(xs, ys, zs)]
    dxdy = p.plan_slope(ys)
    dzdy = p.spine_slope(ys)
    from_end = np.minimum(ys - p.y_start, p.y_end - ys)
    ramp = np.clip(from_end / p.end_blend, 0.0, 1.0)
    beta = 1.0 - ramp * ramp * (3.0 - 2.0 * ramp)   # 1 at the ends, 0 inside
    sections = []
    for x, y, z, sx, sz, b in zip(xs, ys, zs, dxdy, dzdy, beta):
        tangent = np.array([sx, 1.0, sz])
        tangent /= np.linalg.norm(tangent)
        up = np.array([0.0, -sz, 1.0])
        up /= np.linalg.norm(up)
        normal = (1.0 - b) * tangent + b * np.array([0.0, 1.0, 0.0])
        normal /= np.linalg.norm(normal)
        across = np.cross(up, normal)
        across /= np.linalg.norm(across)
        height = np.cross(normal, across)
        height /= np.linalg.norm(height)
        half_w = p.true_width / 2.0 / float(np.dot(normal, tangent))
        c = np.array([x, y, z])
        sections.append([c - half_w * across - hh * height, c + half_w * across - hh * height,
                         c + half_w * across + hh * height, c - half_w * across + hh * height])
    return sections


def sample_sections(
    parameters: A8MeanderParameters, ys: Sequence[float]
) -> list[tuple[float, float, float]]:
    """The (y, x-centre, z-centre) the loft passes through at ``ys``, for checks."""
    ys = np.asarray(ys, dtype=float)
    return list(zip(ys.tolist(), parameters.plan_x(ys).tolist(), parameters.spine_z(ys).tolist()))
