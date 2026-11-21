"""Turn the A8 meander study's run records into matrices, figures and a ranking.

Reads ``<study>/cases/*.json`` written by ``scripts/a8_meander_study.py`` and writes,
next to them:

* ``matrix_2turn.csv``, ``matrix_3turn.csv``, ``matrix_4turn.csv`` -- one row per spine
  sagitta, every reported quantity as a column;
* ``matrices.md`` -- the same, readable, with the selected design marked;
* ``exports_vs_replicas.csv`` -- the three supplied parts against their rebuilds;
* ``ranking.csv`` -- every candidate with its feasibility verdict and score;
* ``fig_*.png`` -- torque-angle curves, and the design-space maps.

How "best" is decided
---------------------

A spring-back element has to do three things, and the ranking takes them in order of
how badly failing each would hurt:

1. **Not fail.** Feasible only if
   * the strip clears the knuckle at rest by at least ``MIN_REST_CLEARANCE_MM`` -- a
     strip that only just clears in CAD touches once printed, and is then preloaded;
   * the solve runs through the whole PIP range, ``FULL_RANGE_DEG`` (the 0-100 deg
     placeholder range in docs/06), and the torque never falls as flexion increases.
     A fall is the strip snapping into the joint crease; the finger would lose its
     spring part-way through a movement. Every 2-turn variant does this somewhere
     between 75 and 91 deg, so passing at 90 is not enough;
   * the peak strain away from the clamps stays at or below ``STRAIN_LIMIT`` at
     90 deg -- engineering judgement for millions of cycles of a TPU, not a measured
     fatigue limit for this filament.
2. **Return the finger, from any angle.** The score is restoring torque per unit
   peak strain at 90 deg, ``T90 / eps90``: how much spring the design delivers for
   the damage it does to the material. It is independent of the modulus -- both
   terms scale together at these strains -- so the ranking survives the material
   being wrong, and it is the right figure of merit because absolute torque can then
   be set by section height (torque goes as h^3, strain as h, so the ratio goes as
   h^2: a design that is efficient at 1.2 mm stays efficient at 1.5).
3. **Still push near full extension.** Designs whose score is within
   ``SCORE_TIE_FRACTION`` of the best are treated as equal -- the export and its
   parametric rebuild differ by 1.3 %, which is the resolution of the score -- and
   among those the one with the most torque at 15 deg wins, then the lower profile.
   A spring that has little left near 0 deg leaves the finger hanging short of full
   extension.

Printability (narrowest true wall) is reported and flagged, not scored, because it
has fixes outside the spring's own geometry.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import matplotlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from barnes_ui.core.flexure.templates.a8_meander import (  # noqa: E402
    A8_PLAN_3TURN,
    A8MeanderParameters,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

#: Peak engineering strain allowed at 90 deg flexion, away from the clamps.
STRAIN_LIMIT = 0.20
#: Two 0.4 mm extrusion widths: the narrowest wall a 0.4 mm nozzle prints as a
#: proper perimeter pair rather than a single bead.
PRINTABLE_WIDTH_MM = 0.80
#: Smallest clearance between strip and finger at rest that counts as clear, mm.
MIN_REST_CLEARANCE_MM = 0.25
#: The whole PIP range analysed, deg. The torque must not fall anywhere in it.
FULL_RANGE_DEG = 100.0
#: Scores within this fraction of the best are treated as tied.
SCORE_TIE_FRACTION = 0.03
#: Torque sampled at these angles.
ANGLES = ("15", "30", "45", "60", "90")


def _get(record: dict, *path, default=None):
    value = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def knuckle_clearance(sagitta: float | None, axis_y: float = 15.905,
                      radius: float = 3.4) -> float | None:
    """Clearance between the strip's underside and the knuckle at rest, mm.

    Only the spine enters -- the underside is the spine less half the 1.2 mm section,
    whatever the plan path -- so it is computed from the sagitta. The run's own
    ``clearance_at_rest_mm`` is the minimum over every finger surface, and the strip's
    ends rest on the link tops at their rings by design, which makes that number
    about 0.1 mm for every case and says nothing about the joint.
    """
    if sagitta is None:
        return None
    p = A8MeanderParameters(plan=A8_PLAN_3TURN, sagitta=sagitta, n_turns=3)
    y = np.linspace(p.y_start, p.y_end, 4001)
    underside = p.spine_z(y) - p.height_z / 2.0
    return float(np.hypot(y - axis_y, underside).min() - radius)


def summarise(record: dict) -> dict:
    """The flat row a matrix shows for one run."""
    t90 = _get(record, "torque_n_mm", "90")
    t15 = _get(record, "torque_n_mm", "15")
    e90 = _get(record, "peak_strain_interior", "90")
    drop = record.get("first_torque_drop_deg")
    reached = record.get("reached_deg") or 0.0
    geometry = record.get("geometry") or {}
    reasons = []
    clearance = knuckle_clearance(record.get("sagitta"))
    if "geometric_interference_mm" in record:
        reasons.append(f"strip starts {record['geometric_interference_mm']:.2f} mm "
                       "inside the finger (spine too flat)")
    elif "failure" in record:
        reasons.append(f"analysis failed: {record['failure'][:80]}")
    else:
        if clearance is not None and clearance < MIN_REST_CLEARANCE_MM:
            reasons.append(f"clears the knuckle by only {clearance:.2f} mm at rest")
        if drop is not None and drop <= FULL_RANGE_DEG:
            reasons.append(f"snaps: torque falls at {drop:.0f} deg")
        elif reached < FULL_RANGE_DEG - 0.5:
            reasons.append(f"solve stopped at {reached:.0f} deg")
    if e90 is not None and e90 > STRAIN_LIMIT:
        reasons.append(f"strain {e90 * 100:.0f} % > {STRAIN_LIMIT * 100:.0f} %")
    row = {
        "label": record["label"],
        "kind": record.get("kind"),
        "n_turns": record.get("n_turns"),
        "sagitta_mm": record.get("sagitta"),
        "spine_radius_mm": geometry.get("spine_radius_mm"),
        "centreline_mm": geometry.get("centreline_length_mm"),
        "min_true_width_mm": geometry.get("min_true_width_mm"),
        "apex_top_z_mm": geometry.get("spine_apex_top_z_mm"),
        "k0_n_mm_per_rad": record.get("k0_n_mm_per_rad"),
        **{f"T{a}_n_mm": _get(record, "torque_n_mm", a) for a in ANGLES},
        "T_max_n_mm": record.get("torque_max_n_mm"),
        "reached_deg": reached,
        "knuckle_clearance_mm": knuckle_clearance(record.get("sagitta")),
        "energy_0_90_mJ": record.get("energy_0_90_n_mm"),
        "T15_over_T90": (t15 / t90) if t15 and t90 else None,
        "linearity_T90_over_k0": record.get("linearity_t90_over_k0"),
        **{f"strain_{a}_pct": (_get(record, "peak_strain_interior", a) or math.nan) * 100
           for a in ("30", "60", "90")},
        "strain_90_at_clamp_pct": (_get(record, "peak_strain_all", "90") or math.nan) * 100,
        "min_radius_90_mm": _get(record, "min_radius_from_axis_mm", "90"),
        "lateral_extent_0_mm": _get(record, "lateral_extent_mm", "0"),
        "lateral_extent_90_mm": _get(record, "lateral_extent_mm", "90"),
        "first_torque_drop_deg": drop,
        "efficiency_T90_per_strain": (t90 / e90) if t90 and e90 else None,
        "efficiency_T60_per_strain": (
            _get(record, "torque_n_mm", "60") / _get(record, "peak_strain_interior", "60")
            if _get(record, "torque_n_mm", "60") and _get(record, "peak_strain_interior", "60")
            else None),
        "printable": (geometry.get("min_true_width_mm", 99) >= PRINTABLE_WIDTH_MM)
        if geometry else None,
        "feasible": not reasons,
        "why_not": "; ".join(reasons),
        "cutbacks": record.get("cutbacks"),
        "wall_s": record.get("wall_seconds"),
    }
    return row


def select(candidates: list[dict]) -> str | None:
    """The selected label: best score, ties broken by torque at 15 deg, then profile."""
    if not candidates:
        return None
    top = max(r["efficiency_T90_per_strain"] for r in candidates)
    tied = [r for r in candidates
            if r["efficiency_T90_per_strain"] >= (1.0 - SCORE_TIE_FRACTION) * top]
    tied.sort(key=lambda r: (-(r["T15_n_mm"] or 0.0), r["apex_top_z_mm"] or 0.0))
    return tied[0]["label"]


def _fmt(value, digits=3):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "NO"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


MATRIX_COLUMNS = [
    ("sagitta_mm", "Spine sagitta (mm)"),
    ("spine_radius_mm", "Spine radius (mm)"),
    ("apex_top_z_mm", "Top above ring axis (mm)"),
    ("k0_n_mm_per_rad", "k0 (N·mm/rad)"),
    ("T15_n_mm", "T15° (N·mm)"),
    ("T30_n_mm", "T30° (N·mm)"),
    ("T60_n_mm", "T60° (N·mm)"),
    ("T90_n_mm", "T90° (N·mm)"),
    ("energy_0_90_mJ", "Energy 0–90° (mJ)"),
    ("T15_over_T90", "T15/T90"),
    ("strain_30_pct", "ε30° (%)"),
    ("strain_60_pct", "ε60° (%)"),
    ("strain_90_pct", "ε90° (%)"),
    ("strain_90_at_clamp_pct", "ε90° at clamp (%)"),
    ("efficiency_T60_per_strain", "T60/ε60 (N·mm)"),
    ("efficiency_T90_per_strain", "T90/ε90 (N·mm)"),
    ("reached_deg", "Solved to (°)"),
    ("min_radius_90_mm", "Closest to axis at 90° (mm)"),
    ("lateral_extent_90_mm", "Width at 90° (mm)"),
    ("min_true_width_mm", "Narrowest wall (mm)"),
    ("knuckle_clearance_mm", "Knuckle clearance (mm)"),
    ("feasible", "Feasible"),
    ("why_not", "Why not"),
]


def markdown_matrix(rows: list[dict], best_label: str | None) -> str:
    header = "| " + " | ".join(title for _, title in MATRIX_COLUMNS) + " |"
    rule = "|" + "---|" * len(MATRIX_COLUMNS)
    lines = [header, rule]
    for row in rows:
        cells = [_fmt(row[key]) for key, _ in MATRIX_COLUMNS]
        if row["label"] == best_label:
            cells = [f"**{c}**" for c in cells]
            cells[0] = "**★ " + cells[0][2:]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def plot_curves(records: list[dict], path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    cmap = plt.get_cmap("viridis")
    records = sorted(records, key=lambda r: r.get("sagitta") or 0)
    for i, record in enumerate(records):
        curve = record.get("curve") or {}
        if not curve.get("angle_deg"):
            continue
        colour = cmap(i / max(1, len(records) - 1))
        name = (record["label"].replace("export_A8_PIP_Meander_", "")
                if record.get("kind") == "export" else "")
        ax.plot([0] + curve["angle_deg"], [0] + curve["torque_n_mm"], color=colour,
                label=f"{name} sagitta {record.get('sagitta', 0):.2f} mm".strip())
    ax.set_xlabel("PIP flexion (deg)")
    ax.set_ylabel("Restoring torque (N·mm)")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8, ncol=2)
    fig.text(0.01, 0.01, "TPU 90A, Neo-Hookean E = 19.3 MPa (datasheet). Not "
             "experimentally validated.", fontsize=7, color="#a33")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_maps(rows: list[dict], path: Path) -> None:
    sweep = [r for r in rows if r["kind"] == "sweep"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    for ax, key, label in zip(
        axes,
        ("T90_n_mm", "strain_90_pct", "efficiency_T90_per_strain"),
        ("Restoring torque at 90° (N·mm)", "Peak strain at 90°, away from clamps (%)",
         "T90 / ε90 (N·mm) — the score"),
    ):
        for n_turns, marker in ((2, "o"), (3, "s"), (4, "^")):
            rows_n = [r for r in sweep if r["n_turns"] == n_turns and r[key] is not None
                      and not (isinstance(r[key], float) and math.isnan(r[key]))]
            # A value at 90 deg read after the strip has snapped is not a spring
            # characteristic: it is shown hollow and unjoined, not on the curve.
            clean = sorted((r["sagitta_mm"], r[key]) for r in rows_n
                           if not (r["first_torque_drop_deg"] is not None
                                   and r["first_torque_drop_deg"] <= 90.0))
            snapped = sorted((r["sagitta_mm"], r[key]) for r in rows_n
                             if r["first_torque_drop_deg"] is not None
                             and r["first_torque_drop_deg"] <= 90.0)
            line = None
            if clean:
                (line,) = ax.plot(*zip(*clean), marker=marker, label=f"{n_turns}-turn")
            if snapped:
                ax.plot(*zip(*snapped), marker=marker, ls="none", mfc="none",
                        color=line.get_color() if line else None,
                        label=f"{n_turns}-turn, after snapping")
        if key == "strain_90_pct":
            ax.axhline(STRAIN_LIMIT * 100, color="#a33", ls="--", lw=1, label="limit")
        ax.set_xlabel("Spine sagitta (mm)")
        ax.set_title(label, fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args(argv)

    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((args.study / "cases").glob("*.json"))]
    if not records:
        print("No run records found.", file=sys.stderr)
        return 1
    rows = [summarise(r) for r in records]

    candidates = [r for r in rows if r["kind"] in ("sweep", "export") and r["feasible"]
                  and r["efficiency_T90_per_strain"]]
    best = select(candidates)

    ranked = sorted(rows, key=lambda r: (not r["feasible"],
                                         -(r["efficiency_T90_per_strain"] or 0)))
    write_csv(args.study / "ranking.csv", ranked)

    sections = []
    for n_turns in (2, 3, 4):
        group = sorted((r for r in rows if r["kind"] == "sweep" and r["n_turns"] == n_turns),
                       key=lambda r: r["sagitta_mm"])
        if not group:
            continue
        write_csv(args.study / f"matrix_{n_turns}turn.csv", group)
        group_label = select([r for r in group if r["feasible"]
                              and r["efficiency_T90_per_strain"]])
        group_best = next((r for r in group if r["label"] == group_label), None)
        sections.append(f"### {n_turns}-turn\n\n"
                        + (f"Best in group: sagitta {group_best['sagitta_mm']:.1f} mm.\n\n"
                           if group_best else "No feasible variant in this group.\n\n")
                        + markdown_matrix(group, best if best in {r['label'] for r in group}
                                          else (group_best or {}).get("label")))
        plot_curves([rec for rec in records if rec.get("kind") == "sweep"
                     and rec.get("n_turns") == n_turns],
                    args.study / f"fig_torque_angle_{n_turns}turn.png",
                    f"A8 {n_turns}-turn strip: restoring torque vs flexion, by spine sagitta")

    exports = [r for r in rows if r["kind"] in ("export", "replica")]
    write_csv(args.study / "exports_vs_replicas.csv",
              sorted(exports, key=lambda r: (r["label"].split("_", 1)[1], r["kind"])))
    plot_curves([rec for rec in records if rec.get("kind") == "export"],
                args.study / "fig_torque_angle_exports.png",
                "Supplied A8 exports: restoring torque vs flexion")
    plot_maps(rows, args.study / "fig_design_space.png")

    text = ["# A8 meander matrices", "",
            f"Selected design: **{best}**" if best else "No feasible design.", ""]
    text += sections
    (args.study / "matrices.md").write_text("\n\n".join(text) + "\n", encoding="utf-8")
    print(f"best: {best}")
    for row in ranked[:8]:
        print(f"  {row['label']:<44} feasible={row['feasible']!s:<5} "
              f"T90={_fmt(row['T90_n_mm'])} eps90={_fmt(row['strain_90_pct'])}% "
              f"score={_fmt(row['efficiency_T90_per_strain'])} {row['why_not']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
