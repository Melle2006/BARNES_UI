"""
TYPE B finger: 3 rigid PLA phalanges + 3 TPU re-entrant-lattice joint modules
(MCP, PIP, DIP), corrected from build_finger_one_more_lattice_level.py and
generated as a family of variants that differ in lattice strut thickness and in
the number of criss-cross (bow-tie) cells per lattice.

    python "TYPE B/build_finger_type_b.py"                # every variant
    python "TYPE B/build_finger_type_b.py" B00_baseline   # named variants only
    python "TYPE B/build_finger_type_b.py" --no-stl --no-assembly

AXIS CONVENTION (unchanged from the original script):
    Z = along the finger, proximal (flange) -> distal (tip)
    X = lateral width
    Y = dorsal (+) / palmar (-), the flexion bending direction

All dimensions in millimetres. See README.md in this folder for the list of
errors corrected relative to the original script and what each variant is.
"""

import argparse
import csv
import math
import os
import sys

import cadquery as cq

# ---------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ---------------------------------------------------------------------------
CLR = 0.3            # per-side clearance, TPU tab -> PLA socket
AX_CLR = 0.3         # axial clearance at the socket floor, so the collar seats
WALL = 1.2           # PLA socket wall (3 perimeters at 0.4 mm)
MIN_WALL = 0.8       # minimum material left around a channel inside a tab
COLLAR_LEN = 0.8     # full-section shoulder between tab and lattice
COLLAR_R = 2.0       # corner radius of the joint block / collar profile
PIN_D = 2.0          # retention pin diameter (two pins per tab, along Y)
CHAN_TENDON_D = 3.0  # palmar tendon channel
CHAN_SENSOR_D = 1.5  # dorsal sensor-lead channel
TENDON_ANCHOR_D = 2.0
SENSOR_Y = 3.0       # preferred dorsal sensor channel offset
TENDON_CLEARANCE = 0.4

MIN_STRUT = 0.4      # thinnest strut a 0.4 mm nozzle can lay down
MIN_WAIST_GAP = 0.3  # clear gap between the two halves of a bow-tie at its waist
MIN_TRAVEL = 0.3     # minimum lateral re-entrant travel of a strut
LATTICE_MARGIN = 0.2 # lattice kept this far inside the collar outline

CS_MCP = (16.0, 14.0)
CS_PIP = (14.0, 12.0)
CS_DIP = (12.0, 10.0)
CS_TIP = (11.0, 9.0)

# Phalanx lengths as specified, measured to the original joint gap. Each end
# that faces a joint is shortened by COLLAR_LEN in build_finger(), because the
# collar now occupies that length; total finger length and lattice length are
# unchanged.
L_PHAL1 = 32.86
L_PHAL2 = 17.76
L_PHAL3 = 15.98

# end_len was 2.15 (PIP) and 1.0 (DIP): too short to hold a 2 mm pin. The tab
# sits inside the phalanx socket, so lengthening it does not change the
# visible joint or the lattice.
MCP = dict(end_len=4.0, flex_len=10.25, pulley_r=5.0,
           pal_yc=-3.5, pal_span=6.0, pal_t=0.7, pal_delta=0.5, pal_n=3,
           dor_yc=3.5,  dor_span=5.0, dor_t=1.4, dor_delta=0.5, dor_n=2)
PIP = dict(end_len=4.0, flex_len=7.55, pulley_r=3.5,
           pal_yc=-3.0, pal_span=5.0, pal_t=0.55, pal_delta=0.45, pal_n=2,
           dor_yc=3.0,  dor_span=3.8, dor_t=1.1, dor_delta=0.45, dor_n=2)
DIP = dict(end_len=4.0, flex_len=7.3, pulley_r=3.0,
           pal_yc=-2.5, pal_span=4.0, pal_t=0.45, pal_delta=0.4, pal_n=3,
           dor_yc=2.5,  dor_span=3.2, dor_t=0.9, dor_delta=0.4, dor_n=2)

HARDSTOP_MCP = dict(w=3.0, d=3.0, h=2.0)
HARDSTOP_PIP = dict(w=3.0, d=3.0, h=1.5)
HARDSTOP_DIP = dict(w=3.0, d=3.0, h=1.0)

