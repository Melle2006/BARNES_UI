"""Generate the A6 sliding-end leaf-spring PIP flexures, one per leaf radius.

Every design here is sized to follow a human PIP from 0 to 105 degrees of flexion.
``scripts/a6_rom_check.py`` is the test of that claim and the source of each design's
travel; see "Sizing for a human range of motion" below.

What A6 is
----------

A pre-curved leaf is fused to a cuff on the proximal phalanx (PP). Its free end runs in
a guide on the middle-phalanx (MP) cuff, which constrains the leaf's *direction* but not
its *position along that direction*. When the joint flexes, the guide rotates with the
MP, so the leaf is forced to change its end angle and bends, storing energy and pushing
back. The end slides rather than being fixed because a leaf clamped at both ends would
also have to stretch, adding an axial stiffness that has nothing to do with the spring
being designed.

Where the sizes come from
-------------------------

The two cuffs are copied from the A8 3-turn meander (``A8_PIP_Meander_3turn_2mm``),
measured from its STEP export:

    PP collar   13.8 x 9.4 mm outside, corner R 3.55, wall 1.2, y = 0 .. 3
    MP collar   10.1 x 6.2 mm outside, corner R 2.10, wall 1.2, y = 28.86 .. 31.86

Axes match that file: Y runs along the finger from PP to MP, +Z is dorsal, and both
collars are centred on the Y axis. The A8 spine is 2 x 1.2 mm with a dorsal bow of about
0.9 mm over its 25.9 mm span, a radius of roughly 90 mm.

Why the guide is tilted
-----------------------

A circular arc between two points cannot leave both of them horizontally. Rather than
force a curved leaf into a level slot, which would preload it at rest, the anchor and
the guide are each aligned to the arc's own end tangent. Every variant is therefore
unstressed in its neutral pose, and any restoring moment comes from flexing the joint
and not from assembly. Because the guide is tilted, a tighter radius means a steeper
guide, and the guide is raised on a saddle until its distal end clears the MP collar.
That is why the tight-radius variants stand taller.

The free end and its stop
-------------------------

The guide is a narrow neck followed by a wider pocket. The leaf ends in a T-head that
lives in the pocket. It can slide the design's travel toward the PP before the head
meets the neck, which keeps the leaf from pulling out, and ``TRAVEL_DISTAL`` the other
way before it meets the end wall. Every sliding gap is ``CLEARANCE`` per side so the two
bodies can be printed in place.

Sizing for a human range of motion
----------------------------------

The first A6 set had a 2.5 mm stroke, a 4 x 1 mm leaf and a short guide centred on the
MP cuff, and stopped at 15 to 36 degrees. What changed, and why:

* **Travel is about 11 mm, tuned per radius.** As the PIP flexes, the path over the back of
  the joint lengthens, and the tip slides out to make up the difference. Past roughly
  60 degrees, a freely sliding tip has no equilibrium, so it runs on until the T-head
  meets the neck. From then on the stop carries tension and the leaf bends between two
  fixed ends. Too little travel and the leaf goes taut before 105 degrees. Too much and
  the tip arrives at the stop with a jump, which reads as a moment of negative torque (a
  snap). The travel for each radius is the centre of the window between those two
  failures, found by ``a6_rom_check.py --tune``.
* **The guide mouth sits 3.6 mm onto the MP cuff and the guide grows distally.**
  Centring a longer guide on the cuff would move its mouth toward the joint. That needs
  more slide and pulls the leaf into the knuckle. A mouth further from the joint widens
  the range of travel that passes.
* **The MP cuff runs the length of the guide**, so a guide about 15 mm long is carried
  by the cuff rather than cantilevered off it. Its cross-section is still the A8's. Its
  length is the one dimension here that has to be checked against the real MP and DIP.
* **Only R24 to R30 are offered.** At R32, a single travel passed, and a design that
  fails 0.5 mm either side is too fragile to print. Larger radii pass through the
  joint or snap.
* **The leaf is 6 mm wide** rather than 4. Width adds stiffness without adding strain,
  and 6 mm is the most the MP cuff can carry with the head and guide walls around it.

Needs CadQuery, which is not one of this project's dependencies (``pip install cadquery``).

    python scripts/make_a6_designs.py            # writes into "A6 designs/"
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

# --- Cuffs, copied from the A8 export -------------------------------------------------

#: Length of both cuffs along the finger, in mm.
CUFF_LENGTH = 3.0
#: Cuff wall thickness, in mm.
CUFF_WALL = 1.2
#: PP cuff outside width (X), height (Z) and corner radius, in mm.
PP_OUTER = (13.8, 9.4, 3.55)
#: MP cuff outside width (X), height (Z) and corner radius, in mm.
MP_OUTER = (10.1, 6.2, 2.10)
#: Where the MP cuff starts along Y, in mm. The gap between cuffs is 25.86 mm.
MP_START = 28.86

# --- Leaf -----------------------------------------------------------------------------

#: Leaf width (X) and thickness, in mm. Wider and thinner than the A8's 2 x 1.2 spine,
#: as a leaf should be: it has to bend in one plane and stay stiff in the other. Width
#: scales stiffness without changing strain. Thickness scales strain linearly and
#: stiffness as its cube, and peak strain is already the limiting quantity at 1 mm.
LEAF_WIDTH = 6.0
LEAF_THICKNESS = 1.0
#: Where the leaf leaves the PP anchor, in mm along Y. The anchor overhangs the cuff
#: by 1 mm so the leaf's root is supported past the cuff edge.
ANCHOR_EXIT = CUFF_LENGTH + 1.0
#: How far the anchor's leaf seat sits above the PP cuff top at its proximal end, in mm.
ANCHOR_LIFT = 0.2
#: Extra anchor width beyond the leaf on each side, in mm.
ANCHOR_SIDE = 1.0

# --- Guide ----------------------------------------------------------------------------

#: Gap between the leaf and the guide on every sliding face, in mm, per side.
CLEARANCE = 0.25
#: Guide wall thickness on the sides, floor and roof, in mm.
GUIDE_WALL = 0.8
#: Length of the narrow neck the leaf slides through, in mm.
NECK_LENGTH = 1.5
#: How far the T-head on the leaf tip stands out past the leaf on each side, and its
#: length along the leaf, in mm. A 6 mm leaf then makes the guide exactly as wide as the
#: MP cuff, which is why ``MAX_LEAF_WIDTH`` is 6 mm.
HEAD_OVERHANG = 1.0
HEAD_LENGTH = 1.2
#: Travel of the tip away from the PP, in mm. Only flexion is designed for, and the tip
#: never moves this way in flexion, so this is a printing gap rather than a stroke.
TRAVEL_DISTAL = 0.5
#: Distance the guide's lowest point is kept above the MP cuff top, in mm.
GUIDE_LIFT = 0.2
#: Where the guide's mouth sits along Y, in mm: 3.6 mm onto the MP cuff. The guide runs
#: distally from here, so lengthening it for more travel does not bring the mouth closer
#: to the joint. Further from the joint widens the range of travel that passes: with the
#: mouth at the cuff's proximal edge only one travel passed, for one radius.
GUIDE_MOUTH_Y = 32.5

#: Leaf radius -> travel of the tip toward the PP, in mm, from
#: ``python scripts/a6_rom_check.py --tune``. Only radii with a passing travel are listed.
TRAVEL_BY_RADIUS = {24.0: 12.5, 26.0: 11.5, 28.0: 11.5, 30.0: 11.0}

#: Leaf radii generated at the default 6 x 1 mm section, in mm.
RADII = tuple(TRAVEL_BY_RADIUS)

#: Combinations picked by ``scripts/a6_parameter_sweep.py``, generated with their own
#: section: name -> (radius, thickness, width, travel), in mm. "best" has the highest
#: worst-case mean restoring torque at the 20% strain limit. "margin" gives up some
#: torque for strain headroom and a wider travel window. See results/a6/README.md.
SWEEP_PICKS = {
    "best": (32.0, 1.8, 6.0, 11.5),
    "margin": (28.0, 1.4, 6.0, 12.0),
}

#: Widest leaf whose guide still fits within the MP cuff's width, in mm.
MAX_LEAF_WIDTH = MP_OUTER[0] - 2 * (HEAD_OVERHANG + CLEARANCE + GUIDE_WALL)


def set_section(width: float, thickness: float) -> None:
    """Change the leaf's cross-section, and every size that follows from it.

    The geometry functions read module-level sizes, so a parameter sweep changes the
    section here rather than threading it through every call.
    """
    global LEAF_WIDTH, LEAF_THICKNESS, HEAD_WIDTH, GUIDE_WIDTH, GUIDE_HALF_DEPTH
    LEAF_WIDTH, LEAF_THICKNESS = width, thickness
    HEAD_WIDTH = width + 2 * HEAD_OVERHANG
    GUIDE_WIDTH = HEAD_WIDTH + 2 * (CLEARANCE + GUIDE_WALL)
    # Guide half-depth either side of the leaf's mid-plane.
    GUIDE_HALF_DEPTH = thickness / 2 + CLEARANCE + GUIDE_WALL


set_section(LEAF_WIDTH, LEAF_THICKNESS)
DEFAULT_SECTION = (LEAF_WIDTH, LEAF_THICKNESS)


def designs() -> list[tuple[str, float, float, float, float]]:
    """Every design to generate: (file name, radius, travel, width, thickness)."""
    width, thickness = DEFAULT_SECTION
    out = [(f"A6_PIP_SlidingLeaf_R{r:g}", r, TRAVEL_BY_RADIUS[r], width, thickness)
           for r in RADII]
    for radius, thickness, width, travel in SWEEP_PICKS.values():
        out.append((f"A6_PIP_SlidingLeaf_R{radius:g}_t{thickness:g}_w{width:g}",
                    radius, travel, width, thickness))
    return out


def _add(p, q, k: float = 1.0):
    return (p[0] + k * q[0], p[1] + k * q[1])


@dataclass
class Arc:
    """A leaf centreline from A to B, bowed dorsally, in the Y-Z plane."""

    a: tuple[float, float]
    b: tuple[float, float]
    radius: float | None

    @property
    def centre(self):
        (ay, az), (by, bz) = self.a, self.b
        chord = math.hypot(by - ay, bz - az)
        uy, uz = (by - ay) / chord, (bz - az) / chord
        mid = ((ay + by) / 2, (az + bz) / 2)
        drop = math.sqrt(self.radius ** 2 - (chord / 2) ** 2)
        return (mid[0] + uz * drop, mid[1] - uy * drop)

    def tangent(self, p):
        """Unit direction of travel from A toward B at ``p``."""
        if self.radius is None:
            (ay, az), (by, bz) = self.a, self.b
            n = math.hypot(by - ay, bz - az)
            return ((by - ay) / n, (bz - az) / n)
        cy, cz = self.centre
        ry, rz = (p[0] - cy) / self.radius, (p[1] - cz) / self.radius
        return (rz, -ry)

    def normal(self, p):
        """Unit dorsal-side normal at ``p``: the tangent turned 90 degrees."""
        ty, tz = self.tangent(p)
        return (-tz, ty)

    def midpoint(self):
        if self.radius is None:
            return ((self.a[0] + self.b[0]) / 2, (self.a[1] + self.b[1]) / 2)
        cy, cz = self.centre
        (ay, az), (by, bz) = self.a, self.b
        my, mz = (ay + by) / 2 - cy, (az + bz) / 2 - cz
        n = math.hypot(my, mz)
        return (cy + self.radius * my / n, cz + self.radius * mz / n)

    def offset_midpoint(self, d: float):
        """The arc's midpoint moved ``d`` along its normal."""
        return _add(self.midpoint(), self.normal(self.midpoint()), d)

    def length(self) -> float:
        chord = math.dist(self.a, self.b)
        if self.radius is None:
            return chord
        return 2 * self.radius * math.asin(chord / (2 * self.radius))


