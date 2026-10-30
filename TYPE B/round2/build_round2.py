"""
Type B round 2: compression-carrying joints and a deep tendon offset.

Round 1 (the B1/B3/B5/B6 families and the lattice) stays exactly as it is; it is
still to be printed and tested. This script only adds. It reuses the same finger,
collars, tabs, sockets and phalanges from ../build_finger_type_b.py, and writes
everything under this folder.

Why round 2 exists
------------------
docs/11-tendon-routing-type-a-b.md (branch claude/busy-gates-m9buje) found that
every round-1 variant buckles under tendon compression well before the servo
limit. The tendon squeezes each joint as it bends it. With no pin, the TPU leaves
alone carry that load, and a leaf 1-2 mm thick buckles at a few newtons. So
round 2 adds a part whose job is to carry compression, and leaves the TPU
springs to do the returning:

    B4  rolling contact   two convex bearing lobes that roll on each other,
                          held together by crossed TPU straps (fused X)
    B8  contact pad       a cylindrical knuckle on the neutral axis (B8_y00) or
                          2 mm dorsal of it (B8_y20), seated in a concave cup,
                          with thin TPU leaves as the return spring only
    B9  compression strut a short, stocky web with a single neck on the neutral
                          axis, notched 40 deg palmar for range; thin leaves
                          return

and a separate option:

    deep tendon           the tendon channel at the deepest palmar offset the
                          section allows with the builder's own 0.8 mm walls,
                          applied to shortlisted round-1 variants and to the new
                          designs (deep_offset/)

Every bearing pair is printed 0.3 mm apart, so the joint is free as printed. The
tendon load closes the gap and then goes through the bearing, not the leaves.

Design rules that matter
------------------------
* A rolling contact moves towards the palm as the joint closes, by R sin(theta/2).
  The tendon's lever about it is roughly d - R sin(theta/2), so a large rolling
  radius would turn a palmar tendon into an extensor part-way through flexion.
  B4's radius is therefore set per joint so the lever stays at least
  LEVER_MARGIN at that joint's target flexion. That makes it small at the
  as-built offsets, and larger at the deep ones.
* A bearing on the palmar side would put the pivot palmar of the tendon, and the
  tendon would extend the joint. So the pad is central (y = 0) or dorsal
  (y = +2), never palmar. Moving it dorsally lengthens the lever without moving
  the tendon.
* Bearings and springs sit in separate lanes either side of the clear central
  corridor, so the tendon and sensor lead pass in open air as in round 1.

    python "TYPE B/round2/build_round2.py"                 # everything
    python "TYPE B/round2/build_round2.py" --only B4_t080_a60 deep:B3_t200_w30
    python "TYPE B/round2/build_round2.py" --no-stl
    python "TYPE B/round2/build_round2.py" --deep-offsets 4.7 3.7 2.7  # force

``--deep-offsets`` overrides the computed limits. The values above are the ones
first proposed in docs/11, which used the nominal section. Built at those, the
wall checks fail at the tapered socket floors, the collars and the DP's
coupling-wire boss; the verification report says where.
"""

import argparse
import csv
import math
import os
import sys

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
TYPE_B = os.path.dirname(HERE)
REPO = os.path.dirname(TYPE_B)
sys.path.insert(0, TYPE_B)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import build_finger_type_b as B  # noqa: E402
import build_flexure_families as F  # noqa: E402
import verify_type_b as V  # noqa: E402

GAP = 0.3             # as-printed clearance between bearing surfaces
LEVER_MARGIN = 0.3    # B4: tendon lever kept at least this at target flexion (mm)
TARGET_FLEX_DEG = {"MCP": 90.0, "PIP": 100.0, "DIP": 80.0}
SEAT_LIP = 0.35       # B8: cup rim at zm + SEAT_LIP*(r+GAP): ~139 deg of wrap
SEAT_WALL = 0.8       # B8: material outside the cup
SHANK = 0.6           # B8: knuckle shank half-height as a fraction of r
NECK_LEN = 0.8        # B9: flat length of the neck
NOTCH_PAL_DEG = 40.0  # B9: palmar face angle from the finger axis: ~100 deg range
NOTCH_DOR_DEG = 15.0  # B9: dorsal side only needs to open
LEAF_T = 0.75         # B8/B9 return leaves (PIP; graded like round 1)


def joint_of(name):
    return name.split()[0]


