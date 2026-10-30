"""
Type B flexure families B1, B3, B5 and B6 (+ the B7 taper option on B3/B6).

Every family uses exactly the same finger as the lattice designs: phalanges,
tabs, sockets, pins, collars, flange, tendon and sensor channels and flex-zone
lengths all come from build_finger_type_b.py. Only the TPU between the two
collars of each joint changes, so test results compare the flexures alone.

    B1  hourglass       two elliptical-notch webs, one each side of the tendon
    B3  dual leaf       one flat leaf each side of the tendon, side by side
    B5  crossed strip   cross-axis pivot: two strip directions in interleaved
                        lanes (A B | B A), crossing in side view but never touching
    B6  multi leaf      2 or 3 thinner-width leaves each side, same total width
                        and thickness as the B3 w=2.0 leaves (equal material)
    B7  taper           option on B3/B6 leaves: thicker roots, thin middle

All flexures sit on the section's centre line (y = 0), so each joint bends
about the middle of its section. Thickness values in variant names are the
PIP values; the MCP and DIP are graded by the same ratios as the original
lattice struts (MCP x1.27, DIP x0.82), so the bigger joint stays stiffer.

    python "TYPE B/build_flexure_families.py"               # all families
    python "TYPE B/build_flexure_families.py" B3 B5         # some families
    python "TYPE B/build_flexure_families.py" B3 --only B3_t100_w20
"""

import argparse
import csv
import math
import os
import sys

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_finger_type_b as B  # noqa: E402
import verify_type_b as V  # noqa: E402

GRADE = {"MCP": 0.70 / 0.55, "PIP": 1.0, "DIP": 0.45 / 0.55}
EDGE = 0.3            # flexure kept this far inside the collar outline
LANE_GAP = 0.6        # clear gap between neighbouring leaves / strip lanes
MIN_LEAF_W = 0.6      # narrowest leaf or lane that is still worth printing
MIN_FLEX_T = 0.6      # thinnest flexure section
PTS = 41              # points per curved edge


def corridor_half():
    return B.CHAN_TENDON_D / 2 + B.TENDON_CLEARANCE


def joint_of(name):
    return name.split()[0]


def yz_prism(pts, x0, x1):
    """Closed (y, z) polygon extruded across x0..x1."""
    return (cq.Workplane("YZ").workplane(offset=x0)
            .polyline(pts).close().extrude(x1 - x0).val())


def mirrored(solids):
    return solids + [s.mirror("YZ") for s in solids]


def thickness_profile(t_mid, taper, z0, F):
    """(z, t) samples of a leaf: uniform when taper == 1, otherwise a smooth
    parabola from taper*t_mid at both roots to t_mid at the middle."""
    out = []
    for i in range(PTS):
        s = i / (PTS - 1)
        out.append((z0 + s * F, t_mid * (1 + (taper - 1) * (2 * s - 1) ** 2)))
    return out


def leaf_polygon(t_mid, taper, z0, F):
    prof = thickness_profile(t_mid, taper, z0, F)
    if taper == 1:
        prof = [prof[0], prof[-1]]
    return [(t / 2, z) for z, t in prof] + [(-t / 2, z) for z, t in reversed(prof)]


def leaf_compliance(t_mid, taper, w, F):
    """integral of dz / I(z) for one leaf, Euler-Bernoulli."""
    prof = thickness_profile(t_mid, taper, 0, F)
    tot = 0.0
    for (za, ta), (zb, tb) in zip(prof, prof[1:]):
        ia, ib = w * ta ** 3 / 12, w * tb ** 3 / 12
        tot += (zb - za) * (1 / ia + 1 / ib) / 2
    return tot


def side_band(cs, half_needed):
    """Lateral range (x_in, x_out) on one side, outside the tendon corridor,
    where the collar is at least half_needed + EDGE tall above and below y=0."""
    cw, ch, cr = B.collar_dims(cs)
    x_out = cw / 2 - EDGE
    while x_out > corridor_half() and B.half_height(cw, ch, cr, x_out) - EDGE < half_needed:
        x_out -= 0.01
    return corridor_half(), x_out


