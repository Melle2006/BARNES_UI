"""
Parametric single-finger assembly: 3 rigid PLA phalanges + 3 TPU flexure joint
modules (MCP, PIP, DIP), matching the design derived earlier in the conversation.

INTERNAL AXIS CONVENTION (CadQuery native Z-up convention is used internally):
    Z = along the finger's length, proximal (mounting flange) -> distal (fingertip)
      (this is the "X" axis referred to in the earlier written prompt/spec)
    X = lateral width  (the earlier spec's "Y")
    Y = dorsal-palmar height / flexion bending direction (the earlier spec's "Z")
This mapping is only an implementation detail so CadQuery's default loft/workplane
behavior (which extrudes along the workplane normal, i.e. Z) lines up naturally
with the finger's long axis. All dimensions below are identical in value to the
spec regardless of which letter labels them.

All dimensions in millimeters. Every numeric value here traces back to the
stiffness/geometry derivation earlier in the conversation -- see inline comments.
"""

import cadquery as cq
from ocp_vscode import show

# ---------------------------------------------------------------------------
# GLOBAL PARAMETERS (change these and re-run to regenerate the whole assembly)
# ---------------------------------------------------------------------------
CLR = 0.3          # per-side clearance for TPU-tab-into-PLA-socket fit
FILLET_EXT = 2.0   # external long-edge fillet on phalanges
PIN_D = 2.0         # retention pin hole diameter
CHAN_TENDON_D = 3.0 # palmar (flexor-side) tendon/coupling-wire channel diameter
CHAN_SENSOR_D = 1.5 # dorsal sensor-lead channel diameter
TENDON_ANCHOR_D = 2.0 # transverse through-hole for main tendon termination

# Cross-section taper stations: (width_X, height_Y) at each named interface
CS_MCP  = (16.0, 14.0)   # palm / MCP interface
CS_PIP  = (14.0, 12.0)   # PIP interface
CS_DIP  = (12.0, 10.0)   # DIP interface
CS_TIP  = (11.0, 9.0)    # fingertip

# Phalanx lengths (rigid sections only) -- shortened slightly from the
# original 40/22/20mm to give the TPU joint flex-zones more room below,
# which meaningfully improves the auxetic lattice's cell proportions
# (see conversation notes: short flex zones forced very shallow, squashed
# hourglass cells; more length lets the reentrant angle sit closer to the
# 30-45 deg range typical of real auxetic designs instead of ~70 deg).
L_PHAL1 = 32.86
L_PHAL2 = 17.76
L_PHAL3 = 15.98

# Joint module parameters: end-block length, flex-zone length, and now TWO
# bowtie lattices instead of one lattice + one plain web -- a compliant,
# multi-cell, thinner-strut lattice on the palmar side, and a stiffer,
# fewer-cell, thicker-strut lattice on the dorsal side. Both now span nearly
# the FULL joint height (only a small 1mm gap between them), fixing the
# earlier design where a small patterned patch on one edge and a small plain
# web on the other left ~60% of the cross-section as unsupported open space
# -- which is what was actually causing the "floating" appearance, not a
# missing union. Different cell count + strut thickness on each side also
# produces a genuinely different reentrant angle per side, as requested.
MCP = dict(end_len=4.0, flex_len=10.25, pulley_r=5.0,
           pal_yc=-3.5, pal_span=6.0, pal_t=0.7, pal_delta=0.5, pal_n=3,
           dor_yc=3.5,  dor_span=5.0, dor_t=1.4, dor_delta=0.5, dor_n=2)
PIP = dict(end_len=2.15, flex_len=7.55, pulley_r=3.5,
           pal_yc=-3.0, pal_span=5.0, pal_t=0.55, pal_delta=0.45, pal_n=2,
           dor_yc=3.0,  dor_span=3.8, dor_t=1.1, dor_delta=0.45, dor_n=2)