def _angle_deg(direction) -> float:
    """Elevation of a Y-Z direction above the Y axis, in degrees."""
    return math.degrees(math.atan2(direction[1], direction[0]))


def guide_length(travel: float) -> float:
    """Guide length along its axis for a given proximal travel, in mm."""
    return NECK_LENGTH + travel + HEAD_LENGTH + TRAVEL_DISTAL + GUIDE_WALL


def solve_layout(radius: float | None, travel: float) -> Arc:
    """Place A and B so the anchor sits on the PP cuff and the guide clears the MP cuff.

    Both heights depend on the arc's end angles, which depend on both heights, so this
    is a fixed-point iteration. It settles in a handful of steps for every radius here.
    """
    pp_top = PP_OUTER[1] / 2
    mp_top = MP_OUTER[1] / 2
    a = (ANCHOR_EXIT, pp_top + 1.0)
    b = (GUIDE_MOUTH_Y, mp_top + 2.0)
    for _ in range(500):
        arc = Arc(a, b, radius)
        ta, tb = arc.tangent(a), arc.tangent(b)
        # Anchor: the leaf's underside, run back along its tangent to y = 0, sits
        # ANCHOR_LIFT above the PP cuff.
        slope_a = ta[1] / ta[0]
        new_a = (ANCHOR_EXIT, pp_top + ANCHOR_LIFT
                 + LEAF_THICKNESS / 2 / ta[0] + ANCHOR_EXIT * slope_a)
        # Guide: mouth at GUIDE_MOUTH_Y, lowest corner GUIDE_LIFT above the cuff top.
        drop = guide_length(travel) * -tb[1] + GUIDE_HALF_DEPTH * tb[0]
        new_b = (GUIDE_MOUTH_Y, mp_top + GUIDE_LIFT + drop)
        if math.dist(new_a, a) + math.dist(new_b, b) < 1e-9:
            break
        # Half steps: a long, steep guide makes the plain iteration overshoot and
        # oscillate, because raising B steepens the guide, which raises B further.
        a = ((a[0] + new_a[0]) / 2, (a[1] + new_a[1]) / 2)
        b = ((b[0] + new_b[0]) / 2, (b[1] + new_b[1]) / 2)
    else:  # pragma: no cover - would mean the layout has no solution
        raise RuntimeError(f"layout did not converge for R = {radius}")
    return Arc(a, b, radius)