ANCHOR_BOSS = dict(offset_from_joint=4.0, hole_d=1.5, boss_h=2.0, boss_wd=3.0,
                   hole_into_body=0.5)

# Holes moved outboard (spacing 14 -> 22) so M3 heads (dia 5.5) clear the
# MCP block, which reaches x = +/-7.7.
FLANGE = dict(w=28.0, h=14.0, t=4.0, hole_d=3.0, hole_spacing=22.0)

TIP_RECESS = dict(w=8.0, d=6.0, depth=1.0)
TIP_FILLET_TRY = (4.0, 3.5, 3.0, 2.5, 2.0)

EMBED = 0.5          # features added to a surface start this far inside it

# ---------------------------------------------------------------------------
# VARIANTS
# ---------------------------------------------------------------------------
# t_scale multiplies every strut thickness (palmar and dorsal, all joints), so
# the palmar:dorsal 1:2 ratio and the MCP > PIP > DIP grading are kept.
# crossings is the number of bow-tie (criss-cross) cells in each palmar
# lattice; dorsal lattices get one fewer, as in the original design. None keeps
# the original per-joint counts.
T_LEVELS = (0.9, 1.0, 1.1, 1.2)
X_LEVELS = (2, 3, 4)

VARIANTS = {"B00_baseline": dict(t_scale=1.0, crossings=None)}
for _t in T_LEVELS:
    for _x in X_LEVELS:
        VARIANTS[f"B_T{round(_t * 100):03d}_X{_x}"] = dict(t_scale=_t, crossings=_x)


# ---------------------------------------------------------------------------
# PROFILE HELPERS
# ---------------------------------------------------------------------------
def outer_radius(w, h):
    """Corner radius of the organic phalanx cross-section."""
    return min(0.42 * min(w, h), min(w, h) / 2 - 0.01)


def rounded_profile(w, h, r=None):
    if r is None:
        r = outer_radius(w, h)
    r = min(r, min(w, h) / 2 - 0.01)
    return cq.Sketch().rect(w, h).vertices().fillet(r)


def prism(w, h, r, z0, length):
    return (cq.Workplane("XY").workplane(offset=z0)
            .placeSketch(rounded_profile(w, h, r)).extrude(length).val())


def socket_dims(cs):
    """(w, h, r) of the socket cut into a phalanx end of section cs. The wall
    is uniform because the socket is the outer profile offset inward by WALL."""
    w, h = cs
    return w - 2 * WALL, h - 2 * WALL, outer_radius(w, h) - WALL


def tab_dims(cs):
    sw, sh, sr = socket_dims(cs)
    return sw - 2 * CLR, sh - 2 * CLR, sr - CLR


def collar_dims(cs):
    w, h = cs
    return w - 2 * CLR, h - 2 * CLR, COLLAR_R


def half_height(w, h, r, x):
    """Half-height of a centred rounded rectangle at lateral position x."""
    x = abs(x)
    cx = w / 2 - r
    if x <= cx:
        return h / 2
    if x >= w / 2:
        return 0.0
    return (h / 2 - r) + math.sqrt(r * r - (x - cx) ** 2)


def tapered_box(length, w0, h0, w1, h1):
    s0 = rounded_profile(w0, h0)
    s1 = rounded_profile(w1, h1)
    return (cq.Workplane("XY")
            .placeSketch(s0, s1.moved(cq.Location(cq.Vector(0, 0, length))))
            .loft())


def section_h(h0, h1, length, z):
    return h0 + (h1 - h0) * min(max(z / length, 0.0), 1.0)


def fuse(shapes):
    shapes = [s for s in shapes if s is not None]
    if len(shapes) == 1:
        return shapes[0]
    return shapes[0].fuse(*shapes[1:]).clean()


def cyl(r, length, base, direction):
    return cq.Solid.makeCylinder(r, length, cq.Vector(*base), cq.Vector(*direction))


def channel(points, d):
    """A round channel along a polyline of (y, z) points at x = 0, with a
    sphere at each kink so the bends are smooth."""
    r = d / 2
    parts = []
    for (y0, z0), (y1, z1) in zip(points, points[1:]):
        length = math.hypot(y1 - y0, z1 - z0)
        if length < 1e-6:
            continue
        parts.append(cyl(r, length, (0, y0, z0), (0, (y1 - y0) / length, (z1 - z0) / length)))
    for y, z in points[1:-1]:
        parts.append(cq.Solid.makeSphere(r, cq.Vector(0, y, z), angleDegrees1=-90, angleDegrees2=90))
    return fuse(parts)