DIP = dict(end_len=1.0, flex_len=7.3, pulley_r=None,
           pal_yc=-2.5, pal_span=4.0, pal_t=0.45, pal_delta=0.4, pal_n=3,
           dor_yc=2.5,  dor_span=3.2, dor_t=0.9, dor_delta=0.4, dor_n=2)

HARDSTOP_MCP = dict(w=3.0, d=3.0, h=2.0)   # nub w x d(along length) x h(height)
HARDSTOP_PIP = dict(w=3.0, d=3.0, h=1.5)
HARDSTOP_DIP = dict(w=3.0, d=3.0, h=1.0)

ANCHOR_BOSS = dict(offset_from_joint=4.0, hole_d=1.5, boss_h=2.0, boss_wd=3.0)

FLANGE = dict(w=20.0, h=14.0, t=4.0, hole_d=3.0, hole_spacing=14.0)

TIP_RECESS = dict(w=8.0, d=6.0, depth=1.0)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def rounded_profile(w, h, r=None):
    """A rounded-rectangle (stadium-like) 2D profile -- reads as an organic,
    finger-like cross-section instead of a sharp box. r defaults to a large
    fraction of the smaller dimension for a strongly rounded, human-like look."""
    if r is None:
        r = 0.42 * min(w, h)
    r = min(r, min(w, h) / 2 - 0.01)
    return cq.Sketch().rect(w, h).vertices().fillet(r)


def tapered_box(length, w0, h0, w1, h1, fillet=0.0):
    """A rounded, tapering tube from (w0 x h0) to (w1 x h1) over `length`
    along Z -- lofted between two rounded-rectangle profiles so the result
    reads as an organic tapered finger segment, not a filleted box."""
    s0 = rounded_profile(w0, h0)
    s1 = rounded_profile(w1, h1)
    solid = (
        cq.Workplane("XY")
        .placeSketch(s0, s1.moved(cq.Location(cq.Vector(0, 0, length))))
        .loft()
    )
    return solid


def socket_cut(body, w, h, depth, at_top):
    """Cut a rectangular pocket of size (w x h), `depth` deep, into the body
    at either the top (+Z, distal-facing cut into a proximal-neighboring part)
    or bottom (-Z, proximal-facing cut) face."""
    z_face = "front" if at_top else "back"
    plane = cq.Workplane("XY").workplane(
        offset=(body.val().BoundingBox().zmax if at_top else body.val().BoundingBox().zmin)
    )
    pocket = plane.rect(w, h).extrude(-depth if at_top else depth)
    return body.cut(pocket)


def end_tab(w_full, h_full, length, pin_offset):
    """A rigid mating tab: reduced by clearance from the full cross-section,
    with a transverse pin hole. Extrudes +Z from z=0.

    Uses a MODEST fixed fillet (not the phalanges' aggressive organic
    rounding) -- these are small mechanical hardware blocks (pulley/lattice
    housings), not the visible phalanx shafts, and the aggressive rounding
    was found to measurably thin out the material right where the lattice
    and dorsal structure need a robust bond near the block's Y-extremes."""
    w, h = w_full - 2 * CLR, h_full - 2 * CLR
    r = min(2.0, min(w, h) / 2 - 0.1)
    prof = rounded_profile(w, h, r=r)
    tab = cq.Workplane("XY").placeSketch(prof).extrude(length)
    # Retention pin drilled through the lateral sides (X axis).
    # This avoids crossing the longitudinal tendon/sensor channels.
    pin = (
        cq.Workplane("YZ")
        .workplane(offset=-w / 2 - 1)
        .center(0, pin_offset)
        .circle(PIN_D / 2)
        .extrude(w + 2)
    )
    return tab.cut(pin)