# --- Solids ---------------------------------------------------------------------------

def _rounded_rect(width: float, height: float, radius: float,
                  length: float) -> cq.Workplane:
    return (cq.Workplane("XZ").rect(width, height).extrude(-length)
            .edges("|Y").fillet(radius))


def cuff(outer, start_y: float, length: float = CUFF_LENGTH) -> cq.Workplane:
    width, height, radius = outer
    shell = _rounded_rect(width, height, radius, length).cut(_rounded_rect(
        width - 2 * CUFF_WALL, height - 2 * CUFF_WALL, radius - CUFF_WALL, length))
    return shell.translate((0, start_y, 0))


def _lumen(outer, start_y: float, length: float = CUFF_LENGTH) -> cq.Workplane:
    """The cuff's bore, run long enough to clear anything that hangs into it."""
    width, height, radius = outer
    bore = _rounded_rect(width - 2 * CUFF_WALL, height - 2 * CUFF_WALL,
                         radius - CUFF_WALL, length + 20)
    return bore.translate((0, start_y - 10, 0))


def mp_cuff_length(arc: Arc, travel: float) -> float:
    """MP cuff length that reaches the guide's distal end, rounded up to 0.5 mm."""
    tb = arc.tangent(arc.b)
    end_y = arc.b[0] + guide_length(travel) * tb[0] + GUIDE_HALF_DEPTH * abs(tb[1])
    return max(CUFF_LENGTH, math.ceil((end_y - MP_START) * 2) / 2)