def section_scale(cs):
    """Section height relative to the PIP, for grading round-2 dimensions."""
    return cs[1] / B.CS_PIP[1]


def lanes(cs, outer_half_needed):
    """Each side: an inner bearing lane and an outer spring lane, equal widths,
    LANE_GAP apart, outside the tendon corridor and inside the collar."""
    x_in, x_out = F.side_band(cs, outer_half_needed)
    w = (x_out - x_in - F.LANE_GAP) / 2
    if w < F.MIN_LEAF_W:
        raise ValueError(f"lanes of {w:.2f} mm, below {F.MIN_LEAF_W}")
    cw, ch, cr = B.collar_dims(cs)
    inner = (x_in, x_in + w)
    hh_inner = B.half_height(cw, ch, cr, inner[1]) - F.EDGE
    return inner, (x_out - w, x_out), w, hh_inner


def solid_gap(a, b):
    return a.distance(b)


# ---------------------------------------------------------------------------
# B4: rolling contact, crossed straps
# ---------------------------------------------------------------------------
def lobe_polygon(R, Y, z0, apex, sign):
    """Convex lobe in (y, z): a disc of radius R whose apex is at `apex`, cut by
    the collar face z0 and limited to |y| <= Y. sign=+1 grows from a proximal face
    (z increasing), -1 from a distal face."""
    zc = apex - sign * R
    dz = sign * (z0 - zc)          # > 0 when the collar face cuts the disc
    if dz > 0:
        Y = min(Y, math.sqrt(R * R - dz * dz))
    pts = [(-Y, z0)]
    for i in range(F.PTS):
        y = -Y + 2 * Y * i / (F.PTS - 1)
        pts.append((y, zc + sign * math.sqrt(max(R * R - y * y, 0.0))))
    pts.append((Y, z0))
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def rolling(t, angle_deg, offsets):
    def flexure(cs, spec, z0, Fl, name):
        j = joint_of(name)
        tj = t * F.GRADE[j]
        beta = math.radians(angle_deg / 2)
        hs = Fl / 2 * math.tan(beta)
        d = tj / math.cos(beta)
        inner, outer, w, hh = lanes(cs, hs + d / 2)
        zm = z0 + Fl / 2
        R = (offsets[j] - LEVER_MARGIN) / math.sin(math.radians(TARGET_FLEX_DEG[j]) / 2)
        R = min(R, hh)
        if R < 0.8:
            raise ValueError(f"{name}: rolling radius {R:.2f} mm is too small for "
                             f"a {offsets[j]:.2f} mm tendon offset")
        Y = min(R, hh)
        prox = lobe_polygon(R, Y, z0, zm - GAP / 2, +1)
        dist = lobe_polygon(R, Y, z0 + Fl, zm + GAP / 2, -1)
        lp = F.yz_prism(prox, *inner)
        ld = F.yz_prism(dist, *inner)
        z1 = z0 + Fl
        strip_a = [(hs + d / 2, z0), (-hs + d / 2, z1), (-hs - d / 2, z1), (hs - d / 2, z0)]
        strip_b = [(-hs + d / 2, z0), (hs + d / 2, z1), (hs - d / 2, z1), (-hs - d / 2, z0)]
        xa = F.yz_prism(strip_a, *outer).fuse(F.yz_prism(strip_b, *outer)).clean()
        solids = F.mirrored([lp, ld, xa])
        ls = Fl / math.cos(beta)
        return solids, dict(t=tj, w=w, angle=angle_deg, strip_len=ls, roll_r=R,
                            k_over_E=4 * (w * tj ** 3 / 12) / ls,
                            bearing_gap=solid_gap(lp, ld), bearing="rolling",
                            pivot_y=0.0, bearing_w_total=2 * w)
    return flexure