def _beam_yz(y1, z1, y2, z2, thickness, x_center, x_thickness):
    """Make a true 3-D rectangular strut between two (Y,Z) points.

    Unlike the previous version, the strut has a FINITE thickness in X.
    It therefore behaves like a lattice strut, not a plate spanning the
    entire finger width. This leaves open space both inside each cell and
    between the parallel lattice columns.
    """
    import math
    dy = y2 - y1
    dz = z2 - z1
    length = math.hypot(dy, dz)
    if length <= 1e-9:
        raise ValueError("Zero-length lattice strut")
    py = -dz / length * thickness / 2
    pz = dy / length * thickness / 2
    pts = [
        (y1 + py, z1 + pz),
        (y2 + py, z2 + pz),
        (y2 - py, z2 - pz),
        (y1 - py, z1 - pz),
    ]
    return (
        cq.Workplane("YZ")
        .workplane(offset=x_center - x_thickness / 2)
        .polyline(pts).close()
        .extrude(x_thickness)
    )


def bowtie_lattice(y_center, y_span, z_start, z_len, n_cells, strut_t, delta, x_width):
    """Build a genuinely hollow 3-D re-entrant lattice.

    Geometry follows the paper's open-cell concept: four thin diagonal struts
    surround each empty re-entrant cell. Four parallel lattice columns are
    placed across X as two symmetric pairs, with a deliberate central void
    sized for the Ø3 mm main tendon. The flexure is not a solid plate and no
    material crosses the tendon corridor. Only the small interface bridges
    and the rigid end blocks provide the transverse connection.
    """
    import math
    n_bridges = n_cells + 1
    cell_h = (z_len - n_bridges * delta) / n_cells
    if cell_h <= 0.05:
        raise ValueError(
            f"Lattice cell height is {cell_h:.3f}mm (too thin/negative) -- "
            f"reduce lat_n or lat_delta, or increase flex_len."
        )

    waist_span = max(2.0 * strut_t, 0.25 * y_span)
    waist_span = min(waist_span, y_span - 2.0 * strut_t)
    if waist_span <= 0:
        raise ValueError("y_span is too small for the requested strut thickness")

    angle_deg = math.degrees(math.atan((y_span - waist_span) / cell_h))

    # Four separate lattice columns across the lateral X direction.
    # The two inner columns are deliberately moved outward, leaving a
    # symmetric central corridor for the Ø3 mm main tendon.  The corridor
    # is a TRUE void through the flexure: no lattice strut or connector spans
    # X = 0, so the tendon can pass without cutting through the cellular
    # geometry.  The arrangement remains left-right symmetric.
    n_x = 4
    x_strut_t = min(max(0.8, strut_t), 1.2)

    # Required free width = tendon diameter + clearance on both sides.
    tendon_clearance = 0.4
    central_gap = CHAN_TENDON_D + 2.0 * tendon_clearance

    # Inner-column center locations are chosen so their nearest faces leave
    # the required clear corridor.  The outer columns use the available
    # envelope while retaining the same left-right symmetry.
    inner_x = central_gap / 2.0 + x_strut_t / 2.0
    outer_x = x_width / 2.0 - x_strut_t / 2.0

    if outer_x <= inner_x:
        raise ValueError(
            f"Flexure width {x_width:.2f}mm is too small for four columns "
            f"and a {central_gap:.2f}mm tendon corridor."
        )

    x_centers = [-outer_x, -inner_x, inner_x, outer_x]

    actual_gap = 2.0 * inner_x - x_strut_t
    print(f"    lateral lattice: 4 columns | central tendon corridor "
          f"{actual_gap:.2f} mm clear")

    solids = []
    z = z_start

    # End/interface bridge: one bridge per X-column. This keeps the center
    # open while giving each lattice column a positive connection to the
    # rigid end block.
    for xc in x_centers:
        solids.append(
            cq.Workplane("YZ")
            .workplane(offset=xc - x_strut_t / 2)
            .center(y_center, z + delta / 2)
            .rect(y_span, delta)
            .extrude(x_strut_t)
        )
    z += delta

    for _ in range(n_cells):
        z_top = z
        z_mid = z + cell_h / 2
        z_bot = z + cell_h

        y_left = y_center - y_span / 2
        y_right = y_center + y_span / 2
        y_waist_left = y_center - waist_span / 2
        y_waist_right = y_center + waist_span / 2

        for xc in x_centers:
            solids.extend([
                _beam_yz(y_left, z_top, y_waist_left, z_mid,
                         strut_t, xc, x_strut_t),
                _beam_yz(y_right, z_top, y_waist_right, z_mid,
                         strut_t, xc, x_strut_t),
                _beam_yz(y_waist_left, z_mid, y_left, z_bot,
                         strut_t, xc, x_strut_t),
                _beam_yz(y_waist_right, z_mid, y_right, z_bot,
                         strut_t, xc, x_strut_t),
            ])

        z = z_bot
        for xc in x_centers:
            solids.append(
                cq.Workplane("YZ")
                .workplane(offset=xc - x_strut_t / 2)
                .center(y_center, z + delta / 2)
                .rect(y_span, delta)
                .extrude(x_strut_t)
            )
        z += delta

    result = solids[0]
    for s in solids[1:]:
        result = result.union(s)
    return result, angle_deg


