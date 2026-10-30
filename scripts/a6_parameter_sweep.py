"""Sweep A6 leaf curvature, thickness and width, and pick the best valid combination.

What "best" means
-----------------

A6 is a spring-back: after the finger flexes, the leaf has to return it to straight.
What it has available for that is the energy it stored on the way down, so the
figure of merit is the **mean restoring torque over 0 to 105 degrees**, which is that
stored energy divided by the angle. It is taken at the worst of the four assumed PIP
axis positions, because the real axis is not known and the design has to work wherever
it turns out to be.

Among combinations that are valid, the best is the one with the highest worst-case mean
torque. Ties go to the wider travel window (more tolerance to print and axis error),
then to the lower profile.

Why only curvature and thickness are simulated
----------------------------------------------

The leaf's bent shape is set by geometry alone. Bending rigidity EI scales every moment
and force equally, so it drops out of the equilibrium. Two things follow:

* **Width only scales torque.** EI is proportional to width, and nothing else changes,
  so width is applied analytically on top of each simulated curvature and thickness.
  The cap is ``MAX_LEAF_WIDTH``, the widest leaf whose guide still fits the MP cuff.
* **Thickness scales strain.** Bending strain is half the thickness times the change in
  curvature, while torque grows with thickness cubed. Thickness also moves the anchor
  and guide slightly, so it is simulated rather than assumed.

For each curvature and thickness, the travel is re-tuned on the geometric criteria of
``a6_rom_check.py``: reaches 105 degrees, restoring at every angle, clear of the joint.
The strain limit is then applied as a separate filter, so its effect is visible on its
own. Because ``STRAIN_LIMIT`` is a placeholder until the filament has been tested, the
best combination is also reported at other strain limits.

Nothing here is calibrated. Torque is shown at the middle of the 8 to 18 MPa modulus
bracket, and the ranking does not depend on the modulus.

    python scripts/a6_parameter_sweep.py          # about 30 minutes on 4 cores
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import a6_rom_check as rom  # noqa: E402
import make_a6_designs as a6  # noqa: E402

RADII = (22.0, 24.0, 26.0, 28.0, 30.0, 32.0, 35.0, 40.0)
THICKNESSES = (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
WIDTHS = (3.0, 4.0, 5.0, 6.0)
#: Strain limits for the sensitivity table, in per cent. The headline uses
#: ``rom.STRAIN_LIMIT``.
STRAIN_LIMITS = (10.0, 15.0, 20.0, 25.0, 30.0)
#: Modulus for the torque figures, in MPa: the middle of the bracket. Ranking does not
#: depend on it.
MODULUS = float(np.mean(rom.MODULUS_RANGE))
#: The A3 twin strap's measured stiffness, in N mm/rad, for scale.
A3_STIFFNESS = 6.103

OUT = Path(__file__).resolve().parents[1] / "results" / "a6"


def _failure(rows_by_travel) -> str:
    """Which geometric criterion stopped a curvature and thickness from passing."""
    counts = {"reaches_target": 0, "always_restoring": 0, "clears_joint": 0}
    for rows in rows_by_travel.values():
        for row in rows:
            for key in counts:
                counts[key] += not row[key]
    labels = {"reaches_target": "goes taut before 105 deg",
              "always_restoring": "snaps onto its stop",
              "clears_joint": "cuts through the joint"}
    worst = max(counts, key=counts.get)
    return labels[worst]


def simulate(job):
    """Tune travel for one curvature and thickness, and record the per-EI results."""
    radius, thickness = job
    a6.set_section(a6.MAX_LEAF_WIDTH, thickness)
    rows_by_travel = {t: rom.evaluate(radius, t) for t in rom.TUNE_TRAVELS}
    passing = [t for t, rows in rows_by_travel.items()
               if all(r["passes_geometry"] for r in rows)]
    travel = rom.pick_travel(passing)
    result = {"radius_mm": radius, "thickness_mm": thickness,
              "passing_travels_mm": passing, "travel_mm": travel}
    if travel is None:
        result["valid_geometry"] = False
        result["reason"] = ("only one travel passes" if passing
                            else _failure(rows_by_travel))
        print(f"R{radius:g} t{thickness:g}: {result['reason']}", flush=True)
        return result

    rows = rows_by_travel[travel]
    arc = a6.solve_layout(radius, travel)
    result.update({
        "valid_geometry": True,
        "reason": "",
        "travel_window_mm": _window(passing, travel),
        "energy_per_ei_worst": min(r["_energy_per_ei"] for r in rows),
        "torque_105_per_ei_worst": min(r["_torque_per_ei"] for r in rows),
        "kappa_max_worst": max(r["_kappa_max"] for r in rows),
        "closest_to_axis_mm": min(r["closest_to_axis_mm"] for r in rows),
        "head_on_stop_from_deg": [r["head_on_stop_from_deg"] for r in rows],
        "height_above_pp_cuff_mm": round(
            max(arc.midpoint()[1], arc.a[1], arc.b[1]) + thickness / 2
            - a6.PP_OUTER[1] / 2, 2),
        "mp_cuff_length_mm": a6.mp_cuff_length(arc, travel),
    })
    print(f"R{radius:g} t{thickness:g}: travel {travel}, window "
          f"{result['travel_window_mm']}", flush=True)
    return result


def _window(passing, travel) -> float:
    """Width of the unbroken run of passing travels that contains ``travel``, in mm."""
    lo = hi = travel
    while any(abs(t - (lo - 0.5)) < 1e-9 for t in passing):
        lo -= 0.5
    while any(abs(t - (hi + 0.5)) < 1e-9 for t in passing):
        hi += 0.5
    return hi - lo


def combine(sim, width, strain_limit) -> dict:
    """One curvature, thickness and width, with every validity check applied."""
    t = sim["thickness_mm"]
    row = {"radius_mm": sim["radius_mm"], "thickness_mm": t, "width_mm": width,
           "travel_mm": sim["travel_mm"]}
    if not sim["valid_geometry"]:
        return {**row, "valid": False, "reason": sim["reason"]}
    ei = MODULUS * width * t ** 3 / 12
    strain = 100 * t / 2 * sim["kappa_max_worst"]
    theta = math.radians(rom.FLEXION_TARGET)
    row.update({
        "peak_strain_pct": round(strain, 1),
        "mean_torque_Nmm": round(sim["energy_per_ei_worst"] * ei / theta, 3),
        "torque_at_105_Nmm": round(sim["torque_105_per_ei_worst"] * ei, 3),
        "travel_window_mm": sim["travel_window_mm"],
        "closest_to_axis_mm": sim["closest_to_axis_mm"],
        "height_above_pp_cuff_mm": sim["height_above_pp_cuff_mm"],
        "mp_cuff_length_mm": sim["mp_cuff_length_mm"],
    })
    if width > a6.MAX_LEAF_WIDTH:
        return {**row, "valid": False, "reason": "guide wider than the MP cuff"}
    if strain > strain_limit:
        return {**row, "valid": False, "reason": f"strain over {strain_limit:g}%"}
    return {**row, "valid": True, "reason": ""}


def best(rows) -> dict | None:
    valid = [r for r in rows if r["valid"]]
    if not valid:
        return None
    return max(valid, key=lambda r: (r["mean_torque_Nmm"], r["travel_window_mm"],
                                     -r["height_above_pp_cuff_mm"]))


def matrix_markdown(sims, rows, winner) -> str:
    """Curvature x thickness at the widest leaf: mean torque, or why it is invalid."""
    width = max(WIDTHS)
    cell = {(r["radius_mm"], r["thickness_mm"]): r for r in rows if r["width_mm"] == width}
    head = "| R \\ t | " + " | ".join(f"{t:g} mm" for t in THICKNESSES) + " |"
    lines = [head, "|---" * (len(THICKNESSES) + 1) + "|"]
    for radius in RADII:
        out = []
        for t in THICKNESSES:
            r = cell[(radius, t)]
            if r["valid"]:
                text = f"{r['mean_torque_Nmm']:.2f}"
                if winner and (radius, t) == (winner["radius_mm"], winner["thickness_mm"]):
                    text = f"**{text} ★**"
            elif "strain" in r["reason"]:
                text = f"✗ strain {r['peak_strain_pct']:.0f}%"
            else:
                text = "✗ " + {"goes taut before 105 deg": "taut",
                               "snaps onto its stop": "snaps",
                               "cuts through the joint": "hits joint",
                               "only one travel passes": "fragile"}[r["reason"]]
            out.append(text)
        lines.append(f"| R{radius:g} | " + " | ".join(out) + " |")
    return "\n".join(lines)


def plot(path, sims, rows, winner) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14, 5.6),
                                 gridspec_kw={"width_ratios": [1.6, 1]})
    width = max(WIDTHS)
    grid = np.full((len(RADII), len(THICKNESSES)), np.nan)
    for r in rows:
        if r["width_mm"] == width and r["valid"]:
            grid[RADII.index(r["radius_mm"]), THICKNESSES.index(r["thickness_mm"])] = \
                r["mean_torque_Nmm"]
    ax.set_facecolor("0.88")
    im = ax.imshow(grid, cmap="viridis", aspect="auto")
    fig.colorbar(im, ax=ax, label=f"worst-case mean restoring torque, N mm (E {MODULUS:g} MPa)")
    for r in rows:
        if r["width_mm"] != width:
            continue
        i, j = RADII.index(r["radius_mm"]), THICKNESSES.index(r["thickness_mm"])
        if r["valid"]:
            text = f"{r['mean_torque_Nmm']:.2f}"
        elif "strain" in r["reason"]:
            text = f"strain\n{r['peak_strain_pct']:.0f}%"
        else:
            text = r["reason"].replace(" ", "\n", 1)
        ax.text(j, i, text, ha="center", va="center", fontsize=6.5,
                color="w" if r["valid"] else "0.35")
    if winner:
        i, j = RADII.index(winner["radius_mm"]), THICKNESSES.index(winner["thickness_mm"])
        ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec="red", lw=3))
    ax.set_xticks(range(len(THICKNESSES)), [f"{t:g}" for t in THICKNESSES])
    ax.set_yticks(range(len(RADII)), [f"R{r:g}" for r in RADII])
    ax.set_xlabel("leaf thickness (mm)")
    ax.set_ylabel("leaf radius of curvature")
    ax.set_title(f"Curvature x thickness at {width:g} mm width, strain limit "
                 f"{rom.STRAIN_LIMIT:g}% (red: best)", fontsize=10)

    if winner:
        rad = winner["radius_mm"]
        sub = np.full((len(WIDTHS), len(THICKNESSES)), np.nan)
        for r in rows:
            if r["radius_mm"] == rad and r["valid"]:
                sub[WIDTHS.index(r["width_mm"]), THICKNESSES.index(r["thickness_mm"])] = \
                    r["mean_torque_Nmm"]
        bx.set_facecolor("0.88")
        bx.imshow(sub, cmap="viridis", aspect="auto", origin="lower")
        for r in rows:
            if r["radius_mm"] != rad:
                continue
            i, j = WIDTHS.index(r["width_mm"]), THICKNESSES.index(r["thickness_mm"])
            bx.text(j, i, f"{r['mean_torque_Nmm']:.2f}" if r["valid"] else "✗",
                    ha="center", va="center", fontsize=7,
                    color="w" if r["valid"] else "0.35")
        i, j = WIDTHS.index(winner["width_mm"]), THICKNESSES.index(winner["thickness_mm"])
        bx.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec="red", lw=3))
        bx.set_xticks(range(len(THICKNESSES)), [f"{t:g}" for t in THICKNESSES])
        bx.set_yticks(range(len(WIDTHS)), [f"{w:g}" for w in WIDTHS])
        bx.set_xlabel("leaf thickness (mm)")
        bx.set_ylabel("leaf width (mm)")
        bx.set_title(f"Width x thickness at R{rad:g}", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    jobs = [(r, t) for r in RADII for t in THICKNESSES]
    with Pool(args.workers) as pool:
        sims = pool.map(simulate, jobs, chunksize=1)

    rows = [combine(s, w, rom.STRAIN_LIMIT) for s in sims for w in WIDTHS]
    winner = best(rows)
    sensitivity = {}
    for limit in STRAIN_LIMITS:
        pick = best([combine(s, w, limit) for s in sims for w in WIDTHS])
        sensitivity[f"{limit:g}"] = pick and {k: pick[k] for k in (
            "radius_mm", "thickness_mm", "width_mm", "travel_mm", "mean_torque_Nmm",
            "torque_at_105_Nmm", "peak_strain_pct")}

    with open(args.out / "parameter_sweep.csv", "w", newline="") as fh:
        fields = ["radius_mm", "thickness_mm", "width_mm", "valid", "reason", "travel_mm",
                  "mean_torque_Nmm", "torque_at_105_Nmm", "peak_strain_pct",
                  "travel_window_mm", "closest_to_axis_mm", "height_above_pp_cuff_mm",
                  "mp_cuff_length_mm"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})

    summary = {
        "figure_of_merit": "worst-case (over assumed PIP axis positions) mean restoring "
                           "torque over 0-105 deg flexion = stored energy / angle",
        "modulus_MPa": MODULUS,
        "strain_limit_pct": rom.STRAIN_LIMIT,
        "axis_positions_mm": rom.AXIS_POSITIONS,
        "max_leaf_width_mm": a6.MAX_LEAF_WIDTH,
        "best": winner,
        "best_by_strain_limit": sensitivity,
        "a3_stiffness_Nmm_per_rad": A3_STIFFNESS,
        "simulations": sims,
    }
    (args.out / "parameter_sweep.json").write_text(json.dumps(summary, indent=2))
    plot(args.out / "parameter_sweep.png", sims, rows, winner)
    print(matrix_markdown(sims, rows, winner))
    print("best:", winner)
    print("by strain limit:", json.dumps(sensitivity, indent=1))


if __name__ == "__main__":
    main()
