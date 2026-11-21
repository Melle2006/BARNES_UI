"""
Single-joint PIP test rig and tensile specimens for Type B round 2.

The rig holds a real Phalanx 1 fixed and lets a real PIP module and Phalanx 2
move. Any Type B PIP module, round 1 or round 2, as-built or deep tendon, drops
in. Everything is PLA except the module under test.

    rig_base        dummy MCP tab that Phalanx 1 slides onto and is pinned to
                    (exactly as on the finger); a 0-115 deg protractor about the
                    nominal PIP pivot; a pulley clevis for the tendon weights; a
                    side plate to clamp to a table edge, so the finger, the
                    pulley and both weight strings overhang it
    load_adapter    dummy DIP tab that plugs into Phalanx 2's distal socket,
                    carrying the tendon anchor, an arm with hook holes at 30,
                    37.5 and 44.8 mm from the PIP pivot (44.8 = the Type B
                    finger's fingertip), and a pointer vane over the scale
    pulley          20 mm grooved wheel, 10 mm bore for a 623ZZ bearing on an
                    M3 bolt

The finger lies palmar side up, so flexion lifts the distal part against a
weight hung from the arm. The tendon leaves the back of the post, runs over
the pulley and hangs down.

Tendon slots are cut tall enough for both tendon depths, the as-built and
round 2's deep offset, so one rig takes every variant.

Frame: the finger's own. z runs along the finger, with z = 0 at Phalanx 1's
proximal face; y is dorsal (+), which on the rig points DOWN; x is lateral.

Specimens (flat = thickness vertical; edge = standing on edge, thickness in the
XY plane):
    tensile_1BA_t1.0_flat, tensile_1BA_t2.0_flat
        ISO 527-2 type 1BA dog-bones, printed flat
    tensile_strip_t1.0_edge, tensile_strip_t2.0_edge
        straight strips printed on edge, which is how a leaf is laid down when
        the module lies on its side
    compression_d10_h10
        10 x 10 mm cylinder for the compressive modulus, which the round-2
        bearings depend on

    python "TYPE B/round2/test_rig/build_test_rig.py" [--no-stl]

Writes STEP/STL here, plus rig_assembly.step (rig with a B3_t150_w30 finger,
for checking) and rig_checks.csv.
"""

import argparse
import csv
import math
import os
import sys

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
TYPE_B = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, TYPE_B)
sys.path.insert(0, os.path.dirname(HERE))
import build_finger_type_b as B  # noqa: E402
import build_flexure_families as F  # noqa: E402
import build_round2 as R2  # noqa: E402

TOL = 1e-3


def box(x0, x1, y0, y1, z0, z1):
    return B._box(x0, x1, y0, y1, z0, z1)


def geometry():
    """Finger positions the rig must match, taken from the builder itself."""
    parts, z, rep = B.build_finger(flexure=F.FAMILIES["B3"]["variants"]["B3_t150_w30"][1],
                                   verbose=False)
    z0 = z["02_Phalanx1"]
    zz = {n: v - z0 for n, v in z.items()}            # Phalanx 1 proximal face at 0
    pip, lay = rep["specs"]["PIP"], rep["layouts"]
    pivot_z = zz["03_PIP_module"] + pip["end_len"] + B.COLLAR_LEN + pip["flex_len"] / 2
    deep = {j: v[0] for j, v in R2.deepest_offsets().items()}
    return dict(parts=parts, z=zz, rep=rep, pivot_z=pivot_z, lay=lay, deep=deep)


def obround_slot(y_a, y_b, z0, z1, d=B.CHAN_TENDON_D):
    """A channel along z covering every depth from y_a to y_b."""
    r = d / 2
    lo, hi = min(y_a, y_b), max(y_a, y_b)
    s = box(-r, r, lo, hi, z0, z1)
    return s.fuse(B.cyl(r, z1 - z0, (0, lo, z0), (0, 0, 1)),
                  B.cyl(r, z1 - z0, (0, hi, z0), (0, 0, 1))).clean()


def yz_poly(pts, x0, x1):
    """Polygon in (z, y) extruded across x0..x1."""
    return (cq.Workplane("YZ").workplane(offset=x0)
            .polyline([(y, z) for z, y in pts]).close().extrude(x1 - x0).val())


# ---------------------------------------------------------------------------
PLATE_X = (-14.0, -11.0)     # protractor plane, beside the finger
VANE_X = (-10.5, -3.0)       # pointer vane, between the plate and the arm
RHO_IN, RHO_OUT = 34.0, 58.0
TICK = (44.0, 49.0)          # tick band, radius from the pivot
HOOK_R = (30.0, 37.5, 44.8)  # hook holes, radius from the pivot
ANGLE_MAX = 115
POST_Z = (-22.0, 0.0)
PULLEY_RG = 8.0              # groove bottom radius
PULLEY_Z = -33.0