def make_joint_module(cs, spec, name):
    """Builds one TPU joint module: end-block(tab) -- [palmar bowtie lattice,
    small gap, dorsal bowtie lattice] -- end-block(tab). Both sides are now
    patterned lattices (not one plain web) covering nearly the full joint
    height; they differ in cell count, strut thickness, and reentrant angle
    to keep the palmar side compliant/foldable and the dorsal side stiffer
    (resists stretching) -- mirroring panel A of the reference figure
    (contraction on the palmar side, extension on the dorsal side).
    cs = (w, h) cross-section for this joint's rigid end-blocks (full size).
    Returns (module_solid, total_len)."""
    w, h = cs
    end_len, flex_len = spec["end_len"], spec["flex_len"]
    total_len = 2 * end_len + flex_len
    x_width = w - 2.0  # total lateral envelope for the 4 open lattice columns + central tendon corridor

    blk1 = end_tab(w, h, end_len, pin_offset=end_len - 1.5)
    blk2 = end_tab(w, h, end_len, pin_offset=1.5).translate((0, 0, end_len + flex_len))

    palmar, pal_angle = bowtie_lattice(
        y_center=spec["pal_yc"], y_span=spec["pal_span"],
        z_start=end_len, z_len=flex_len,
        n_cells=spec["pal_n"], strut_t=spec["pal_t"], delta=spec["pal_delta"],
        x_width=x_width,
    )
    dorsal, dor_angle = bowtie_lattice(
        y_center=spec["dor_yc"], y_span=spec["dor_span"],
        z_start=end_len, z_len=flex_len,
        n_cells=spec["dor_n"], strut_t=spec["dor_t"], delta=spec["dor_delta"],
        x_width=x_width,
    )

    module = blk1.union(palmar).union(dorsal).union(blk2)

    # Note: the tendon's moment arm (pulley radius) is realized by offsetting
    # the tendon channel's Y-position where add_channels is called on this
    # module in the main script -- and that channel is restricted to the two
    # end-blocks only (not cut through this flex zone), specifically so it
    # can never intersect/sever either lattice regardless of Y position.

    print(f"  [{name}] palmar: {spec['pal_n']} cell(s) @ {pal_angle:.1f} deg | "
          f"dorsal: {spec['dor_n']} cell(s) @ {dor_angle:.1f} deg")

    return module, total_len


def add_hardstop_nub(body, hs, z_pos, side="proximal_face"):
    """Add a small rectangular nub protruding from the palmar (-Y) face at z_pos."""
    y_face = -body.val().BoundingBox().ylen / 2  # approx palmar face; refined per-part below
    nub = (
        cq.Workplane("XZ")
        .workplane(offset=y_face)
        .center(0, z_pos)
        .rect(hs["w"], hs["d"])
        .extrude(-hs["h"])
    )
    return body.union(nub)


