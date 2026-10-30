"""Matrices, figures and the selected design for the printable A8 study on the index PIP.

Reads ``<study>/cases/*.json`` from ``scripts/a8_meander_study.py --finger index_pip
--groups printable`` and writes ``matrix_h<height>.csv`` per section height,
``matrices.md``, ``ranking.csv`` and figures.

How the design is chosen
------------------------

The first study (results/a8_meander_study) held the section fixed and found the
spring too weak, with the strain far below any limit. Section height is now a design
variable, which changes the question: not "most spring per unit strain", but **the
strongest spring that is still safe**.

1. Feasible only if the strip clears both cams at rest by at least
   ``MIN_REST_CLEARANCE_MM`` (checked in the study before solving, and again here from
   the record), the torque never falls anywhere in 0-100 deg, and the peak strain
   away from the clamps stays at or below ``STRAIN_LIMIT`` at 90 deg.
2. Among feasible designs, the most restoring torque at 90 deg wins.
3. Designs within ``TORQUE_TIE_FRACTION`` of it are tied, and the lower profile wins
   among them -- a strip standing proud of the finger catches on things.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

STRAIN_LIMIT = 0.20
MIN_REST_CLEARANCE_MM = 0.25
FULL_RANGE_DEG = 100.0
TORQUE_TIE_FRACTION = 0.03
ANGLES = ("15", "30", "45", "60", "90")


def _get(record, *path):
    value = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def summarise(r: dict) -> dict:
    g = r.get("geometry") or {}
    t90 = _get(r, "torque_n_mm", "90")
    e90 = _get(r, "peak_strain_interior", "90")
    drop = r.get("first_torque_drop_deg")
    reached = r.get("reached_deg") or 0.0
    reasons = []
    if "geometric_interference_mm" in r:
        reasons.append(f"starts {r['geometric_interference_mm']:.2f} mm inside the finger")
    elif "failure" in r:
        reasons.append(f"analysis failed: {r['failure'][:70]}")
    else:
        if (r.get("clearance_at_rest_mm") or 0.0) < MIN_REST_CLEARANCE_MM:
            reasons.append(f"clears the cams by only {r.get('clearance_at_rest_mm', 0):.2f} mm")
        if drop is not None and drop <= FULL_RANGE_DEG:
            reasons.append(f"snaps: torque falls at {drop:.0f} deg")
        elif reached < FULL_RANGE_DEG - 0.5:
            reasons.append(f"solve stopped at {reached:.0f} deg")
        if e90 is not None and e90 > STRAIN_LIMIT:
            reasons.append(f"strain {e90 * 100:.0f} % > {STRAIN_LIMIT * 100:.0f} %")
    return {
        "label": r["label"], "n_turns": r.get("n_turns"), "true_width_mm": r.get("true_width"),
        "height_mm": r.get("height"), "sagitta_mm": r.get("sagitta"),
        "spine_radius_mm": g.get("spine_radius_mm"),
        "top_above_axis_mm": g.get("spine_apex_top_z_mm"),
        "centreline_mm": g.get("centreline_length_mm"),
        "volume_mm3": g.get("volume_mm3"),
        "clearance_at_rest_mm": r.get("clearance_at_rest_mm"),
        "k0_n_mm_per_rad": r.get("k0_n_mm_per_rad"),
        **{f"T{a}_n_mm": _get(r, "torque_n_mm", a) for a in ANGLES},
        "T100_n_mm": r.get("torque_max_n_mm") if reached >= 99.5 else None,
        "energy_0_90_mJ": r.get("energy_0_90_n_mm"),
        "strain_30_pct": (_get(r, "peak_strain_interior", "30") or math.nan) * 100,
        "strain_60_pct": (_get(r, "peak_strain_interior", "60") or math.nan) * 100,
        "strain_90_pct": (e90 or math.nan) * 100,
        "strain_90_at_clamp_pct": (_get(r, "peak_strain_all", "90") or math.nan) * 100,
        "T90_per_strain_n_mm": (t90 / e90) if t90 and e90 else None,
        "width_at_90_mm": _get(r, "lateral_extent_mm", "90"),
        "reached_deg": reached, "first_torque_drop_deg": drop,
        "feasible": not reasons, "why_not": "; ".join(reasons),
        "wall_s": r.get("wall_seconds"), "cutbacks": r.get("cutbacks"),
    }


def select(rows: list[dict]) -> str | None:
    feasible = [r for r in rows if r["feasible"] and r["T90_n_mm"]]
    if not feasible:
        return None
    top = max(r["T90_n_mm"] for r in feasible)
    tied = [r for r in feasible if r["T90_n_mm"] >= (1 - TORQUE_TIE_FRACTION) * top]
    tied.sort(key=lambda r: (r["top_above_axis_mm"] or 0.0, -r["T90_n_mm"]))
    return tied[0]["label"]


def _fmt(v, d=3):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "NO"
    if isinstance(v, float):
        return f"{v:.{d}g}"
    return str(v)


COLUMNS = [
    ("sagitta_mm", "Sagitta (mm)"), ("spine_radius_mm", "Spine R (mm)"),
    ("top_above_axis_mm", "Top above bone axis (mm)"),
    ("k0_n_mm_per_rad", "k0 (N·mm/rad)"), ("T15_n_mm", "T15°"), ("T30_n_mm", "T30°"),
    ("T60_n_mm", "T60°"), ("T90_n_mm", "T90° (N·mm)"), ("T100_n_mm", "T100°"),
    ("energy_0_90_mJ", "Energy 0–90° (mJ)"), ("strain_60_pct", "ε60° (%)"),
    ("strain_90_pct", "ε90° (%)"), ("strain_90_at_clamp_pct", "ε90° at clamp (%)"),
    ("T90_per_strain_n_mm", "T90/ε90 (N·mm)"), ("clearance_at_rest_mm", "Rest clearance (mm)"),
    ("width_at_90_mm", "Width at 90° (mm)"), ("feasible", "Feasible"), ("why_not", "Why not"),
]


def table(rows: list[dict], best: str | None) -> str:
    out = ["| " + " | ".join(t for _, t in COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in rows:
        cells = [_fmt(r[k]) for k, _ in COLUMNS]
        if r["label"] == best:
            cells = [f"**{c}**" for c in cells]
            cells[0] = "**★ " + cells[0][2:]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def write_csv(path: Path, rows: list[dict]) -> None:
    if rows:
        with path.open("w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows([{k: ("" if v is None else v) for k, v in r.items()} for r in rows])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--study", type=Path, required=True)
    args = ap.parse_args(argv)
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((args.study / "cases").glob("*.json"))]
    rows = [summarise(r) for r in records]
    best = select(rows)
    write_csv(args.study / "ranking.csv",
              sorted(rows, key=lambda r: (not r["feasible"], -(r["T90_n_mm"] or 0))))

    md = ["# Printable A8 strip on the index PIP — matrices", "",
          f"Selected: **{best}**" if best else "No feasible design yet.", ""]
    groups = sorted({(r["n_turns"], r["true_width_mm"], r["height_mm"]) for r in rows})
    for n_turns, width, height in groups:
        g = sorted((r for r in rows if (r["n_turns"], r["true_width_mm"], r["height_mm"])
                    == (n_turns, width, height)), key=lambda r: r["sagitta_mm"])
        write_csv(args.study / f"matrix_{n_turns}T_w{width}_h{height}.csv", g)
        md += [f"## {n_turns} turns, true width {width} mm, height {height} mm", "",
               table(g, best), ""]
    (args.study / "matrices.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # Torque-angle curves: one panel per height for 3 turns, plus the 2-turn check.
    by_label = {r["label"]: r for r in records}
    panels = [k for k in groups]
    fig, axes = plt.subplots(1, len(panels), figsize=(4.6 * len(panels), 4.2), sharey=True,
                             squeeze=False)
    cmap = plt.get_cmap("viridis")
    for ax, (n_turns, width, height) in zip(axes[0], panels):
        g = sorted((r for r in rows if (r["n_turns"], r["true_width_mm"], r["height_mm"])
                    == (n_turns, width, height)), key=lambda r: r["sagitta_mm"])
        for i, row in enumerate(g):
            curve = by_label[row["label"]].get("curve") or {}
            if curve.get("angle_deg"):
                ax.plot([0] + curve["angle_deg"], [0] + curve["torque_n_mm"],
                        color=cmap(i / max(1, len(g) - 1)),
                        lw=2.4 if row["label"] == best else 1.4,
                        label=f"s {row['sagitta_mm']:.1f} mm")
        ax.set_title(f"{n_turns} turns, w {width}, h {height} mm", fontsize=10)
        ax.set_xlabel("PIP flexion (deg)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    axes[0][0].set_ylabel("Restoring torque (N·mm)")
    fig.text(0.01, 0.01, "TPU 90A, Neo-Hookean E = 19.3 MPa (datasheet). Index PIP from "
             "the hand assembly. Not experimentally validated.", fontsize=7, color="#a33")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(args.study / "fig_torque_angle.png", dpi=130)
    plt.close(fig)

    # Height trade-off for 3 turns at 1.2 mm width.
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for height in sorted({r["height_mm"] for r in rows if r["n_turns"] == 3}):
        g = sorted((r for r in rows if r["n_turns"] == 3 and r["height_mm"] == height
                    and r["true_width_mm"] == 1.2 and r["T90_n_mm"]),
                   key=lambda r: r["sagitta_mm"])
        if g:
            axes[0].plot([r["sagitta_mm"] for r in g], [r["T90_n_mm"] for r in g], "o-",
                         label=f"h {height} mm")
            axes[1].plot([r["sagitta_mm"] for r in g], [r["strain_90_pct"] for r in g], "o-",
                         label=f"h {height} mm")
    axes[0].set_title("Restoring torque at 90° (N·mm)", fontsize=10)
    axes[1].set_title("Peak strain at 90°, away from clamps (%)", fontsize=10)
    axes[1].axhline(STRAIN_LIMIT * 100, color="#a33", ls="--", lw=1, label="limit")
    for ax in axes:
        ax.set_xlabel("Spine sagitta (mm)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(args.study / "fig_height_tradeoff.png", dpi=130)
    plt.close(fig)

    print(f"best: {best}")
    for r in sorted(rows, key=lambda r: (not r["feasible"], -(r["T90_n_mm"] or 0))):
        print(f"  {r['label']:<28} T90={_fmt(r['T90_n_mm'])} eps90={_fmt(r['strain_90_pct'])}% "
              f"top={_fmt(r['top_above_axis_mm'])} {r['why_not']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
