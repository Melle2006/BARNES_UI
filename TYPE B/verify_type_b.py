"""
Geometric verification of every Type B variant, beyond the checks built into
build_finger_type_b.py. Everything is measured on the built solids in their
assembled positions, straight (unflexed) pose:

  * tendon and sensor-lead routing: a rod slightly under channel size is run
    along the whole path, flange to fingertip anchor, and must touch nothing
  * tab-in-socket radial clearance and socket wall thickness
  * material around channels and pin holes inside the TPU tabs
  * retention pins, flange screw holes and M3 head clearance, anchor-boss
    holes, fingertip tendon anchor hole

What it cannot check: how the lattice flexes, joint stiffness, whether the
hard stops engage at the intended angle. Those need FEA or a print.

    python "TYPE B/verify_type_b.py"                 # all variants
    python "TYPE B/verify_type_b.py" B00_baseline    # named variants
    python "TYPE B/verify_type_b.py" --save-assembly # also write finger_assembly.step
"""

import argparse
import csv
import os
import sys

import cadquery as cq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_finger_type_b as B  # noqa: E402

TOL = 1e-3      # mm^3 of overlap treated as touching, not colliding
ROD_UNDER = 0.1 # probe rods are this much under the nominal hole diameter

JOINT_PARTS = (  # joint, module, proximal phalanx (None at MCP), distal phalanx
    ("MCP", "01_MCP_module_with_flange", None, "02_Phalanx1"),
    ("PIP", "03_PIP_module", "02_Phalanx1", "04_Phalanx2"),
    ("DIP", "05_DIP_module", "04_Phalanx2", "06_Phalanx3"),
)


def clear(shape, probe):
    return shape.intersect(probe).Volume()


def exterior(solid, z0, z1):
    """Space outside `solid` laterally, within z0..z1 only, so open end faces
    of a socket or channel don't count as zero wall."""
    bb = solid.BoundingBox()
    box = B._box(bb.xmin - 5, bb.xmax + 5, bb.ymin - 5, bb.ymax + 5, z0, z1)
    return box.cut(solid)


def dist(a, b):
    return a.distance(b)