# ---------------------------------------------------------------------------
# BUILD: MOUNTING FLANGE + MCP MODULE  (one physical part)
# ---------------------------------------------------------------------------
mcp_module, mcp_len = make_joint_module(CS_MCP, MCP, "MCP")

flange = (
    cq.Workplane("XY")
    .rect(FLANGE["w"], FLANGE["h"])
    .extrude(FLANGE["t"])
)
for sx in (-1, 1):
    flange = (
        flange.faces(">Z")
        .workplane()
        .center(sx * FLANGE["hole_spacing"] / 2, 0)
        .hole(FLANGE["hole_d"])
    )
# attach flange to the proximal end of the MCP module
flange = flange.translate((0, 0, -FLANGE["t"]))
mcp_part = flange.union(mcp_module)

# continuous tendon + sensor channels through the whole module length
def add_channels(body, z0, z1, tendon_y=-3.0, sensor_y=3.0):
    tendon = (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .center(0, tendon_y)
        .circle(CHAN_TENDON_D / 2)
        .extrude(z1 - z0)
    )
    sensor = (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .center(0, sensor_y)
        .circle(CHAN_SENSOR_D / 2)
        .extrude(z1 - z0)
    )
    return body.cut(tendon).cut(sensor)


def add_channels_skip_flexzone(body, z_lo, skip_z0, skip_z1, z_hi, tendon_y, sensor_y=3.0):
    """Cuts tendon+sensor channels through [z_lo, skip_z0] and [skip_z1, z_hi],
    leaving [skip_z0, skip_z1] (the flex zone, where the bowtie lattice and
    dorsal web live) completely untouched -- the tendon simply runs in open
    air across that short gap. This is what prevents the channel from ever
    intersecting/severing the lattice, regardless of the lattice's Y-position."""
    body = add_channels(body, z_lo, skip_z0, tendon_y, sensor_y)
    body = add_channels(body, skip_z1, z_hi, tendon_y, sensor_y)
    return body

# mcp_part spans global Z = -FLANGE["t"] .. mcp_len (flange, then the MCP
# module starting at its own Z=0). The MCP module's flex zone sits at
# [MCP["end_len"], MCP["end_len"]+MCP["flex_len"]] in that same frame.
mcp_part = add_channels_skip_flexzone(
    mcp_part,
    z_lo=-FLANGE["t"], skip_z0=MCP["end_len"],
    skip_z1=MCP["end_len"] + MCP["flex_len"], z_hi=mcp_len,
    tendon_y=-MCP["pulley_r"],
)

# export reference: MCP module occupies global Z = 0 .. mcp_len
Z_MCP_END = mcp_len


# ---------------------------------------------------------------------------
# BUILD: PHALANX 1
# ---------------------------------------------------------------------------
w0, h0 = CS_MCP
w1, h1 = CS_PIP
phal1 = tapered_box(L_PHAL1, w0, h0, w1, h1, fillet=FILLET_EXT)

# proximal socket (receives MCP module's distal tab)
sock_p = cq.Workplane("XY").placeSketch(rounded_profile(w0, h0)).extrude(MCP["end_len"])
phal1 = phal1.cut(sock_p)
pin_p = (
    cq.Workplane("YZ").workplane(offset=-w0 / 2 - 1)
    .center(0, MCP["end_len"] - 1.5).circle(PIN_D / 2).extrude(w0 + 2)
)
phal1 = phal1.cut(pin_p)

# distal socket (receives PIP module's proximal tab)
sock_d = (
    cq.Workplane("XY").workplane(offset=L_PHAL1 - PIP["end_len"])
    .placeSketch(rounded_profile(w1, h1)).extrude(PIP["end_len"])
)
phal1 = phal1.cut(sock_d)
pin_d = (
    cq.Workplane("YZ").workplane(offset=-w1 / 2 - 1)
    .center(0, L_PHAL1 - 1.5).circle(PIN_D / 2).extrude(w1 + 2)
)
phal1 = phal1.cut(pin_d)

