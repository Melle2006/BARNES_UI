"""Parametric serpentine (meander) flexure template.

Generates a meander flexure from parameters rather than morphing an imported solid.
This is the approach ``docs/01-feasibility-assessment.md`` committed to for Module E:
stretching an arbitrary solid to fit distorts cross-sections, and since bending
stiffness scales with the cube of width, a 10 per cent distortion is a 33 per cent
stiffness change that nobody asked for and nobody sees.

It arrives ahead of Phase 4 because Phase 2 needs a meander to develop against. The
A3 twin-strap part is a simple arch; the A8 family is a serpentine that doubles back,
which the axis-sweep centreline extractor explicitly refuses. Without a meander there
was nothing to build path-following extraction against.

**This is not the A8 part.** It is a reference meander with exactly known parameters.
It cannot validate anything about the real A8 design -- only a STEP export of the
actual part can do that. What it does provide is a geometry with analytically known
arc length, volume and section, which is what the extraction and mechanics code can be
verified against.

Construction
------------

The solid is a boolean union of straight boxes and annular half-sectors. That is
deliberately chosen over sweeping a profile along a wire: pipe-shell sweeps fail or
self-intersect at the tight reversals a meander is made of, whereas boxes and sector
solids are primitives the boolean kernel handles reliably.

The segments butt exactly rather than overlapping. A straight run's centreline spans
``x`` from 0 to ``run_length``; the turn's arc begins at ``x = run_length`` on the same
centreline, and the sector's starting radial edge coincides exactly with the box's end
face. That matters for verification: with no overlap and constant width, the volume is
exactly ``width * thickness * centreline_length`` for both straight and circular-arc
segments, which gives an independent analytical check on the generated solid.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from ...cad._occ import occ, require_kernel

logger = logging.getLogger(__name__)

__all__ = ["MeanderParameters", "build_meander", "MeanderError"]


class MeanderError(ValueError):
    """The requested meander parameters cannot produce a valid solid."""


@dataclass(frozen=True)
class MeanderParameters:
    """Geometry of a serpentine flexure.

    The meander lies in the XY plane and is extruded along Z. Straight runs are
    parallel to X and stacked along Y, joined by 180-degree turns at alternating ends,
    so the member's overall span is along Y and each run reverses along X.

    Used at a finger joint, the joint axis would be parallel to X, so bending acts on
    the ``width`` dimension -- which is why ``width`` is the in-plane dimension and
    ``thickness`` the out-of-plane one, matching the convention in
    ``docs/01-feasibility-assessment.md`` where ``I = t * w^3 / 12``.
    """

    #: Length of each straight run, measured along its centreline (mm).
    run_length: float = 12.0
    #: Number of straight runs. Turns number one fewer.
    n_runs: int = 4
    #: Centreline-to-centreline spacing of adjacent runs, along Y (mm).
    pitch: float = 3.0
    #: Strap width, in-plane, the dimension bending acts on (mm).
    width: float = 1.0
    #: Extrusion depth, out of plane (mm).
    thickness: float = 1.2
    #: Length of the attachment tab at each end, along X (mm). Zero for none.
    tab_length: float = 0.0
    #: Width of the attachment tabs, along Y (mm). Ignored when tab_length is zero.
    tab_width: float = 4.0

    def __post_init__(self) -> None:
        if self.n_runs < 2:
            raise MeanderError("A meander needs at least 2 runs to have a turn.")
        if self.width <= 0 or self.thickness <= 0 or self.run_length <= 0:
            raise MeanderError("width, thickness and run_length must be positive.")
        if self.pitch <= self.width:
            raise MeanderError(
                f"pitch ({self.pitch} mm) must exceed width ({self.width} mm), "
                "otherwise adjacent runs merge into a solid block and the member is no "
                "longer a meander."
            )
        # A micron, not zero. Below roughly this the inner radius is comparable to the
        # modelling tolerance and the boolean produces a degenerate or invalid body
        # rather than a thin one. Manufacturability is a separate, much coarser test --
        # see minimum_feature_size.
        if self.inner_radius <= 1.0e-6:
            raise MeanderError(
                f"The turn inner radius would be {self.inner_radius:.3e} mm, which is "
                "at or below the modelling tolerance and cannot produce a valid solid. "
                "Increase pitch or reduce width."
            )

    # -- derived geometry ------------------------------------------------------

    @property
    def n_turns(self) -> int:
        return self.n_runs - 1

    @property
    def turn_radius(self) -> float:
        """Centreline radius of a turn (mm). Half the pitch, by construction."""
        return self.pitch / 2.0

    @property
    def inner_radius(self) -> float:
        """Inner edge radius of a turn (mm). The tightest feature in the part."""
        return self.turn_radius - self.width / 2.0

    @property
    def outer_radius(self) -> float:
        return self.turn_radius + self.width / 2.0

    @property
    def centreline_length(self) -> float:
        """Exact centreline arc length (mm).

        Straight runs plus semicircular turns:
        ``n_runs * run_length + n_turns * pi * turn_radius``.

        Analytical, so it is the reference the extracted arc length is checked against.
        """
        return (
            self.n_runs * self.run_length
            + self.n_turns * math.pi * self.turn_radius
        )

    @property
    def expected_volume(self) -> float:
        """Exact volume of the meander body, excluding tabs (mm^3).

        ``width * thickness * centreline_length``. This holds exactly for both segment
        types because an annular sector of constant width has area
        ``pi * pitch * width / 2``, which equals its centreline arc ``pi * pitch / 2``
        times the width. Since the segments butt rather than overlap, the total is
        simply the sum.
        """
        return self.width * self.thickness * self.centreline_length

    @property
    def envelope(self) -> tuple[float, float, float]:
        """Overall bounding-box size (mm), excluding tabs.

        Along X the turns bulge a full ``outer_radius`` beyond each end of the straight
        runs, not merely half a width -- the first draft of this used ``width`` and
        predicted 13.0 mm where the built solid measured 16.0 mm. The solid was right.

        Along Y the outermost turn reaches exactly the far edge of the next run
        (``centre + outer_radius == y_next + width/2``), so the turns are flush and
        contribute nothing beyond the runs themselves.
        """
        x_extent = self.run_length + 2.0 * self.outer_radius
        y_extent = (self.n_runs - 1) * self.pitch + self.width
        return (x_extent, y_extent, self.thickness)

    @property
    def minimum_feature_size(self) -> float:
        """Smallest dimension a printer has to resolve (mm).

        The lesser of the strap width and the inner turn radius. Checked against the
        printer's capability before a design is accepted, per Phase 4's safety checks.
        """
        return min(self.width, self.inner_radius)

    def describe(self) -> str:
        x, y, z = self.envelope
        return (
            f"Meander: {self.n_runs} runs of {self.run_length} mm, pitch {self.pitch} "
            f"mm, width {self.width} mm, thickness {self.thickness} mm. "
            f"Centreline {self.centreline_length:.4f} mm, "
            f"envelope {x:.3f} x {y:.3f} x {z:.3f} mm, "
            f"inner turn radius {self.inner_radius:.4f} mm."
        )

    def centreline_points(self, per_run: int = 40, per_turn: int = 40):
        """Analytical centreline as a polyline, for comparison against extraction.

        Returned as a list of (x, y, z) at the mid-thickness plane. This is the ground
        truth the traced centreline is measured against -- the one case in this project
        where the true answer is known exactly.
        """
        points: list[tuple[float, float, float]] = []
        z = self.thickness / 2.0

        for run in range(self.n_runs):
            y = run * self.pitch
            forward = run % 2 == 0
            x0, x1 = (0.0, self.run_length) if forward else (self.run_length, 0.0)
            for i in range(per_run):
                t = i / (per_run - 1)
                points.append((x0 + (x1 - x0) * t, y, z))

            if run == self.n_runs - 1:
                break

            # Turn joining this run to the next, centred beyond the run's far end.
            #
            # The start angle is -pi/2 for both parities, not +pi/2 for backward runs.
            # Whichever way a run travels, it finishes directly below its turn centre
            # -- the centre sits at y + turn_radius above the run's own centreline --
            # so the arc always begins at -pi/2. Only the sweep direction differs:
            # forward runs sweep through +X, backward runs through -X.
            #
            # Getting this wrong put a gap of one pitch at every backward turn and
            # inflated the sampled path length by 9.6 per cent against this class's
            # own centreline_length. The built solid was unaffected -- it is assembled
            # from booleans, not from this polyline -- but this is the ground truth the
            # traced centreline is compared against, so an error here would have been
            # blamed on the tracer.
            centre_x = self.run_length if forward else 0.0
            centre_y = y + self.turn_radius
            start = -math.pi / 2.0
            direction = 1.0 if forward else -1.0
            for i in range(1, per_turn):
                angle = start + direction * math.pi * (i / per_turn)
                points.append(
                    (
                        centre_x + self.turn_radius * math.cos(angle),
                        centre_y + self.turn_radius * math.sin(angle),
                        z,
                    )
                )
        return points


def build_meander(parameters: MeanderParameters) -> Any:
    """Build the meander as an OpenCASCADE solid.

    Raises :class:`MeanderError` if the boolean union fails, rather than returning a
    partial body -- a half-fused meander would still display and still measure, and
    would be wrong.
    """
    require_kernel()
    p = parameters

    solids: list[Any] = []

    for run in range(p.n_runs):
        y = run * p.pitch
        solids.append(_straight_run(p, y))
        if run < p.n_runs - 1:
            solids.append(_turn(p, run, y))

    if p.tab_length > 0:
        solids.extend(_tabs(p))

    result = solids[0]
    for solid in solids[1:]:
        fuse = occ.BRepAlgoAPI_Fuse(result, solid)
        fuse.Build()
        if not fuse.IsDone():
            raise MeanderError(
                "The boolean union of the meander segments failed. Check that pitch "
                "exceeds width and that the inner turn radius is positive."
            )
        result = fuse.Shape()

    # Remove the internal faces left where segments butt together. Without this the
    # body carries a seam face at every junction, which inflates the face count and
    # gives the mesher artificial edges to refine around in Phase 3.
    try:
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

        unifier = ShapeUpgrade_UnifySameDomain(result, True, True, True)
        unifier.Build()
        result = unifier.Shape()
    except Exception as exc:  # pragma: no cover - cosmetic step only
        logger.debug("Could not unify coplanar faces on the meander: %s", exc)

    return result


def _straight_run(p: MeanderParameters, y: float) -> Any:
    """One straight run as a box, centred on the run's centreline."""
    return occ.BRepPrimAPI_MakeBox(
        occ.gp_Pnt(0.0, y - p.width / 2.0, 0.0),
        p.run_length,
        p.width,
        p.thickness,
    ).Shape()