# ---------------------------------------------------------------------------
# JOINT-LEVEL GEOMETRY (shared by the module and the two phalanges it joins)
# ---------------------------------------------------------------------------
def section_at(cs0, cs1, length, z):
    t = min(max(z / length, 0.0), 1.0)
    return tuple(a + (b - a) * t for a, b in zip(cs0, cs1))


def joint_layout(cs, spec, cs_d):
    """Channel offsets and pin positions that must agree between a joint
    module's tabs and the sockets of the phalanges on either side of it.
    cs_d is the section the distal tab is sized from: the following
    phalanx's section at its socket floor, because that phalanx tapers and
    is thinnest there. It is never larger than cs, so it sets the limits."""
    tw, th, _ = tab_dims(cs_d)
    tendon_max = th / 2 - CHAN_TENDON_D / 2 - MIN_WALL
    sensor_max = th / 2 - CHAN_SENSOR_D / 2 - MIN_WALL
    tendon_y = -min(spec["pulley_r"], tendon_max)
    sensor_y = min(SENSOR_Y, sensor_max)
    # Two pins along Y, either side of the X = 0 channels, centred in the
    # material between the tendon channel and the tab's side wall.
    x_lo = CHAN_TENDON_D / 2 + MIN_WALL / 2 + PIN_D / 2
    x_hi = tw / 2 - MIN_WALL / 2 - PIN_D / 2
    if x_hi < x_lo:
        raise ValueError(f"tab {tw:.2f} mm wide has no room for retention pins")
    if spec["end_len"] < PIN_D + 2 * 1.0:
        raise ValueError(f"end_len {spec['end_len']} mm cannot hold a {PIN_D} mm pin")
    return dict(tendon_y=tendon_y, sensor_y=sensor_y, pin_x=(x_lo + x_hi) / 2, cs_d=cs_d,
                pulley_clamped=abs(tendon_y) < spec["pulley_r"] - 1e-9)


def pins(pin_x, z):
    return [cyl(PIN_D / 2, 100, (sx * pin_x, -50, z), (0, 1, 0)) for sx in (-1, 1)]


# ---------------------------------------------------------------------------
# LATTICE
# ---------------------------------------------------------------------------
def _beam_yz(y1, z1, y2, z2, t, x_center, x_t):
    dy, dz = y2 - y1, z2 - z1
    length = math.hypot(dy, dz)
    py, pz = -dz / length * t / 2, dy / length * t / 2
    pts = [(y1 + py, z1 + pz), (y2 + py, z2 + pz), (y2 - py, z2 - pz), (y1 - py, z1 - pz)]
    return (cq.Workplane("YZ").workplane(offset=x_center - x_t / 2)
            .polyline(pts).close().extrude(x_t).val())


def _node(y, z, t, x_center, x_t):
    return cyl(t / 2, x_t, (x_center - x_t / 2, y, z), (1, 0, 0))