# ---------------------------------------------------------------------------
# B8: knuckle in a cup (contact pad), leaves return
# ---------------------------------------------------------------------------
def knuckle(r_pip, y_pip, t_leaf=LEAF_T):
    def flexure(cs, spec, z0, Fl, name):
        j = joint_of(name)
        sc = section_scale(cs)
        r, yp, tl = r_pip * sc, y_pip * sc, t_leaf * F.GRADE[j]
        inner, outer, w, hh = lanes(cs, tl / 2)
        R2 = r + GAP
        if abs(yp) + R2 + SEAT_WALL > hh:
            raise ValueError(f"{name}: cup at y={yp:.2f} r={R2:.2f} does not fit in {hh:.2f}")
        zm = z0 + Fl / 2
        hs = SHANK * r
        psi0 = math.pi - math.asin(hs / r)
        prox = [(yp - hs, z0)]
        for i in range(F.PTS):
            p = -psi0 + 2 * psi0 * i / (F.PTS - 1)
            prox.append((yp + r * math.sin(p), zm + r * math.cos(p)))
        prox.append((yp + hs, z0))
        zs = zm + SEAT_LIP * R2
        psis = math.acos(SEAT_LIP)
        yl, yr = max(yp - R2 - SEAT_WALL, -hh), min(yp + R2 + SEAT_WALL, hh)
        z1 = z0 + Fl
        cup = [(yl, z1), (yl, zs)]
        for i in range(F.PTS):
            p = -psis + 2 * psis * i / (F.PTS - 1)
            cup.append((yp + R2 * math.sin(p), zm + R2 * math.cos(p)))
        cup += [(yr, zs), (yr, z1)]
        kp = F.yz_prism(prox, *inner)
        kd = F.yz_prism(cup, *inner)
        leaf = F.yz_prism(F.leaf_polygon(tl, 1.0, z0, Fl), *outer)
        solids = F.mirrored([kp, kd, leaf])
        # The shank meets the cup rim at this relative rotation.
        seat_rom = 180 - math.degrees(psis) - math.degrees(math.asin(hs / R2))
        return solids, dict(t=tl, w=w, knuckle_r=r, pivot_y=yp, seat_rom_deg=seat_rom,
                            k_over_E=2 / F.leaf_compliance(tl, 1.0, w, Fl),
                            bearing_gap=solid_gap(kp, kd), bearing="knuckle",
                            bearing_w_total=2 * w)
    return flexure


# ---------------------------------------------------------------------------
# B9: notched compression strut on the neutral axis, leaves return
# ---------------------------------------------------------------------------
def strut(t_neck, t_leaf=LEAF_T):
    def flexure(cs, spec, z0, Fl, name):
        j = joint_of(name)
        tn, tl = t_neck * F.GRADE[j], t_leaf * F.GRADE[j]
        inner, outer, w, hh = lanes(cs, tl / 2)
        zm = z0 + Fl / 2
        tp, td = math.tan(math.radians(NOTCH_PAL_DEG)), math.tan(math.radians(NOTCH_DOR_DEG))
        top, bot = [], []
        n = 2 * F.PTS + 1
        for i in range(n):
            z = z0 + Fl * i / (n - 1)
            u = max(abs(z - zm) - NECK_LEN / 2, 0.0)
            top.append((min(tn / 2 + u * td, hh), z))
            bot.append((-min(tn / 2 + u * tp, hh), z))
        poly = top + list(reversed(bot))
        web = F.yz_prism(poly, *inner)
        leaf = F.yz_prism(F.leaf_polygon(tl, 1.0, z0, Fl), *outer)
        comp = 0.0
        for (ya, za), (yb, zb), (ya2, _), (yb2, _) in zip(top, top[1:], bot, bot[1:]):
            ha, hb = ya - ya2, yb - yb2
            comp += (zb - za) * (12 / (w * ha ** 3) + 12 / (w * hb ** 3)) / 2
        k_web = 2 / comp
        k_leaf = 2 / F.leaf_compliance(tl, 1.0, w, Fl)
        return F.mirrored([web, leaf]), dict(
            t=tl, w=w, neck_t=tn, neck_len=NECK_LEN, k_over_E=k_web + k_leaf,
            k_web_over_E=k_web, bearing="strut", pivot_y=0.0,
            neck_area_mm2=2 * w * tn, bearing_w_total=2 * w)
    return flexure