def _yz_prism(points, width: float) -> cq.Workplane:
    """A closed Y-Z polygon extruded symmetrically to ``width`` in X."""
    return cq.Workplane("YZ").polyline(points).close().extrude(width / 2, both=True)


def _oriented_box(origin, tangent, s0, s1, n0, n1, width) -> cq.Workplane:
    """A box running from ``s0`` to ``s1`` along ``tangent`` and ``n0`` to ``n1`` across."""
    normal = (-tangent[1], tangent[0])

    def at(s, n):
        return _add(_add(origin, tangent, s), normal, n)

    return _yz_prism([at(s0, n0), at(s1, n0), at(s1, n1), at(s0, n1)], width)


def leaf(arc: Arc, travel: float) -> cq.Workplane:
    """The leaf: a straight root in the anchor, the arc, and a straight tail with T-head."""
    half = LEAF_THICKNESS / 2
    a, b = arc.a, arc.b
    ta, tb = arc.tangent(a), arc.tangent(b)
    na, nb = arc.normal(a), arc.normal(b)
    root = _add(a, ta, -ANCHOR_EXIT / ta[0])
    tail_length = NECK_LENGTH + travel
    tail = _add(b, tb, tail_length)

    wp = (cq.Workplane("YZ").moveTo(*_add(root, na, half)).lineTo(*_add(a, na, half)))
    if arc.radius is None:
        wp = wp.lineTo(*_add(b, nb, half))
    else:
        wp = wp.threePointArc(arc.offset_midpoint(half), _add(b, nb, half))
    wp = wp.lineTo(*_add(tail, nb, half)).lineTo(*_add(tail, nb, -half)).lineTo(
        *_add(b, nb, -half))
    if arc.radius is None:
        wp = wp.lineTo(*_add(a, na, -half))
    else:
        wp = wp.threePointArc(arc.offset_midpoint(-half), _add(a, na, -half))
    body = wp.lineTo(*_add(root, na, -half)).close().extrude(LEAF_WIDTH / 2, both=True)

    head = _oriented_box(b, tb, tail_length - 0.01, tail_length + HEAD_LENGTH,
                         -half, half, HEAD_WIDTH)
    return body.union(head)