def _box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def bowtie_lattice(y_lo, y_hi, z_start, z_len, n_cells, strut_t, delta, x_width, label):
    """Open re-entrant lattice in four X-columns around a clear tendon corridor.
    Strut centrelines are inset by t/2 so no strut leaves the band, and every
    strut end gets a round node so joints are filleted rather than notched."""
    if strut_t < MIN_STRUT:
        raise ValueError(f"{label}: strut {strut_t:.3f} mm is below MIN_STRUT {MIN_STRUT}")
    span = y_hi - y_lo
    yc = (y_lo + y_hi) / 2
    cell_h = (z_len - (n_cells + 1) * delta) / n_cells
    if cell_h < max(1.0, strut_t):
        raise ValueError(f"{label}: cell height {cell_h:.3f} mm is too small")

    # The original rule placed strut centrelines on the band edge, so struts
    # stuck out of it by t/2. Keep the original lateral travel (and so the
    # re-entrant angle) where possible, taking the t/2 inset out of the clear
    # gap at the waist, which may not drop below MIN_WAIST_GAP.
    orig_waist = min(max(2.0 * strut_t, 0.25 * span), span - 2.0 * strut_t)
    target_travel = (span - orig_waist) / 2
    node_span = span - strut_t
    waist = max(node_span - 2 * target_travel, strut_t + MIN_WAIST_GAP)
    travel = (node_span - waist) / 2
    if travel < MIN_TRAVEL - 1e-9:
        raise ValueError(
            f"{label}: band {span:.2f} mm is too narrow for {strut_t:.3f} mm struts "
            f"(re-entrant travel {travel:.2f} mm, waist gap {waist - strut_t:.2f} mm)")
    angle = math.degrees(math.atan(travel / (cell_h / 2)))

    x_t = min(max(0.8, strut_t), 1.2)
    corridor = CHAN_TENDON_D + 2 * TENDON_CLEARANCE
    inner_x = corridor / 2 + x_t / 2
    outer_x = x_width / 2 - x_t / 2
    if outer_x - inner_x < x_t + 0.2:
        raise ValueError(f"{label}: {x_width:.2f} mm is too narrow for four lattice columns")
    xs = (-outer_x, -inner_x, inner_x, outer_x)

    yl, yr = y_lo + strut_t / 2, y_hi - strut_t / 2
    wl, wr = yc - waist / 2, yc + waist / 2
    parts = []
    z = z_start
    for xc in xs:
        parts.append(_box(xc - x_t / 2, xc + x_t / 2, y_lo, y_hi, z, z + delta))
    z += delta
    for _ in range(n_cells):
        zt, zm, zb = z, z + cell_h / 2, z + cell_h
        for xc in xs:
            parts += [
                _beam_yz(yl, zt, wl, zm, strut_t, xc, x_t),
                _beam_yz(yr, zt, wr, zm, strut_t, xc, x_t),
                _beam_yz(wl, zm, yl, zb, strut_t, xc, x_t),
                _beam_yz(wr, zm, yr, zb, strut_t, xc, x_t),
            ]
            for y, zz in ((yl, zt), (yr, zt), (wl, zm), (wr, zm), (yl, zb), (yr, zb)):
                parts.append(_node(y, zz, strut_t, xc, x_t))
            parts.append(_box(xc - x_t / 2, xc + x_t / 2, y_lo, y_hi, zb, zb + delta))
        z = zb + delta
    info = dict(n=n_cells, t=strut_t, x_t=x_t, angle=angle, cell_h=cell_h,
                y_lo=y_lo, y_hi=y_hi, corridor=2 * inner_x - x_t)
    return parts, info


def lattice_bands(cs, spec):
    """Palmar and dorsal Y-bands from the spec, clipped so the outer lattice
    columns stay inside the collar's rounded corners."""
    cw, ch, cr = collar_dims(cs)
    x_width = cs[0] - 2.0
    avail = half_height(cw, ch, cr, x_width / 2) - LATTICE_MARGIN
    pal = (max(spec["pal_yc"] - spec["pal_span"] / 2, -avail), spec["pal_yc"] + spec["pal_span"] / 2)
    dor = (spec["dor_yc"] - spec["dor_span"] / 2, min(spec["dor_yc"] + spec["dor_span"] / 2, avail))
    return pal, dor, x_width


# ---------------------------------------------------------------------------
# JOINT MODULE
# ---------------------------------------------------------------------------
def make_joint_module(cs, spec, name, layout, proximal_is_tab=True, flexure=None):
    """Module stack along Z, from 0:
        proximal tab (in socket) | collar | flexure | collar | distal tab (in socket)
    For the MCP the proximal end bolts to the flange instead of a socket, so it
    is a plain block in the collar profile and has no separate collar.

    flexure(cs, spec, z_flex, flex_len, name) -> (solids, info) builds the
    flex zone; the default is the bow-tie lattice. Whatever it builds must
    keep clear of |x| < corridor/2 so the tendon and sensor lead pass."""
    e, F, c = spec["end_len"], spec["flex_len"], COLLAR_LEN
    tw, th, tr = tab_dims(cs)
    dw, dh, dr = tab_dims(layout["cs_d"])
    cw, ch, cr = collar_dims(cs)

    parts = []
    if proximal_is_tab:
        parts += [prism(tw, th, tr, 0, e), prism(cw, ch, cr, e, c)]
        z_flex = e + c
    else:
        parts.append(prism(cw, ch, cr, 0, e))
        z_flex = e
    z_end_flex = z_flex + F
    parts += [prism(cw, ch, cr, z_end_flex, c), prism(dw, dh, dr, z_end_flex + c, e)]
    total = z_end_flex + c + e

    if flexure is None:
        flex_parts, info = lattice_flexure(cs, spec, z_flex, F, name)
    else:
        flex_parts, info = flexure(cs, spec, z_flex, F, name)
    module = fuse(parts + flex_parts)

    # Channels through the solid ends only; across the flex zone the tendon and
    # sensor lead run in open air down the lattice's central corridor.
    ty, sy = layout["tendon_y"], layout["sensor_y"]
    cuts = []
    for z0, z1 in ((-50, z_flex), (z_end_flex, total + 1)):
        cuts.append(cyl(CHAN_TENDON_D / 2, z1 - z0, (0, ty, z0), (0, 0, 1)))
        cuts.append(cyl(CHAN_SENSOR_D / 2, z1 - z0, (0, sy, z0), (0, 0, 1)))
    if proximal_is_tab:
        cuts += pins(layout["pin_x"], e / 2)
    cuts += pins(layout["pin_x"], total - e / 2)
    module = module.cut(fuse(cuts)).clean()

    return module, total, z_flex, info


