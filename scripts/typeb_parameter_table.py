"""Exact Type B design parameters per joint, from the CAD builder (no rounding by hand).

    python3 scripts/typeb_parameter_table.py

For every family and variant in TYPE B/build_flexure_families.py it calls the flexure builder
for the MCP, PIP and DIP and records what it actually builds (thickness, width, lengths ...),
then scans thickness upward to find where the geometry runs out (the width left per lane drops
below the 0.6 mm printing minimum). Writes docs/typeB_parameter_ranges.md and
results/typeB_parameter_ranges.csv.
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "TYPE B"))
import build_flexure_families as F  # noqa: E402
import build_finger_type_b as B  # noqa: E402

JOINTS = (("MCP", B.CS_MCP, B.MCP), ("PIP", B.CS_PIP, B.PIP), ("DIP", B.CS_DIP, B.DIP))
KEYS = ("t", "w", "w_web", "angle", "strip_len", "notch_len", "web_h", "n", "r", "lobe_r", "gap")


def info_of(fn, j, cs, spec):
    try:
        _, info = fn(cs, spec, 0.0, spec["flex_len"], f"{j} module")
        return {k: v for k, v in info.items() if not isinstance(v, (list, tuple, dict))}
    except Exception as ex:          # noqa: BLE001
        return {"error": str(ex)[:80]}


def main():
    rows = []
    for fam, d in F.FAMILIES.items():
        for name, (params, fn) in d["variants"].items():
            for j, cs, spec in JOINTS:
                inf = info_of(fn, j, cs, spec)
                rows.append(dict(family=fam, variant=name, joint=j, flex_len=spec["flex_len"],
                                 **{f"param_{k}": v for k, v in params.items()},
                                 **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in inf.items()
                                    if k != "k_over_E"}))
    cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("family", "variant", "joint"), k))
    out = REPO / "results" / "typeB_parameter_ranges.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    # B5 / B5i geometric limit: largest nominal t (PIP value; others graded) that still builds
    lim = []
    for fam, mk, angles in (("B5", F.crossed_strips, (45, 60, 75)), ("B5i", F.crossed_strips_inset, (45,))):
        for a in angles:
            tmax = None
            t = 0.5
            while t <= 4.0:
                ok = all("error" not in info_of(mk(t, a), j, cs, spec) for j, cs, spec in JOINTS)
                if ok: tmax = t
                t = round(t + 0.05, 2)
            lim.append((fam, a, tmax))
    print("GRADE", F.GRADE, "T_LEVELS", F.T_LEVELS, "MIN_LEAF_W", F.MIN_LEAF_W, "LANE_GAP", F.LANE_GAP, "EDGE", F.EDGE)
    for r in lim: print("LIMIT", *r)
    print("flex_len", {j: s["flex_len"] for j, _, s in JOINTS}, "CS", {j: c for j, c, _ in JOINTS})
    print("rows", len(rows), "->", out)


if __name__ == "__main__":
    main()