# hard-stop nub on proximal (palmar, -Y) face, limits MCP flexion to 90 deg
nub1 = (
    cq.Workplane("XZ").workplane(offset=-h0 / 2)
    .center(0, HARDSTOP_MCP["d"] / 2 + 2)
    .rect(HARDSTOP_MCP["w"], HARDSTOP_MCP["d"])
    .extrude(-HARDSTOP_MCP["h"])
)
phal1 = phal1.union(nub1)

# matching step on the flange's distal face (cut a shallow recess so the nub
# has a defined mechanical contact surface at the 90-degree limit)
# (modeled as a flat face already present on the flange -- no extra cut needed
#  for this reference build; verify contact geometry against the real assembly
#  angle in CAD before printing)

phal1 = add_channels(phal1, 0, L_PHAL1)


# ---------------------------------------------------------------------------
# BUILD: PIP MODULE
# ---------------------------------------------------------------------------
pip_module, pip_len = make_joint_module(CS_PIP, PIP, "PIP")
pip_module = add_channels_skip_flexzone(
    pip_module,
    z_lo=0, skip_z0=PIP["end_len"],
    skip_z1=PIP["end_len"] + PIP["flex_len"], z_hi=pip_len,
    tendon_y=-PIP["pulley_r"],
)


# ---------------------------------------------------------------------------
# BUILD: PHALANX 2
# ---------------------------------------------------------------------------
w0, h0 = CS_PIP
w1, h1 = CS_DIP
phal2 = tapered_box(L_PHAL2, w0, h0, w1, h1, fillet=FILLET_EXT)

sock_p = cq.Workplane("XY").placeSketch(rounded_profile(w0, h0)).extrude(PIP["end_len"])
phal2 = phal2.cut(sock_p)
pin_p = (
    cq.Workplane("YZ").workplane(offset=-w0 / 2 - 1)
    .center(0, PIP["end_len"] - 1.5).circle(PIN_D / 2).extrude(w0 + 2)
)
phal2 = phal2.cut(pin_p)

sock_d = (
    cq.Workplane("XY").workplane(offset=L_PHAL2 - DIP["end_len"])
    .placeSketch(rounded_profile(w1, h1)).extrude(DIP["end_len"])
)
phal2 = phal2.cut(sock_d)
pin_d2 = (
    cq.Workplane("YZ").workplane(offset=-w1 / 2 - 1)
    .center(0, L_PHAL2 - 1.5).circle(PIN_D / 2).extrude(w1 + 2)
)
phal2 = phal2.cut(pin_d2)

# hard-stop nub, limits PIP flexion to 100 deg
nub2 = (
    cq.Workplane("XZ").workplane(offset=-h0 / 2)
    .center(0, HARDSTOP_PIP["d"] / 2 + 2)
    .rect(HARDSTOP_PIP["w"], HARDSTOP_PIP["d"])
    .extrude(-HARDSTOP_PIP["h"])
)
phal2 = phal2.union(nub2)

# DIP coupling-wire anchor boss near the distal end, palmar side,
# offset 4mm proximal of the DIP joint centerline
anchor_z = L_PHAL2 - ANCHOR_BOSS["offset_from_joint"]
boss2 = (
    cq.Workplane("XZ").workplane(offset=-h1 / 2)
    .center(0, anchor_z)
    .rect(ANCHOR_BOSS["boss_wd"], ANCHOR_BOSS["boss_wd"])
    .extrude(ANCHOR_BOSS["boss_h"])
)
# The boss now occupies Y = -h1/2 - boss_h ... -h1/2.
# Drill its Ø1.5 mm tendon hole along +Y.
boss2_hole = cq.Solid.makeCylinder(
    ANCHOR_BOSS["hole_d"] / 2,
    ANCHOR_BOSS["boss_h"] + 2.0,
    cq.Vector(0, -h1 / 2 - ANCHOR_BOSS["boss_h"] - 1.0, anchor_z),
    cq.Vector(0, 1, 0)
)
boss2_solid = boss2.val().cut(boss2_hole)
phal2 = phal2.union(cq.Workplane("XY").newObject([boss2_solid]))
phal2 = add_channels(phal2, 0, L_PHAL2)