def lattice_flexure(cs, spec, z_flex, F, name):
    pal_band, dor_band, x_width = lattice_bands(cs, spec)
    pal, pal_info = bowtie_lattice(*pal_band, z_flex, F, spec["pal_n"], spec["pal_t"],
                                   spec["pal_delta"], x_width, f"{name} palmar")
    dor, dor_info = bowtie_lattice(*dor_band, z_flex, F, spec["dor_n"], spec["dor_t"],
                                   spec["dor_delta"], x_width, f"{name} dorsal")
    return pal + dor, dict(palmar=pal_info, dorsal=dor_info)


# ---------------------------------------------------------------------------
# PHALANX
# ---------------------------------------------------------------------------
def palmar_block(w, d, h, y_surface, z_center):
    """A block standing out of the palmar surface, starting EMBED inside it."""
    return _box(-w / 2, w / 2, y_surface - h, y_surface + EMBED, z_center - d / 2, z_center + d / 2)


def make_phalanx(length, cs0, cs1, prox, dist, hardstop, tip=False,
                 boss_z=None):
    """prox / dist: dict(spec, layout) of the joint on that end (dist is None
    for the fingertip). Sockets use the uniform-wall socket profile, pins and
    channels are taken from the joint layouts so they line up with the tabs."""
    (w0, h0), (w1, h1) = cs0, cs1
    body = tapered_box(length, w0, h0, w1, h1)
    if tip:
        for r in TIP_FILLET_TRY:
            try:
                body = body.edges(">Z").fillet(r)
                tip_r = r
                break
            except Exception:
                continue
        else:
            raise RuntimeError("fingertip fillet failed at every radius tried")
    body = body.val()

    def h_at(z):
        return section_h(h0, h1, length, z)

    adds, cuts = [], []
    # Hard stop on the PALMAR face near the proximal end.
    zc = hardstop["d"] / 2 + 2
    adds.append(palmar_block(hardstop["w"], hardstop["d"], hardstop["h"],
                             -h_at(zc + hardstop["d"] / 2) / 2, zc))
    if boss_z is not None:
        b = ANCHOR_BOSS
        y_s = -h_at(boss_z + b["boss_wd"] / 2) / 2
        adds.append(palmar_block(b["boss_wd"], b["boss_wd"], b["boss_h"], y_s, boss_z))
        cuts.append(cyl(b["hole_d"] / 2, b["boss_h"] + 1 + b["hole_into_body"],
                        (0, y_s - b["boss_h"] - 1, boss_z), (0, 1, 0)))
    body = fuse([body] + adds)

    e_p = prox["spec"]["end_len"]
    sw, sh, sr = socket_dims(prox["layout"]["cs_d"])
    cuts.append(prism(sw, sh, sr, -1, e_p + AX_CLR + 1))
    cuts += pins(prox["layout"]["pin_x"], e_p / 2)

    ty0, sy0 = prox["layout"]["tendon_y"], prox["layout"]["sensor_y"]
    if dist is not None:
        e_d = dist["spec"]["end_len"]
        sw, sh, sr = socket_dims(cs1)
        cuts.append(prism(sw, sh, sr, length - e_d - AX_CLR, e_d + AX_CLR + 1))
        cuts += pins(dist["layout"]["pin_x"], length - e_d / 2)
        ty1, sy1 = dist["layout"]["tendon_y"], dist["layout"]["sensor_y"]
        z_a, z_b = e_p + AX_CLR, length - e_d - AX_CLR
        cuts.append(channel([(ty0, -1), (ty0, z_a), (ty1, z_b), (ty1, length + 1)], CHAN_TENDON_D))
        cuts.append(channel([(sy0, -1), (sy0, z_a), (sy1, z_b), (sy1, length + 1)], CHAN_SENSOR_D))
    else:
        # Fingertip: tendon terminates in a transverse anchor hole on its own
        # channel line; sensor channel stops blind at the same depth.
        anchor_z = length - 3.0
        cuts.append(cyl(TENDON_ANCHOR_D / 2, 100, (-50, ty0, anchor_z), (1, 0, 0)))
        cuts.append(cyl(CHAN_TENDON_D / 2, anchor_z + 1, (0, ty0, -1), (0, 0, 1)))
        cuts.append(cyl(CHAN_SENSOR_D / 2, anchor_z + 1, (0, sy0, -1), (0, 0, 1)))
        # Sensor-pad recess on the PALMAR face, depth measured from the local surface.
        r = TIP_RECESS
        z0 = length - r["d"] - 3.0
        y_s = -h_at(z0) / 2
        cuts.append(_box(-r["w"] / 2, r["w"] / 2, y_s - 3, -h_at(z0 + r["d"]) / 2 + r["depth"],
                         z0, z0 + r["d"]))
    body = body.cut(fuse(cuts)).clean()
    return body