def rig_base(g):
    lay_m = g["lay"]["MCP"]
    e = B.MCP["end_len"]
    pz = g["pivot_z"]
    parts = []
    # post, and the bridge down to the side plate
    parts.append(box(-9, 9, -12, 10, *POST_Z))
    parts.append(box(-14, -9, -12, 16, *POST_Z))
    # dummy MCP distal tab, sized exactly as the module's
    tw, th, tr = B.tab_dims(lay_m["cs_d"])
    parts.append(B.prism(tw, th, tr, 0, e))
    # side plate to clamp to a table edge
    parts.append(box(-80, -13, 10, 16, -55, 60))
    # pulley clevis, hung from a beam above the tendon line
    y_t = (lay_m["tendon_y"] - g["deep"]["MCP"]) / 2            # between the two depths
    yc = y_t + PULLEY_RG
    parts.append(box(-9, 9, -16, -12, -45, POST_Z[1]))           # beam, above the post top
    for x0, x1 in ((-7.0, -3.3), (3.3, 7.0)):
        parts.append(box(x0, x1, -16, yc + 5, PULLEY_Z - 7, PULLEY_Z + 7))
    # protractor frame and sector, in the plate plane
    frame = [(-22, -16), (-16, -16), (-16, 52), (pz - 8, 52), (pz - 8, 58), (-22, 58)]
    parts.append(yz_poly([(z, -y) for z, y in frame], *PLATE_X))  # v = -y is "up"
    sector = []
    for i in range(61):
        a = math.radians(-5 + (ANGLE_MAX + 10) * i / 60)
        sector.append((pz + RHO_OUT * math.cos(a), -RHO_OUT * math.sin(a)))
    for i in range(61):
        a = math.radians(ANGLE_MAX + 5 - (ANGLE_MAX + 10) * i / 60)
        sector.append((pz + RHO_IN * math.cos(a), -RHO_IN * math.sin(a)))
    parts.append(yz_poly(sector, *PLATE_X))
    base = B.fuse(parts)

    cuts = []
    # tendon: slot through the dummy tab and post covering both tendon depths
    cuts.append(obround_slot(lay_m["tendon_y"], -g["deep"]["MCP"], POST_Z[0] - 1, e + 1))
    cuts += B.pins(lay_m["pin_x"], e / 2)                          # retention pins
    cuts.append(B.cyl(1.6, 20, (-10, yc, PULLEY_Z), (1, 0, 0)))    # M3 axle
    cuts.append(box(-3.3, 3.3, -11, yc + 6, PULLEY_Z - 12, PULLEY_Z + 12))  # pulley room
    cuts.append(box(-3.0, 3.0, -12.5, 10, POST_Z[0] - 1, POST_Z[0] + 3))   # tendon exit relief
    # clamp slots
    for z in (-40.0, 30.0):
        cuts.append(box(-60, -35, 9, 17, z - 3, z + 3))
    # ticks every 5 deg, longer every 10; numbers every 10, engraved on the
    # finger-side face (x = PLATE_X[1]) and read from that side
    face = PLATE_X[1]
    for deg in range(0, ANGLE_MAX + 1, 5):
        a = math.radians(deg)
        r1, r2 = TICK[0], TICK[1] + (2.0 if deg % 10 == 0 else 0.0)
        w = 0.35
        ca, sa = math.cos(a), math.sin(a)
        quad = [(pz + r1 * ca - w * sa, -(r1 * sa + w * ca)), (pz + r2 * ca - w * sa, -(r2 * sa + w * ca)),
                (pz + r2 * ca + w * sa, -(r2 * sa - w * ca)), (pz + r1 * ca + w * sa, -(r1 * sa - w * ca))]
        cuts.append(yz_poly(quad, face - 0.6, face + 1))
        if deg % 10 == 0:
            rn = TICK[1] + 5.0
            # text runs along +z with "up" = -y: upright when read from the finger side
            pl = cq.Plane(origin=(face + 0.1, -rn * sa, pz + rn * ca), xDir=(0, 0, 1), normal=(1, 0, 0))
            txt = cq.Workplane(pl).text(str(deg), 3.2, -0.7, halign="center", valign="center",
                                        combine=False)
            cuts.append(txt.val())
    return base.cut(B.fuse(cuts)).clean(), dict(y_tendon_line=y_t, pulley_axle_y=yc)