# ---------------------------------------------------------------------------
# deep tendon offset
# ---------------------------------------------------------------------------
def deepest_offsets(boss_clearance=0.5):
    """Deepest palmar tendon offset per joint keeping the builder's MIN_WALL of
    material round the 3 mm channel everywhere it runs, and boss_clearance to the
    coupling-wire boss holes. Returns {joint: (offset, what limits it, all)}."""
    r, wall = B.CHAN_TENDON_D / 2, B.MIN_WALL
    c = B.COLLAR_LEN
    L1, L2, L3 = B.L_PHAL1 - 2 * c, B.L_PHAL2 - 2 * c, B.L_PHAL3 - c
    floor = lambda s: s["end_len"] + B.AX_CLR  # noqa: E731
    b = B.ANCHOR_BOSS
    out = {}
    for j, cs, nxt, L, spec in (("MCP", B.CS_MCP, B.CS_PIP, L1, B.MCP),
                                ("PIP", B.CS_PIP, B.CS_DIP, L2, B.PIP),
                                ("DIP", B.CS_DIP, B.CS_TIP, L3, B.DIP)):
        cs_d = B.section_at(cs, nxt, L, floor(spec))
        lim = {"distal phalanx at its socket floor": cs_d[1] / 2 - wall - r,
               "collar": B.collar_dims(cs)[1] / 2 - wall - r,
               ("flange" if j == "MCP" else "proximal phalanx at its distal end"):
                   (B.FLANGE["h"] / 2 if j == "MCP" else cs[1] / 2) - wall - r}
        if j == "DIP":
            for ph, h0, h1, Lp, bz in (("DP", B.CS_DIP[1], B.CS_TIP[1], L3, b["offset_from_joint"]),
                                       ("MP", B.CS_PIP[1], B.CS_DIP[1], L2, L2 - b["offset_from_joint"])):
                y_top = -B.section_h(h0, h1, Lp, bz + b["boss_wd"] / 2) / 2 + b["hole_into_body"]
                lim[f"{ph} coupling-wire boss hole"] = -y_top - boss_clearance - r
        key = min(lim, key=lim.get)
        out[j] = (math.floor(lim[key] * 20 + 1e-9) / 20, key, lim)
    return out


# ---------------------------------------------------------------------------
# VARIANTS
# ---------------------------------------------------------------------------
AS_BUILT = {}  # filled from the round-1 layouts in main()


def new_designs(offsets):
    return {
        "B4_t080_a60": (dict(family="B4", strap_t=0.8, angle=60), rolling(0.8, 60, offsets)),
        "B4_t100_a60": (dict(family="B4", strap_t=1.0, angle=60), rolling(1.0, 60, offsets)),
        "B8_y00_r150": (dict(family="B8", pad_y=0.0, knuckle_r=1.5), knuckle(1.5, 0.0)),
        "B8_y20_r125": (dict(family="B8", pad_y=2.0, knuckle_r=1.25), knuckle(1.25, 2.0)),
        "B9_n100": (dict(family="B9", neck_t=1.0), strut(1.0)),
        "B9_n150": (dict(family="B9", neck_t=1.5), strut(1.5)),
    }


#: Round-1 variants given a deep-offset copy: the two the analysis singled out,
#: plus the softest and stiffest of each family by its own k estimate (ties broken
#: towards the larger contrast), and the lattice bracketed by strut scale.
DEEP_ROUND1 = {
    "B1": ("B1_t100_notch100", "B1_t200_notch050"),
    "B3": ("B3_t100_w20", "B3_t200_w30"),
    "B5": ("B5_t100_a75", "B5_t200_a45"),
    "B6": ("B6_n6_t100", "B6_n4_t200"),
    "lattice": ("B_T090_X3", "B_T120_X3"),
}


def all_variants(deep):
    """name -> (outdir, params, build kwargs, deep?)"""
    out = {}
    for name, (params, flex) in new_designs(AS_BUILT).items():
        out[name] = (HERE, params, dict(flexure=flex), False)
    for fam, names in DEEP_ROUND1.items():
        for n in names:
            if fam == "lattice":
                out["deep:" + n] = (os.path.join(HERE, "deep_offset"), dict(family="lattice", source=n),
                                    dict(**B.VARIANTS[n], tendon_offsets=deep), True)
            else:
                params, flex = F.FAMILIES[fam]["variants"][n]
                out["deep:" + n] = (os.path.join(HERE, "deep_offset"),
                                    dict(family=fam, source=n, **params),
                                    dict(flexure=flex, tendon_offsets=deep), True)
    for name, (params, flex) in new_designs(deep).items():
        out["deep:" + name] = (os.path.join(HERE, "deep_offset"), dict(source=name, **params),
                               dict(flexure=flex, tendon_offsets=deep), True)
    return out


# ---------------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------------
def folder_name(name):
    return name.replace("deep:", "") + ("_deep" if name.startswith("deep:") else "")