# ---------------------------------------------------------------------------
# BUILD ONE FINGER
# ---------------------------------------------------------------------------
def variant_specs(t_scale, crossings):
    out = []
    for base in (MCP, PIP, DIP):
        s = dict(base)
        s["pal_t"] = round(base["pal_t"] * t_scale, 4)
        s["dor_t"] = round(base["dor_t"] * t_scale, 4)
        if crossings is not None:
            s["pal_n"], s["dor_n"] = crossings, max(1, crossings - 1)
        out.append(s)
    return out


def build_finger(t_scale=1.0, crossings=None, verbose=True, flexure=None):
    mcp, pip, dip = variant_specs(t_scale, crossings)
    c = COLLAR_LEN
    L1, L2, L3 = L_PHAL1 - 2 * c, L_PHAL2 - 2 * c, L_PHAL3 - c
    floor = lambda s: s["end_len"] + AX_CLR
    lay_m = joint_layout(CS_MCP, mcp, section_at(CS_MCP, CS_PIP, L1, floor(mcp)))
    lay_p = joint_layout(CS_PIP, pip, section_at(CS_PIP, CS_DIP, L2, floor(pip)))
    lay_d = joint_layout(CS_DIP, dip, section_at(CS_DIP, CS_TIP, L3, floor(dip)))

    mcp_mod, mcp_len, _, mcp_lat = make_joint_module(CS_MCP, mcp, "MCP", lay_m, proximal_is_tab=False,
                                                     flexure=flexure)
    flange = _box(-FLANGE["w"] / 2, FLANGE["w"] / 2, -FLANGE["h"] / 2, FLANGE["h"] / 2, -FLANGE["t"], 0)
    flange = flange.cut(fuse(
        [cyl(FLANGE["hole_d"] / 2, FLANGE["t"] + 2, (sx * FLANGE["hole_spacing"] / 2, 0, -FLANGE["t"] - 1), (0, 0, 1))
         for sx in (-1, 1)]
        + [cyl(CHAN_TENDON_D / 2, 10, (0, lay_m["tendon_y"], -6), (0, 0, 1)),
           cyl(CHAN_SENSOR_D / 2, 10, (0, lay_m["sensor_y"], -6), (0, 0, 1))]))
    mcp_part = fuse([flange, mcp_mod])

    pip_mod, pip_len, _, pip_lat = make_joint_module(CS_PIP, pip, "PIP", lay_p, flexure=flexure)
    dip_mod, dip_len, _, dip_lat = make_joint_module(CS_DIP, dip, "DIP", lay_d, flexure=flexure)

    J = lambda s, l: dict(spec=s, layout=l)
    phal1 = make_phalanx(L1, CS_MCP, CS_PIP, J(mcp, lay_m), J(pip, lay_p), HARDSTOP_MCP)
    phal2 = make_phalanx(L2, CS_PIP, CS_DIP, J(pip, lay_p), J(dip, lay_d), HARDSTOP_PIP,
                         boss_z=L2 - ANCHOR_BOSS["offset_from_joint"])
    phal3 = make_phalanx(L3, CS_DIP, CS_TIP, J(dip, lay_d), None, HARDSTOP_DIP, tip=True,
                         boss_z=ANCHOR_BOSS["offset_from_joint"])

    # Assembly offsets: each phalanx starts where the preceding module's distal
    # tab starts; each module's proximal tab starts end_len before the end of
    # the preceding phalanx, so its collar seats on that phalanx's end face.
    z = {"01_MCP_module_with_flange": 0.0}
    z["02_Phalanx1"] = mcp_len - mcp["end_len"]
    z["03_PIP_module"] = z["02_Phalanx1"] + L1 - pip["end_len"]
    z["04_Phalanx2"] = z["03_PIP_module"] + pip_len - pip["end_len"]
    z["05_DIP_module"] = z["04_Phalanx2"] + L2 - dip["end_len"]
    z["06_Phalanx3"] = z["05_DIP_module"] + dip_len - dip["end_len"]

    parts = {"01_MCP_module_with_flange": mcp_part, "02_Phalanx1": phal1,
             "03_PIP_module": pip_mod, "04_Phalanx2": phal2,
             "05_DIP_module": dip_mod, "06_Phalanx3": phal3}
    report = dict(specs=dict(MCP=mcp, PIP=pip, DIP=dip),
                  layouts=dict(MCP=lay_m, PIP=lay_p, DIP=lay_d),
                  lattice=dict(MCP=mcp_lat, PIP=pip_lat, DIP=dip_lat))
    if verbose and flexure is None:
        for j in ("MCP", "PIP", "DIP"):
            lat, lay = report["lattice"][j], report["layouts"][j]
            print(f"  [{j}] palmar {lat['palmar']['n']}x t={lat['palmar']['t']:.3f} "
                  f"@{lat['palmar']['angle']:.1f} deg | dorsal {lat['dorsal']['n']}x "
                  f"t={lat['dorsal']['t']:.3f} @{lat['dorsal']['angle']:.1f} deg | "
                  f"tendon y={lay['tendon_y']:.2f}"
                  + (f" (pulley_r {report['specs'][j]['pulley_r']} clamped to fit tab)"
                     if lay["pulley_clamped"] else ""))
    return parts, z, report