def load_adapter(g):
    lay_d = g["lay"]["DIP"]
    spec = B.DIP
    e = spec["end_len"]
    z0 = g["z"]["05_DIP_module"]                      # where the DIP module's tab would start
    pz = g["pivot_z"]
    tw, th, tr = B.tab_dims(B.CS_DIP)
    cw, ch, cr = B.collar_dims(B.CS_DIP)
    zb = z0 + e + 3.0
    z_end = pz + 48.6
    parts = [B.prism(tw, th, tr, z0, e), B.prism(cw, ch, cr, z0 + e, 3.0),
             box(-3, 3, -2.5, 2.5, zb - 0.5, z_end),
             box(VANE_X[0], VANE_X[1] + 0.5, -0.5, 0.5, pz + 46.4, pz + 48.6)]   # vane: a radial
    # blade on y = 0, beyond the last hook hole; it crosses the tick band at 46-49 mm
    adapter = B.fuse(parts)
    cuts = [obround_slot(lay_d["tendon_y"], -g["deep"]["DIP"], z0 - 1, zb - 1.0),
            B.cyl(B.TENDON_ANCHOR_D / 2, 40, (-20, (lay_d["tendon_y"] - g["deep"]["DIP"]) / 2, z0 + e + 1.2),
                  (1, 0, 0))]
    cuts += B.pins(lay_d["pin_x"], z0 + e / 2)
    for r in HOOK_R:
        cuts.append(B.cyl(1.25, 20, (-10, 0, pz + r), (1, 0, 0)))
    return adapter.cut(B.fuse(cuts)).clean()


def pulley():
    w = 6.6 - 0.6
    outer = B.cyl(10.0, w, (0, 0, 0), (1, 0, 0))
    groove = (cq.Workplane("YZ").circle(10.5).circle(PULLEY_RG).extrude(1.2).val()
              .translate(cq.Vector(w / 2 - 0.6, 0, 0)))
    bore = B.cyl(5.05, w + 2, (-1, 0, 0), (1, 0, 0))
    return outer.cut(groove).cut(bore).clean()


# ---------------------------------------------------------------------------
def dogbone_1ba(t):
    """ISO 527-2 type 1BA: 75 long, 10 wide ends, 5 wide x 30 parallel, R 30."""
    L, b2, b1, l1, r = 75.0, 10.0, 5.0, 30.0, 30.0
    dx = math.sqrt(r * r - (r - (b2 - b1) / 2) ** 2)      # length of each blend
    left = [(-L / 2, b2 / 2), (-l1 / 2 - dx, b2 / 2)]
    for i in range(1, 16):                                  # blend down to the parallel
        x = -l1 / 2 - dx + dx * i / 15
        left.append((x, b1 / 2 + r - math.sqrt(max(r * r - (x + l1 / 2) ** 2, 0.0))))
    upper = left + [(-x, y) for x, y in reversed(left)]
    poly = upper + [(x, -y) for x, y in reversed(upper)]
    return cq.Workplane("XY").polyline(poly).close().extrude(t).val()


def edge_strip(t):
    """On-edge strip: 80 long, 6 tall, t thick; grips are the end 20 mm."""
    return box(-40, 40, -t / 2, t / 2, 0, 6.0)


def compression_cylinder():
    return B.cyl(5.0, 10.0, (0, 0, 0), (0, 0, 1))


# ---------------------------------------------------------------------------
def rotate_about_pivot(shape, deg, pz):
    # +deg about +x carries a point at (y=0, z=pz+r) to y = -r sin(deg): flexion
    return shape.rotate(cq.Vector(0, 0, pz), cq.Vector(1, 0, pz), deg)