def _turn(p: MeanderParameters, run: int, y: float) -> Any:
    """One 180-degree turn as an annular half-sector.

    Built as an outer cylindrical sector minus an inner full cylinder. The sector's
    sweep starts from the axis system's X direction and runs counter-clockwise, so the
    X direction is set to point along the radial edge where the straight run ends --
    which is what makes the two butt exactly instead of overlapping or leaving a gap.
    """
    forward = run % 2 == 0
    centre_x = p.run_length if forward else 0.0
    centre_y = y + p.turn_radius

    # Right-hand turns sweep from -Y round through +X to +Y; left-hand ones from
    # +Y round through -X to -Y.
    radial = occ.gp_Dir(0.0, -1.0, 0.0) if forward else occ.gp_Dir(0.0, 1.0, 0.0)
    axis = occ.gp_Ax2(
        occ.gp_Pnt(centre_x, centre_y, 0.0), occ.gp_Dir(0.0, 0.0, 1.0), radial
    )

    outer = occ.BRepPrimAPI_MakeCylinder(
        axis, p.outer_radius, p.thickness, math.pi
    ).Shape()
    inner = occ.BRepPrimAPI_MakeCylinder(
        occ.gp_Ax2(
            occ.gp_Pnt(centre_x, centre_y, -p.thickness),
            occ.gp_Dir(0.0, 0.0, 1.0),
        ),
        p.inner_radius,
        3.0 * p.thickness,
    ).Shape()

    cut = occ.BRepAlgoAPI_Cut(outer, inner)
    cut.Build()
    if not cut.IsDone():
        raise MeanderError(f"Could not form the annular sector for turn {run}.")
    return cut.Shape()


def _tabs(p: MeanderParameters) -> list[Any]:
    """Attachment pads at the two free ends of the meander.

    The first run starts at x = 0 and the last ends at x = 0 or run_length depending on
    parity, so the tabs are placed accordingly rather than assumed symmetric.
    """
    tabs: list[Any] = []
    half = p.tab_width / 2.0

    # Start of the first run: extends in -X from x = 0.
    tabs.append(
        occ.BRepPrimAPI_MakeBox(
            occ.gp_Pnt(-p.tab_length, -half, 0.0),
            p.tab_length, p.tab_width, p.thickness,
        ).Shape()
    )

    last_y = (p.n_runs - 1) * p.pitch
    if (p.n_runs - 1) % 2 == 0:
        # Last run runs forward, finishing at x = run_length: tab extends in +X.
        origin = occ.gp_Pnt(p.run_length, last_y - half, 0.0)
    else:
        origin = occ.gp_Pnt(-p.tab_length, last_y - half, 0.0)
    tabs.append(
        occ.BRepPrimAPI_MakeBox(
            origin, p.tab_length, p.tab_width, p.thickness
        ).Shape()
    )
    return tabs