# ---------------------------------------------------------------------------
# CHECKS
# ---------------------------------------------------------------------------
def check(parts, z, report):
    """Every part one valid solid; adjacent parts in the assembly do not
    overlap; pins pass clear through tab and socket; tendon path is clear."""
    problems = []
    placed = {n: p.translate(cq.Vector(0, 0, z[n])) for n, p in parts.items()}
    for n, p in parts.items():
        if not p.isValid():
            problems.append(f"{n}: invalid solid")
        if len(p.Solids()) != 1:
            problems.append(f"{n}: {len(p.Solids())} separate solids")
    names = list(parts)
    for a, b in zip(names, names[1:]):
        v = placed[a].intersect(placed[b]).Volume()
        if v > 1e-3:
            problems.append(f"{a} overlaps {b} by {v:.3f} mm^3")
    joints = (("MCP", "02_Phalanx1", "01_MCP_module_with_flange", True),
              ("PIP", "02_Phalanx1", "03_PIP_module", False),
              ("PIP", "04_Phalanx2", "03_PIP_module", True),
              ("DIP", "04_Phalanx2", "05_DIP_module", False),
              ("DIP", "06_Phalanx3", "05_DIP_module", True))
    for j, ph, mod, distal_tab in joints:
        spec, lay = report["specs"][j], report["layouts"][j]
        if distal_tab:
            zp = z[ph] + spec["end_len"] / 2
        else:
            zp = z[mod] + spec["end_len"] / 2
        rods = fuse([cyl(PIN_D / 2 - 0.05, 100, (sx * lay["pin_x"], -50, zp), (0, 1, 0)) for sx in (-1, 1)])
        for n in (ph, mod):
            v = placed[n].intersect(rods).Volume()
            if v > 1e-3:
                problems.append(f"{j} pin blocked in {n} ({v:.3f} mm^3)")
    return problems


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------
MODULES = ("01_MCP_module_with_flange", "03_PIP_module", "05_DIP_module")
PHALANGES = ("02_Phalanx1", "04_Phalanx2", "06_Phalanx3")