def checks(g, base, adapter):
    """The rig must fit the real parts and stay clear of them through the range."""
    rows = []
    parts, z = g["parts"], g["z"]
    ph1 = parts["02_Phalanx1"].translate(cq.Vector(0, 0, z["02_Phalanx1"]))
    mod = parts["03_PIP_module"].translate(cq.Vector(0, 0, z["03_PIP_module"]))
    ph2 = parts["04_Phalanx2"].translate(cq.Vector(0, 0, z["04_Phalanx2"]))

    def rec(name, value, limit, ok):
        rows.append(dict(check=name, value=round(value, 4), limit=limit, result="pass" if ok else "FAIL"))

    for n, p in (("rig_base", base), ("load_adapter", adapter)):
        rec(f"{n} is one valid solid", len(p.Solids()), "== 1", p.isValid() and len(p.Solids()) == 1)
    v = base.intersect(ph1).Volume()
    rec("rig_base clear of Phalanx 1", v, f"<= {TOL}", v <= TOL)
    # radial clearance, measured across the middle of the tab as verify_type_b.py
    # does: the post face is meant to seat on Phalanx 1's end face
    e_m, e_d = B.MCP["end_len"], B.DIP["end_len"]
    gap = base.intersect(box(-30, 30, -30, 30, 1.0, e_m - 1.0)).distance(ph1)
    rec("dummy MCP tab clearance in Phalanx 1 socket", gap, f"{B.CLR} +/- 0.02", abs(gap - B.CLR) <= 0.02)
    v = adapter.intersect(ph2).Volume()
    rec("load_adapter clear of Phalanx 2", v, f"<= {TOL}", v <= TOL)
    z05 = z["05_DIP_module"]
    gap = adapter.intersect(box(-30, 30, -30, 30, z05 + 1.0, z05 + e_d - 1.0)).distance(ph2)
    rec("dummy DIP tab clearance in Phalanx 2 socket", gap, f"{B.CLR} +/- 0.02", abs(gap - B.CLR) <= 0.02)
    # flex the distal group rigidly about the nominal pivot through the range
    worst = 0.0
    for deg in range(0, ANGLE_MAX + 1, 5):
        moving = B.fuse([rotate_about_pivot(s, deg, g["pivot_z"]) for s in (ph2, adapter)])
        worst = max(worst, moving.intersect(base).Volume())
    rec(f"Phalanx 2 + adapter clear of rig_base, 0-{ANGLE_MAX} deg", worst, f"<= {TOL}", worst <= TOL)
    v = mod.intersect(base).Volume()
    rec("PIP module clear of rig_base", v, f"<= {TOL}", v <= TOL)
    # tendon: a 2.9 mm rod at each depth runs from the post back face through
    # the dummy tab and out of the rig with no PLA in the way
    for label, y in (("as-built", g["lay"]["MCP"]["tendon_y"]), ("deep", -g["deep"]["MCP"])):
        rod = B.cyl((B.CHAN_TENDON_D - 0.1) / 2, -POST_Z[0] + 4.0, (0, y, POST_Z[0] - 0.5), (0, 0, 1))
        v = base.intersect(rod).Volume()
        rec(f"tendon path through post clear ({label} depth)", v, f"<= {TOL}", v <= TOL)
    for label, y in (("as-built", g["lay"]["DIP"]["tendon_y"]), ("deep", -g["deep"]["DIP"])):
        z0 = z["05_DIP_module"]
        rod = B.cyl((B.CHAN_TENDON_D - 0.1) / 2, B.DIP["end_len"] + 1.5, (0, y, z0 - 0.5), (0, 0, 1))
        v = adapter.intersect(rod).Volume()
        rec(f"tendon path into adapter clear ({label} depth)", v, f"<= {TOL}", v <= TOL)
    return rows


def export(shape, name, stl):
    wp = cq.Workplane("XY").newObject([shape])
    cq.exporters.export(wp, os.path.join(HERE, name + ".step"))
    if stl:
        cq.exporters.export(wp, os.path.join(HERE, name + ".stl"), tolerance=0.02, angularTolerance=0.2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-stl", action="store_true")
    args = ap.parse_args(argv)
    g = geometry()
    base, info = rig_base(g)
    adapter = load_adapter(g)
    pul = pulley().translate(cq.Vector(-3.0, info["pulley_axle_y"], PULLEY_Z))
    rows = checks(g, base, adapter)
    v = pul.intersect(base).Volume()
    rows.append(dict(check="pulley clear of rig_base", value=round(v, 4), limit=f"<= {TOL}",
                     result="pass" if v <= TOL else "FAIL"))
    for r in rows:
        print(("  " if r["result"] == "pass" else "  FAIL ") + f"{r['check']}: {r['value']} ({r['limit']})")
    with open(os.path.join(HERE, "rig_checks.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    stl = not args.no_stl
    export(base, "rig_base", stl)
    export(adapter, "load_adapter", stl)
    export(pulley(), "pulley", stl)
    for t in (1.0, 2.0):
        export(dogbone_1ba(t), f"tensile_1BA_t{t:.1f}_flat", stl)
        export(edge_strip(t), f"tensile_strip_t{t:.1f}_edge", stl)
    export(compression_cylinder(), "compression_d10_h10", stl)
    assy = cq.Assembly()
    for n, s, col in (("rig_base", base, (0.9, 0.9, 0.85)), ("load_adapter", adapter, (0.9, 0.6, 0.2)),
                      ("pulley", pul, (0.5, 0.5, 0.5))):
        assy.add(s, name=n, color=cq.Color(*col))
    for n in ("02_Phalanx1", "03_PIP_module", "04_Phalanx2"):
        assy.add(g["parts"][n], name=n, loc=cq.Location(cq.Vector(0, 0, g["z"][n])),
                 color=cq.Color(0.15, 0.45, 0.85) if n == "03_PIP_module" else cq.Color(0.85, 0.85, 0.82))
    assy.export(os.path.join(HERE, "rig_assembly.step"))
    print("pivot z", round(g["pivot_z"], 3), "tendon line y", round(info["y_tendon_line"], 3),
          "hooks at", [round(g["pivot_z"] + r, 2) for r in HOOK_R])
    return 1 if any(r["result"] != "pass" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