# ---------------------------------------------------------------------------
# B3 / B6 / B7: side-by-side leaves
# ---------------------------------------------------------------------------
def leaves(t, total_w, n_per_side, taper=1.0):
    def flexure(cs, spec, z0, F, name):
        j = joint_of(name)
        tj = t * GRADE[j]
        if tj < MIN_FLEX_T:
            raise ValueError(f"{name}: leaf {tj:.2f} mm below {MIN_FLEX_T} mm")
        x_in, x_out = side_band(cs, tj * taper / 2)
        w = total_w / n_per_side
        span = n_per_side * w + (n_per_side - 1) * LANE_GAP
        if w < MIN_LEAF_W or x_out - span < x_in - 1e-9:
            raise ValueError(f"{name}: {n_per_side} leaves of {w:.2f} mm do not fit "
                             f"in {x_out - x_in:.2f} mm beside the tendon corridor")
        poly = leaf_polygon(tj, taper, z0, F)
        solids = []
        for i in range(n_per_side):
            xb = x_out - i * (w + LANE_GAP)
            solids.append(yz_prism(poly, xb - w, xb))
        solids = mirrored(solids)
        comp = leaf_compliance(tj, taper, w, F)
        k_over_e = 2 * n_per_side / comp
        return solids, dict(t=tj, t_root=tj * taper, w=w, n=2 * n_per_side, taper=taper,
                            k_over_E=k_over_e, x_span=(x_out - span, x_out))
    return flexure


# ---------------------------------------------------------------------------
# B1: elliptical-notch (hourglass) webs
# ---------------------------------------------------------------------------
def hourglass(throat, notch_frac, w_web=3.0):
    def flexure(cs, spec, z0, F, name):
        j = joint_of(name)
        tj = throat * GRADE[j]
        cw, ch, cr = B.collar_dims(cs)
        x_out = cw / 2 - EDGE
        x_in = x_out - w_web
        if x_in < corridor_half() - 1e-9:
            raise ValueError(f"{name}: {w_web} mm web does not fit beside the corridor")
        # web height limited by the collar's rounded corner at the outer face
        hb = 2 * (B.half_height(cw, ch, cr, x_out) - EDGE)
        if hb <= tj + 0.5:
            raise ValueError(f"{name}: no room for a notch")
        a = (hb - tj) / 2
        ln = notch_frac * F
        zm = z0 + F / 2
        prof = []
        for i in range(PTS):
            z = z0 + F * i / (PTS - 1)
            u = (z - zm) / (ln / 2)
            half = hb / 2 if abs(u) >= 1 else tj / 2 + a * (1 - math.sqrt(1 - u * u))
            prof.append((z, half))
        # make sure the throat is sampled exactly
        poly = [(h, z) for z, h in prof] + [(-h, z) for z, h in reversed(prof)]
        solids = mirrored([yz_prism(poly, x_in, x_out)])
        # compliance, integrated finely
        comp, n = 0.0, 2000
        for i in range(n):
            z = (i + 0.5) / n * F - F / 2
            u = z / (ln / 2)
            h = hb if abs(u) >= 1 else tj + 2 * a * (1 - math.sqrt(1 - u * u))
            comp += (F / n) / (w_web * h ** 3 / 12)
        return solids, dict(t=tj, w=w_web, notch_len=ln, web_h=hb, k_over_E=2 / comp)
    return flexure


# ---------------------------------------------------------------------------
# B5: cross-axis flexural pivot
# ---------------------------------------------------------------------------
def crossed_strips(t, angle_deg):
    def flexure(cs, spec, z0, F, name):
        j = joint_of(name)
        tj = t * GRADE[j]
        beta = math.radians(angle_deg / 2)
        hs = F / 2 * math.tan(beta)          # strip end offset from y = 0
        d = tj / math.cos(beta)              # strip thickness measured along y
        x_in, x_out = side_band(cs, hs + d / 2)
        w = (x_out - x_in - LANE_GAP) / 2
        if w < MIN_LEAF_W:
            raise ValueError(f"{name}: {angle_deg} deg strips {tj:.2f} mm thick leave "
                             f"{w:.2f} mm lanes, below {MIN_LEAF_W}")
        z1 = z0 + F
        strip_a = [(hs + d / 2, z0), (-hs + d / 2, z1), (-hs - d / 2, z1), (hs - d / 2, z0)]
        strip_b = [(y, z) for (y, z) in [(-hs + d / 2, z0), (hs + d / 2, z1), (hs - d / 2, z1), (-hs - d / 2, z0)]]
        solids = mirrored([yz_prism(strip_a, x_out - w, x_out),       # outer lane: A
                           yz_prism(strip_b, x_in, x_in + w)])        # inner lane: B
        ls = F / math.cos(beta)
        # each strip carries the joint rotation in bending; ignores the
        # axial coupling a real cross pivot has, so use for ranking only
        k_over_e = 4 * (w * tj ** 3 / 12) / ls
        return solids, dict(t=tj, w=w, angle=angle_deg, strip_len=ls, k_over_E=k_over_e)
    return flexure


# ---------------------------------------------------------------------------
# VARIANTS
# ---------------------------------------------------------------------------
T_LEVELS = (1.0, 1.25, 1.5, 2.0)


def tag(v, scale=100):
    return f"{round(v * scale):03d}" if scale == 100 else f"{round(v * scale):02d}"