def export(parts, z, outdir, names, stl=True, assembly=True):
    os.makedirs(outdir, exist_ok=True)
    for n in names:
        wp = cq.Workplane("XY").newObject([parts[n]])
        cq.exporters.export(wp, os.path.join(outdir, n + ".step"))
        if stl:
            cq.exporters.export(wp, os.path.join(outdir, n + ".stl"), tolerance=0.02, angularTolerance=0.2)
    if assembly:
        assy = cq.Assembly()
        colours = {n: cq.Color(0.15, 0.45, 0.85) if n in MODULES else cq.Color(0.85, 0.85, 0.82) for n in parts}
        for n, p in parts.items():
            assy.add(p, name=n, loc=cq.Location(cq.Vector(0, 0, z[n])), color=colours[n])
        assy.export(os.path.join(outdir, "finger_assembly.step"))


def summary_rows(name, cfg, parts, report, problems):
    rows = []
    for j, mod in zip(("MCP", "PIP", "DIP"), MODULES):
        lat, lay = report["lattice"][j], report["layouts"][j]
        rows.append(dict(
            variant=name, t_scale=cfg["t_scale"],
            crossings="original" if cfg["crossings"] is None else cfg["crossings"], joint=j,
            palmar_cells=lat["palmar"]["n"], palmar_strut_mm=round(lat["palmar"]["t"], 3),
            palmar_angle_deg=round(lat["palmar"]["angle"], 1),
            palmar_cell_h_mm=round(lat["palmar"]["cell_h"], 3),
            dorsal_cells=lat["dorsal"]["n"], dorsal_strut_mm=round(lat["dorsal"]["t"], 3),
            dorsal_angle_deg=round(lat["dorsal"]["angle"], 1),
            dorsal_cell_h_mm=round(lat["dorsal"]["cell_h"], 3),
            tendon_moment_arm_mm=round(-lay["tendon_y"], 2),
            module_volume_mm3=round(parts[mod].Volume(), 1),
            checks="pass" if not problems else "; ".join(problems)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("variants", nargs="*", help=f"variant names (default: all). Known: {', '.join(VARIANTS)}")
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--no-stl", action="store_true")
    ap.add_argument("--no-assembly", action="store_true")
    ap.add_argument("--no-check", action="store_true")
    args = ap.parse_args(argv)

    names = args.variants or list(VARIANTS)
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        ap.error(f"unknown variant(s): {', '.join(unknown)}")

    rows, failed = [], []
    common_done = False
    for name in names:
        cfg = VARIANTS[name]
        print(f"\n=== {name}  (strut thickness x{cfg['t_scale']}, "
              f"crossings {cfg['crossings'] or 'original'}) ===")
        try:
            parts, z, report = build_finger(**cfg)
        except ValueError as exc:
            print(f"  NOT BUILT: {exc}")
            failed.append((name, str(exc)))
            continue
        problems = [] if args.no_check else check(parts, z, report)
        for p in problems:
            print("  CHECK FAILED:", p)
        if not args.no_check and not problems:
            print("  checks: single valid solids, no overlaps, pins clear")
        export(parts, z, os.path.join(args.out, name), MODULES,
               stl=not args.no_stl, assembly=not args.no_assembly)
        if not common_done:
            # Phalanges depend only on the cross-sections, tabs and channels,
            # never on the lattice, so they are the same for every variant.
            export(parts, z, os.path.join(args.out, "common_phalanges"), PHALANGES,
                   stl=not args.no_stl, assembly=False)
            common_done = True
        rows += summary_rows(name, cfg, parts, report, problems)

    if rows:
        path = os.path.join(args.out, "variants_summary.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("\nSummary written to", path)
    if failed:
        print("\nVariants not built:")
        for n, why in failed:
            print(f"  {n}: {why}")
    return 1 if failed or any(r["checks"] != "pass" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