def anchor(arc: Arc) -> cq.Workplane:
    """The wedge under the leaf's root that fuses it to the PP cuff."""
    ta = arc.tangent(arc.a)
    under = _add(arc.a, arc.normal(arc.a), -LEAF_THICKNESS / 2)
    under_at_0 = _add(under, ta, -under[0] / ta[0])
    floor = PP_OUTER[1] / 2 - CUFF_WALL / 2
    pts = [(0.0, floor), (ANCHOR_EXIT, floor), under, under_at_0]
    return _yz_prism(pts, LEAF_WIDTH + 2 * ANCHOR_SIDE)


def guide(arc: Arc, travel: float) -> cq.Workplane:
    """The guide on the MP cuff: neck, pocket, end wall, and a saddle down to the cuff."""
    length = guide_length(travel)
    b, tb = arc.b, arc.tangent(arc.b)
    shell = _oriented_box(b, tb, 0.0, length, -GUIDE_HALF_DEPTH, GUIDE_HALF_DEPTH,
                          GUIDE_WIDTH)
    normal = (-tb[1], tb[0])
    low0 = _add(b, normal, -GUIDE_HALF_DEPTH)
    low1 = _add(low0, tb, length)
    seat = MP_OUTER[1] / 2 - CUFF_WALL / 2
    saddle = _yz_prism([low0, low1, (low1[0], seat), (low0[0], seat)], GUIDE_WIDTH)

    gap = LEAF_THICKNESS / 2 + CLEARANCE
    neck = _oriented_box(b, tb, -1.0, NECK_LENGTH + 0.01, -gap, gap,
                         LEAF_WIDTH + 2 * CLEARANCE)
    pocket_end = length - GUIDE_WALL
    pocket = _oriented_box(b, tb, NECK_LENGTH, pocket_end, -gap, gap,
                           HEAD_WIDTH + 2 * CLEARANCE)
    return shell.union(saddle).cut(neck).cut(pocket)


def build(radius: float | None, travel: float):
    arc = solve_layout(radius, travel)
    proximal = cuff(PP_OUTER, 0.0).union(anchor(arc)).union(leaf(arc, travel)).cut(
        _lumen(PP_OUTER, 0.0))
    mp_length = mp_cuff_length(arc, travel)
    distal = cuff(MP_OUTER, MP_START, mp_length).union(guide(arc, travel)).cut(
        _lumen(MP_OUTER, MP_START, mp_length))
    return arc, proximal, distal


def summary(arc: Arc, travel: float, proximal, distal) -> dict:
    a, b = arc.a, arc.b
    apex = max(arc.midpoint()[1], a[1], b[1]) + LEAF_THICKNESS / 2
    interference = proximal.intersect(distal).val().Volume() if proximal.intersect(
        distal).solids().size() else 0.0
    return {
        "radius_mm": "flat" if arc.radius is None else f"{arc.radius:g}",
        "leaf_thickness_mm": LEAF_THICKNESS,
        "leaf_width_mm": LEAF_WIDTH,
        "travel_mm": travel,
        "guide_length_mm": guide_length(travel),
        "mp_cuff_length_mm": mp_cuff_length(arc, travel),
        "free_arc_length_mm": round(arc.length(), 2),
        "chord_mm": round(math.dist(a, b), 2),
        "anchor_angle_deg": round(_angle_deg(arc.tangent(a)), 1),
        "guide_angle_deg": round(_angle_deg(arc.tangent(b)), 1),
        "bend_angle_deg": round(_angle_deg(arc.tangent(a)) - _angle_deg(arc.tangent(b)), 1),
        "top_of_leaf_z_mm": round(apex, 2),
        "height_above_pp_cuff_mm": round(apex - PP_OUTER[1] / 2, 2),
        "leaf_guide_interference_mm3": round(interference, 4),
        "pp_body_volume_mm3": round(proximal.val().Volume(), 1),
        "mp_body_volume_mm3": round(distal.val().Volume(), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "A6 designs")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, radius, travel, width, thickness in designs():
        set_section(width, thickness)
        arc, proximal, distal = build(radius, travel)
        both = cq.Compound.makeCompound([proximal.val(), distal.val()])
        cq.exporters.export(cq.Workplane().add(both), str(args.out / f"{name}.STEP"))
        cq.exporters.export(cq.Workplane().add(both), str(args.out / f"{name}.STL"),
                            tolerance=0.01, angularTolerance=0.1)
        row = {"file": name, **summary(arc, travel, proximal, distal)}
        rows.append(row)
        print(row)

    with open(args.out / "A6_variants.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