FAMILIES = {}
fam = FAMILIES.setdefault("B3", dict(folder="B3_dual_leaf", variants={}))
for t in T_LEVELS:
    for w in (2.0, 3.0):
        fam["variants"][f"B3_t{tag(t)}_w{tag(w, 10)}"] = (dict(t=t, w=w, taper=1.0), leaves(t, w, 1))
for t in (1.0, 1.5):
    for r in (1.5, 2.0):
        fam["variants"][f"B3_t{tag(t)}_w30_taper{tag(r, 10)}"] = (dict(t=t, w=3.0, taper=r), leaves(t, 3.0, 1, r))

fam = FAMILIES.setdefault("B6", dict(folder="B6_multi_leaf", variants={}))
for n in (2, 3):
    for t in T_LEVELS:
        fam["variants"][f"B6_n{2 * n}_t{tag(t)}"] = (dict(t=t, leaves=2 * n, total_w_per_side=2.0, taper=1.0),
                                                     leaves(t, 2.0, n))
for r in (1.5, 2.0):
    fam["variants"][f"B6_n4_t150_taper{tag(r, 10)}"] = (dict(t=1.5, leaves=4, total_w_per_side=2.0, taper=r),
                                                        leaves(1.5, 2.0, 2, r))

fam = FAMILIES.setdefault("B5", dict(folder="B5_crossed_strip", variants={}))
for t in T_LEVELS:
    for a in (45, 60, 75):
        fam["variants"][f"B5_t{tag(t)}_a{a}"] = (dict(t=t, angle=a), crossed_strips(t, a))

fam = FAMILIES.setdefault("B1", dict(folder="B1_hourglass", variants={}))
for t in T_LEVELS:
    for f in (1.0, 0.5):
        fam["variants"][f"B1_t{tag(t)}_notch{tag(f)}"] = (dict(throat=t, notch_frac=f), hourglass(t, f))


# ---------------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------------
MODULE_FOR = {"MCP": "01_MCP_module_with_flange", "PIP": "03_PIP_module", "DIP": "05_DIP_module"}


def run_variant(fam_key, name, params, flexure, outdir, stl=True):
    print(f"=== {name}")
    parts, z, rep = B.build_finger(flexure=flexure, verbose=False)
    problems = B.check(parts, z, rep)
    vrows, _, _ = V.verify(name, {}, built=(parts, z, rep))
    fails = [r for r in vrows if r["result"] != "pass"] + [dict(check=p) for p in problems]
    for f in fails:
        print("  FAIL", f["check"], f.get("value", ""))
    print(f"  {len(vrows) - len([r for r in vrows if r['result'] != 'pass'])}/{len(vrows)} "
          f"verification checks passed" + ("" if not problems else f"; {len(problems)} build checks failed"))
    B.export(parts, z, os.path.join(outdir, name), B.MODULES, stl=stl, assembly=True)
    rows = []
    for j in ("MCP", "PIP", "DIP"):
        info = rep["lattice"][j]
        row = dict(variant=name, joint=j)
        row.update({k: v for k, v in params.items()})
        row.update({f"{k}_mm" if k in ("t", "t_root", "w", "notch_len", "web_h", "strip_len") else k:
                    (round(v, 3) if isinstance(v, float) else v)
                    for k, v in info.items() if k not in ("x_span", "k_over_E")})
        row["k_over_E_mm3"] = round(info["k_over_E"], 4)
        row["flex_len_mm"] = rep["specs"][j]["flex_len"]
        row["tendon_moment_arm_mm"] = round(-rep["layouts"][j]["tendon_y"], 2)
        row["module_volume_mm3"] = round(parts[MODULE_FOR[j]].Volume(), 1)
        row["checks"] = "pass" if not fails else f"{len(fails)} failed"
        rows.append(row)
    return rows, vrows, bool(fails)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("families", nargs="*", help=f"families (default all): {', '.join(FAMILIES)}")
    ap.add_argument("--only", nargs="*", help="build only these variant names")
    ap.add_argument("--no-stl", action="store_true")
    args = ap.parse_args(argv)
    bad = False
    for key in args.families or list(FAMILIES):
        fam = FAMILIES[key]
        outdir = os.path.join(HERE, fam["folder"])
        rows, vrows, skipped = [], [], []
        for name, (params, flexure) in fam["variants"].items():
            if args.only and name not in args.only:
                continue
            try:
                r, v, failed = run_variant(key, name, params, flexure, outdir, stl=not args.no_stl)
            except ValueError as exc:
                print(f"  NOT BUILT: {exc}")
                skipped.append((name, str(exc)))
                bad = True
                continue
            rows += r
            vrows += v
            bad |= failed
        if rows:
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
        for n, why in skipped:
            print(f"{n} not built: {why}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