# ---------------------------------------------------------------------------
# BUILD: DIP MODULE  (no pulley -- passive module)
# ---------------------------------------------------------------------------
dip_module, dip_len = make_joint_module(CS_DIP, DIP, "DIP")
dip_module = add_channels_skip_flexzone(
    dip_module,
    z_lo=0, skip_z0=DIP["end_len"],
    skip_z1=DIP["end_len"] + DIP["flex_len"], z_hi=dip_len,
    tendon_y=-3.0,  # DIP has no pulley of its own; main tendon just passes
                    # through here on its way to its anchor in Phalanx 3
)


# ---------------------------------------------------------------------------
# BUILD: PHALANX 3  (distal, with fingertip sensor recess + tendon anchor)
# ---------------------------------------------------------------------------
w0, h0 = CS_DIP
w1, h1 = CS_TIP
phal3 = tapered_box(L_PHAL3, w0, h0, w1, h1, fillet=FILLET_EXT)

sock_p = cq.Workplane("XY").placeSketch(rounded_profile(w0, h0)).extrude(DIP["end_len"])
phal3 = phal3.cut(sock_p)
pin_p = (
    cq.Workplane("YZ").workplane(offset=-w0 / 2 - 1)
    .center(0, DIP["end_len"] - 1.5).circle(PIN_D / 2).extrude(w0 + 2)
)
phal3 = phal3.cut(pin_p)

# hard-stop nub, limits DIP flexion to 80 deg
nub3 = (
    cq.Workplane("XZ").workplane(offset=-h0 / 2)
    .center(0, HARDSTOP_DIP["d"] / 2 + 2)
    .rect(HARDSTOP_DIP["w"], HARDSTOP_DIP["d"])
    .extrude(-HARDSTOP_DIP["h"])
)
phal3 = phal3.union(nub3)

# DIP coupling-wire anchor boss near the proximal end (mirrors phal2's boss)
anchor_z3 = ANCHOR_BOSS["offset_from_joint"]
boss3 = (
    cq.Workplane("XZ").workplane(offset=-h0 / 2)
    .center(0, anchor_z3)
    .rect(ANCHOR_BOSS["boss_wd"], ANCHOR_BOSS["boss_wd"])
    .extrude(ANCHOR_BOSS["boss_h"])
)
# The boss now occupies Y = -h0/2 - boss_h ... -h0/2.
# Drill its Ø1.5 mm tendon hole along +Y.
boss3_hole = cq.Solid.makeCylinder(
    ANCHOR_BOSS["hole_d"] / 2,
    ANCHOR_BOSS["boss_h"] + 2.0,
    cq.Vector(0, -h0 / 2 - ANCHOR_BOSS["boss_h"] - 1.0, anchor_z3),
    cq.Vector(0, 1, 0)
)
boss3_solid = boss3.val().cut(boss3_hole)
phal3 = phal3.union(cq.Workplane("XY").newObject([boss3_solid]))
# Main-tendon termination anchor near the distal end of Phalanx 3.
# The tendon approaches along +Z through the Ø3 mm longitudinal channel,
# then passes through this transverse hole and can be knotted or mechanically stopped.
tendon_anchor_z = L_PHAL3 - 2.0
tendon_anchor_hole = (
    cq.Workplane("YZ").workplane(offset=-w0 / 2 - 1)
    .center(-3.0, tendon_anchor_z)
    .circle(TENDON_ANCHOR_D / 2)
    .extrude(w0 + 2)
)
phal3 = phal3.cut(tendon_anchor_hole)

# fingertip sensor pad recess on the palmar face near the distal end
recess_z = L_PHAL3 - TIP_RECESS["d"] - 3.0
recess = (
    cq.Workplane("XZ").workplane(offset=-h1 / 2)
    .center(0, recess_z + TIP_RECESS["d"] / 2)
    .rect(TIP_RECESS["w"], TIP_RECESS["d"])
    .extrude(TIP_RECESS["depth"])
)
phal3 = phal3.cut(recess)