def summary(name, params, parts, rep, fails):
    rows = []
    for j in ("MCP", "PIP", "DIP"):
        info = rep["lattice"][j]
        row = dict(variant=folder_name(name), joint=j)
        row.update(params)
        if "palmar" in info:   # lattice
            row.update(palmar_strut_mm=round(info["palmar"]["t"], 3),
                       dorsal_strut_mm=round(info["dorsal"]["t"], 3))
        else:
            for k, v in info.items():
                if k in ("x_span", "k_over_E", "bearing_gap"):
                    continue
                key = f"{k}_mm" if k in ("t", "t_root", "w", "notch_len", "web_h", "strip_len",
                                        "roll_r", "knuckle_r", "pivot_y", "neck_t", "neck_len") else k
                row[key] = round(v, 3) if isinstance(v, float) else v
            row["k_over_E_mm3"] = round(info["k_over_E"], 4)
            if "bearing_gap" in info:
                row["bearing_gap_mm"] = round(info["bearing_gap"], 3)
        row["flex_len_mm"] = rep["specs"][j]["flex_len"]
        row["tendon_moment_arm_mm"] = round(-rep["layouts"][j]["tendon_y"], 2)
        row["module_volume_mm3"] = round(parts[F.MODULE_FOR[j]].Volume(), 1)
        row["checks"] = "pass" if not fails else f"{len(fails)} failed"
        rows.append(row)
    return rows


def run(name, outdir, params, kwargs, stl):
    print(f"=== {name}")
    parts, z, rep = B.build_finger(verbose=False, **kwargs)
    problems = B.check(parts, z, rep)
    vrows, _, _ = V.verify(folder_name(name), {}, built=(parts, z, rep))
    fails = [r for r in vrows if r["result"] != "pass"] + [dict(check=p) for p in problems]
    for f in fails:
        print("  FAIL", f["check"], f.get("value", ""))
    print(f"  {sum(r['result'] == 'pass' for r in vrows)}/{len(vrows)} verification checks"
          + ("" if not problems else f"; build checks failed: {problems}"))
    B.export(parts, z, os.path.join(outdir, folder_name(name)), B.MODULES, stl=stl, assembly=True)
    return parts, rep, summary(name, params, parts, rep, fails), vrows, bool(fails)


def write(outdir, rows, vrows):
    fields = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    with open(os.path.join(outdir, "variants_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(outdir, "verification_report.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(vrows[0]))
        w.writeheader()
        w.writerows(vrows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="build only these (deep copies are deep:<name>)")
    ap.add_argument("--no-stl", action="store_true")
    ap.add_argument("--deep-offsets", nargs=3, type=float, metavar=("MCP", "PIP", "DIP"),
                    help="force the deep tendon offsets (mm) instead of the computed limits")
    args = ap.parse_args(argv)

    _, _, rep0 = B.build_finger(flexure=F.FAMILIES["B3"]["variants"]["B3_t100_w20"][1], verbose=False)
    AS_BUILT.update({j: -rep0["layouts"][j]["tendon_y"] for j in ("MCP", "PIP", "DIP")})
    lim = deepest_offsets()
    deep = ({j: v for j, v in zip(("MCP", "PIP", "DIP"), args.deep_offsets)} if args.deep_offsets
            else {j: lim[j][0] for j in lim})
    print("as-built tendon offsets:", {j: round(v, 2) for j, v in AS_BUILT.items()})
    for j, (v, why, all_) in lim.items():
        print(f"deepest {j}: {v:.2f} mm, limited by the {why} "
              f"({', '.join(f'{k} {x:.2f}' for k, x in all_.items())})")
    print("deep offsets used:", deep)

    groups = {}
    bad = False
    phalanges_done = set()
    for name, (outdir, params, kwargs, is_deep) in all_variants(deep).items():
        if args.only and name not in args.only:
            continue
        try:
            parts, rep, rows, vrows, failed = run(name, outdir, params, kwargs, not args.no_stl)
        except ValueError as exc:
            print(f"  NOT BUILT: {exc}")
            bad = True
            continue
        if is_deep and outdir not in phalanges_done:
            # Deep phalanges differ from round 1 (the channel moves), and are the
            # same for every deep variant: written once.
            B.export(parts, {}, os.path.join(outdir, "deep_phalanges"), B.PHALANGES,
                     stl=not args.no_stl, assembly=False)
            phalanges_done.add(outdir)
        g = groups.setdefault(outdir, ([], []))
        g[0].extend(rows)
        g[1].extend(vrows)
        bad |= failed
    for outdir, (rows, vrows) in groups.items():
        if not args.only:
            write(outdir, rows, vrows)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