def verify(name, cfg, built=None):
    """cfg is passed to build_finger; built=(parts, z, report) skips the build."""
    parts, z, rep = built or B.build_finger(**cfg, verbose=False)
    placed = {n: p.translate(cq.Vector(0, 0, z[n])) for n, p in parts.items()}
    everything = B.fuse(list(placed.values()))
    specs, lays = rep["specs"], rep["layouts"]
    c = B.COLLAR_LEN
    L1, L2, L3 = B.L_PHAL1 - 2 * c, B.L_PHAL2 - 2 * c, B.L_PHAL3 - c
    lengths = {"02_Phalanx1": L1, "04_Phalanx2": L2, "06_Phalanx3": L3}
    rows = []

    def rec(item, value, limit, ok, unit="mm"):
        rows.append(dict(variant=name, check=item, value=round(value, 4), limit=limit,
                         unit=unit, result="pass" if ok else "FAIL"))

    # --- routing: the full tendon and sensor paths as polylines in assembly Z
    def path(key):
        pts = [(lays["MCP"][key], -B.FLANGE["t"] - 1)]
        for j, mod, prox, dist_ph in JOINT_PARTS:
            e = specs[j]["end_len"]
            y = lays[j][key]
            if prox is not None:
                # inside the proximal phalanx: straight through its distal socket
                pts.append((y, z[prox] + lengths[prox] - e - B.AX_CLR))
            # straight through the module and on into the distal phalanx's socket
            pts.append((y, z[dist_ph] + e + B.AX_CLR))
        anchor = z["06_Phalanx3"] + L3 - 3.0
        pts.append((lays["DIP"][key], anchor))
        return pts

    for key, d, label in (("tendon_y", B.CHAN_TENDON_D, "tendon"), ("sensor_y", B.CHAN_SENSOR_D, "sensor lead")):
        rod = B.channel(path(key), d - ROD_UNDER)
        v = clear(everything, rod)
        rec(f"{label} path clear, flange to fingertip", v, f"<= {TOL}", v <= TOL, "mm^3")

    # fingertip anchor hole is clear and actually meets the tendon channel
    ty = lays["DIP"]["tendon_y"]
    az = z["06_Phalanx3"] + L3 - 3.0
    anchor_rod = B.cyl((B.TENDON_ANCHOR_D - ROD_UNDER) / 2, 100, (-50, ty, az), (1, 0, 0))
    v = clear(placed["06_Phalanx3"], anchor_rod)
    rec("fingertip tendon anchor hole clear", v, f"<= {TOL}", v <= TOL, "mm^3")

    for j, mod, prox, dist_ph in JOINT_PARTS:
        spec, lay = specs[j], lays[j]
        e = spec["end_len"]
        # the flex zone stays inside the collar outline
        cs_j = {"MCP": B.CS_MCP, "PIP": B.CS_PIP, "DIP": B.CS_DIP}[j]
        zf = z[mod] + e + (0 if prox is None else c)
        cw, ch, cr = B.collar_dims(cs_j)
        slab = B._box(-30, 30, -30, 30, zf, zf + spec["flex_len"])
        v = placed[mod].intersect(slab).cut(B.prism(cw, ch, cr, zf - 1, spec["flex_len"] + 2)).Volume()
        rec(f"{j} flex zone inside collar outline", v, f"<= {TOL}", v <= TOL, "mm^3")
        cs = {"MCP": B.CS_MCP, "PIP": B.CS_PIP, "DIP": B.CS_DIP}[j]
        cs_d = lay["cs_d"]
        ends = []
        if prox is not None:
            ends.append(("proximal", z[mod], prox, z[prox] + lengths[prox] - e - B.AX_CLR, True))
        ends.append(("distal", z[dist_ph], dist_ph, z[dist_ph], False))
        for side, tab_z0, ph, sock_z0, sock_at_distal_end in ends:
            sw, sh, sr = B.socket_dims(cs if sock_at_distal_end else cs_d)
            # radial clearance tab -> socket, measured in the middle of the tab
            slab = B._box(-30, 30, -30, 30, tab_z0 + 1.0, tab_z0 + e - 1.0)
            tab_mid = placed[mod].intersect(slab)
            gap = dist(tab_mid, placed[ph])
            rec(f"{j} {side} tab radial clearance in socket", gap, f"{B.CLR} +/- 0.02",
                abs(gap - B.CLR) <= 0.02)
            # socket wall: socket prism against the outside of the plain phalanx loft
            L = lengths[ph]
            cs0 = {"02_Phalanx1": B.CS_MCP, "04_Phalanx2": B.CS_PIP, "06_Phalanx3": B.CS_DIP}[ph]
            cs1 = {"02_Phalanx1": B.CS_PIP, "04_Phalanx2": B.CS_DIP, "06_Phalanx3": B.CS_TIP}[ph]
            loft = B.tapered_box(L, *cs0, *cs1).val().translate(cq.Vector(0, 0, z[ph]))
            sock = B.prism(sw, sh, sr, sock_z0, e + B.AX_CLR)
            wall = dist(sock, exterior(loft, sock_z0, sock_z0 + e + B.AX_CLR))
            rec(f"{j} {side} socket wall ({ph})", wall, ">= 1.0", wall >= 1.0)

        # material inside the TPU tab around channels and pin holes
        # the distal tab is the smaller of the two, so it is the one checked
        tw, th, tr = B.tab_dims(cs_d)
        tab = B.prism(tw, th, tr, 0, e)
        out = exterior(tab, 0, e)
        ch_t = B.cyl(B.CHAN_TENDON_D / 2, e, (0, lay["tendon_y"], 0), (0, 0, 1))
        ch_s = B.cyl(B.CHAN_SENSOR_D / 2, e, (0, lay["sensor_y"], 0), (0, 0, 1))
        pin_r = B.fuse(B.pins(lay["pin_x"], e / 2))
        rec(f"{j} tab wall around tendon channel", dist(ch_t, out), f">= {B.MIN_WALL}", dist(ch_t, out) >= B.MIN_WALL - 1e-6)
        rec(f"{j} tab wall around sensor channel", dist(ch_s, out), f">= {B.MIN_WALL}", dist(ch_s, out) >= B.MIN_WALL - 1e-6)
        rec(f"{j} tab material tendon channel to pin hole", dist(ch_t, pin_r), ">= 0.3", dist(ch_t, pin_r) >= 0.3)
        rec(f"{j} tab material tendon to sensor channel", dist(ch_t, ch_s), ">= 0.5", dist(ch_t, ch_s) >= 0.5)
        side_wall = tw / 2 - lay["pin_x"] - B.PIN_D / 2
        rec(f"{j} tab side wall outside pin hole", side_wall, ">= 0.3", side_wall >= 0.3)

    # flange screws: holes clear, and an M3 head (dia 5.5, 3 mm) fits on the distal face
    for sx in (-1, 1):
        x = sx * B.FLANGE["hole_spacing"] / 2
        screw = B.cyl((B.FLANGE["hole_d"] - ROD_UNDER) / 2, 20, (x, 0, -10), (0, 0, 1))
        head = B.cyl(5.5 / 2, 3.0, (x, 0, 0), (0, 0, 1))
        others = B.fuse([placed[n] for n in placed if n != "01_MCP_module_with_flange"])
        v = clear(placed["01_MCP_module_with_flange"], screw) + clear(everything, head) + clear(others, screw)
        rec(f"flange screw hole x={x:+.0f} and M3 head clearance", v, f"<= {TOL}", v <= TOL, "mm^3")

    # anchor-boss holes open (DIP coupling wire)
    b = B.ANCHOR_BOSS
    for ph, bz in (("04_Phalanx2", L2 - b["offset_from_joint"]), ("06_Phalanx3", b["offset_from_joint"])):
        cs0 = {"04_Phalanx2": B.CS_PIP, "06_Phalanx3": B.CS_DIP}[ph]
        cs1 = {"04_Phalanx2": B.CS_DIP, "06_Phalanx3": B.CS_TIP}[ph]
        y_s = -B.section_h(cs0[1], cs1[1], lengths[ph], bz + b["boss_wd"] / 2) / 2
        rod = B.cyl((b["hole_d"] - ROD_UNDER) / 2, b["boss_h"] + 1 + b["hole_into_body"] - 0.05,
                    (0, y_s - b["boss_h"] - 1, bz), (0, 1, 0))
        v = clear(parts[ph], rod)
        rec(f"anchor boss hole open ({ph})", v, f"<= {TOL}", v <= TOL, "mm^3")

    # every palmar feature is on the palmar side
    for ph in lengths:
        bb = parts[ph].BoundingBox()
        cs0 = {"02_Phalanx1": B.CS_MCP, "04_Phalanx2": B.CS_PIP, "06_Phalanx3": B.CS_DIP}[ph]
        rec(f"{ph} nub/boss on palmar side (ymin beyond -h/2)", bb.ymin, f"< {-cs0[1] / 2}",
            bb.ymin < -cs0[1] / 2 and bb.ymax <= cs0[1] / 2 + 1e-6)

    return rows, parts, z


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("variants", nargs="*")
    ap.add_argument("--save-assembly", action="store_true",
                    help="write B_lattice/<variant>/finger_assembly.step for each variant")
    ap.add_argument("--report", default=None, help="CSV report path (default: B_lattice/verification_report.csv)")
    args = ap.parse_args(argv)
    here = os.path.dirname(os.path.abspath(__file__))
    names = args.variants or list(B.VARIANTS)
    all_rows = []
    for n in names:
        print(f"=== {n}")
        rows, parts, z = verify(n, B.VARIANTS[n])
        fails = [r for r in rows if r["result"] != "pass"]
        for r in fails:
            print(f"  FAIL {r['check']}: {r['value']} (limit {r['limit']})")
        print(f"  {len(rows) - len(fails)}/{len(rows)} checks passed")
        if args.save_assembly:
            B.export(parts, z, os.path.join(here, "B_lattice", n), (), stl=False, assembly=True)
        all_rows += rows
    path = args.report or os.path.join(here, "B_lattice", "verification_report.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)
    print("Report:", path)
    return 1 if any(r["result"] != "pass" for r in all_rows) else 0


if __name__ == "__main__":
    sys.exit(main())