phal3 = add_channels(phal3, 0, L_PHAL3 - TIP_RECESS["depth"])

# rounded fingertip: fillet the distal end face edges more aggressively
try:
    phal3 = phal3.edges(">Z").fillet(min(w1, h1) / 2 - 0.5)
except Exception as e:
    print("Fingertip fillet skipped (non-critical):", e)


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------
import os
outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(outdir, exist_ok=True)

parts = {
    "01_MCP_module_with_flange": mcp_part,
    "02_Phalanx1": phal1,
    "03_PIP_module": pip_module,
    "04_Phalanx2": phal2,
    "05_DIP_module": dip_module,
    "06_Phalanx3": phal3,
}

'''
assy = cq.Assembly()
cum_z = 0.0
offsets = {}
for name, part in parts.items():
    bb = part.val().BoundingBox()
    shift = cum_z - bb.zmin   # flush this part's local zmin against the running cursor
    offsets[name] = shift
    assy.add(part.translate((0, 0, shift)), name=name)
    cum_z += (bb.zmax - bb.zmin)
'''

assy = cq.Assembly()

# MCP module:
# mcp_part spans local Z = -4 (flange) to +15.
mcp_shift = 0.0

assy.add(
    mcp_part.translate((0, 0, mcp_shift)),
    name="01_MCP_module_with_flange"
)

# ---------------------------------------------------------
# PHALANX 1
# MCP distal tab = local Z 11 -> 15
# Phalanx 1 proximal socket = local Z 0 -> 4
#
# Therefore phalanx 1 must start at Z = 11.
# ---------------------------------------------------------
phal1_shift = mcp_len - MCP["end_len"]

assy.add(
    phal1.translate((0, 0, phal1_shift)),
    name="02_Phalanx1"
)

# ---------------------------------------------------------
# PIP
# Phalanx 1 distal socket:
# global Z = 11 + 37 - 2.15 = 45.85
# PIP proximal tab enters that socket.
# ---------------------------------------------------------
pip_shift = (
    phal1_shift
    + L_PHAL1
    - PIP["end_len"]
)

assy.add(
    pip_module.translate((0, 0, pip_shift)),
    name="03_PIP_module"
)

# ---------------------------------------------------------
# PHALANX 2
# PIP distal tab enters Phalanx 2 proximal socket.
# ---------------------------------------------------------
phal2_shift = (
    pip_shift
    + pip_len
    - PIP["end_len"]
)

assy.add(
    phal2.translate((0, 0, phal2_shift)),
    name="04_Phalanx2"
)

# ---------------------------------------------------------
# DIP
# Phalanx 2 distal socket receives DIP proximal tab.
# ---------------------------------------------------------
dip_shift = (
    phal2_shift
    + L_PHAL2
    - DIP["end_len"]
)

assy.add(
    dip_module.translate((0, 0, dip_shift)),
    name="05_DIP_module"
)

# ---------------------------------------------------------
# PHALANX 3
# DIP distal tab enters Phalanx 3 proximal socket.
# ---------------------------------------------------------
phal3_shift = (
    dip_shift
    + dip_len
    - DIP["end_len"]
)

assy.add(
    phal3.translate((0, 0, phal3_shift)),
    name="06_Phalanx3"
)

for name, part in parts.items():
    cq.exporters.export(part, f"{outdir}/{name}.stl")
    cq.exporters.export(part, f"{outdir}/{name}.step")

assy.save(f"{outdir}/finger_assembly.step")

show(assy)

print("Done. Files written to", outdir)
print("STEP parts exported:")
for name in parts:
    print("  ", os.path.join(outdir, name + ".step"))
print("Assembly STEP:")
print("  ", os.path.join(outdir, "finger_assembly.step"))