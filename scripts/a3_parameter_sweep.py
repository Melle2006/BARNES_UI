"""Sweep A3 strap curvature, thickness and width, and pick the best valid combination.

The same procedure as ``a6_parameter_sweep.py``, applied to the A3 twin strap, so the two
mechanisms are judged on the same terms.

What A3 is
----------

Two parallel arched straps, each clamped into a collar at both ends. Unlike A6, nothing
slides: as the PIP flexes, the distal collar carries the strap end around the joint
axis, and the arch has to take up both the rotation and the change in end-to-end
distance. The arch has only 0.58 mm of slack (arc minus chord), so beyond a few degrees
the A3 works by **stretching** its straps as well as bending them. An inextensible
model locks at 4 degrees and doubles the stiffness, so the straps are modelled as an
*extensible* planar elastica: the A6 equations plus axial strain N/EA. Energy is
bending plus stretching. The project's reduced-order model reached the same
conclusion: leaving out axial flexibility overstated the A3's stiffness by 13%.

Because EA/EI = 12/t^2, thickness changes the shape and is simulated. Width still only
scales EI and EA together, so it is applied analytically.

Where the sizes come from
-------------------------

Everything here comes from measurements of ``A3_PIP_twin_strap_1.0mm.step`` already
recorded in this project (docs/05-development-plan.md, scripts/a3_joint_stiffness.py):

* **Straps:** 2.0 x 1.0 mm section, 5.7 mm apart. Arc 28.38 mm over a 27.80 mm chord,
  so arc/chord is 1.02084. Top of the arch at z = 12.89.
* **Collars:** the faces are at y = 30.5 and 59.36. The FEA's clamp band starts about
  0.1 mm inside each, so the straps are taken as clamped at y = 30.6 and 59.26.
* **Joint axis:** y = 44.935, z = 5.44, the axis the 6.103 N mm/rad FEA used.

The arch ends stay where the collars put them, at the height that reproduces the measured
arch. Only the arch radius changes, just as A6 kept its cuffs fixed and varied the leaf.

The base geometry is checked against the FEA before any variant is trusted:
``--validate`` compares this model's neutral stiffness for the measured A3 with
6.103 N mm/rad.

The sweep
---------

Pass criteria, the axis positions and the figure of merit are the same as for A6:

* **Pass criteria:** reach 105 degrees, restoring at every angle, at least
  ``JOINT_RADIUS`` from the axis, peak strain at most ``STRAIN_LIMIT``.
* **Axis positions:** taken at the same fractions of the gap between collars as A6's four
  guesses. The FEA's own axis is close to the second.
* **Figure of merit:** worst-case mean restoring torque over 0 to 105 degrees.

Peak strain is the axial strain plus the bending strain at the surface.

    python scripts/a3_parameter_sweep.py --validate   # base A3 against its FEA
    python scripts/a3_parameter_sweep.py              # the sweep, about 30 minutes
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
from numba import njit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import a6_rom_check as rom  # noqa: E402

# --- Measured A3 geometry ------------------------------------------------------------

#: Clamp lines of the straps along Y, in mm.
CLAMP_Y = (30.6, 59.26)
#: Measured arc-length-to-chord ratio of the A3 strap.
ARC_OVER_CHORD = 28.3813 / 27.8017
#: Top of the arch's outer surface, in mm.
ARCH_TOP_Z = 12.89
#: Measured strap section, in mm, and the strap count and pitch.
A3_THICKNESS = 1.0
A3_WIDTH = 2.0
STRAP_COUNT = 2
STRAP_PITCH = 5.7
#: The FEA's joint axis, (y, z) in mm, and its measured stiffness in N mm/rad at the
#: provisional 12 MPa.
FEA_AXIS = (44.935, 5.44)
FEA_STIFFNESS = 6.10336
FEA_MODULUS = 12.0
#: The reduced-order model's figure for the same part, N mm/rad, which includes axial
#: stretching that the inextensible elastica leaves out.
ROM_STIFFNESS = 7.558

# --- Sweep ---------------------------------------------------------------------------

#: Arch radii, in mm. The chord is 28.66 mm, so 14.33 mm is a half circle.
RADII = (16.0, 20.0, 25.0, 30.0, 35.0, 41.4, 50.0, 60.0, 80.0, 120.0)
THICKNESSES = (0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6)
#: Width of each strap, in mm. The pitch stays at the A3's 5.7 mm, and at least 1.5 mm is
#: kept between the two straps, which caps the width at 4.2 mm.
WIDTHS = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
MAX_WIDTH = STRAP_PITCH - 1.5
#: Axis positions: the same fractions of the gap between collars as A6's guesses.
AXIS_FRACTIONS = tuple((y - 3.0) / 25.86 for y, _ in rom.AXIS_POSITIONS)
COLLAR_FACES_Y = (30.5, 59.36)
AXIS_POSITIONS = tuple(
    (round(COLLAR_FACES_Y[0] + f * (COLLAR_FACES_Y[1] - COLLAR_FACES_Y[0]), 2), FEA_AXIS[1])
    for f in AXIS_FRACTIONS)
STRAIN_LIMITS = (10.0, 15.0, 20.0, 25.0, 30.0)
MODULUS = float(np.mean(rom.MODULUS_RANGE))

OUT = Path(__file__).resolve().parents[1] / "results" / "a3_parameter_sweep"


def _measured_radius() -> float:
    """Arc radius giving the measured arc/chord ratio over the clamp span."""
    lo, hi = 1e-6, math.pi - 1e-6  # half the subtended angle
    for _ in range(200):
        mid = (lo + hi) / 2
        if mid / math.sin(mid) < ARC_OVER_CHORD:
            lo = mid
        else:
            hi = mid
    return (CLAMP_Y[1] - CLAMP_Y[0]) / (2 * math.sin(lo))


MEASURED_RADIUS = _measured_radius()


def _sagitta(radius: float) -> float:
    half = (CLAMP_Y[1] - CLAMP_Y[0]) / 2
    return radius - math.sqrt(radius ** 2 - half ** 2)


#: Height of the strap ends' centreline, in mm, fixed by the measured arch.
END_Z = ARCH_TOP_Z - A3_THICKNESS / 2 - _sagitta(MEASURED_RADIUS)


@njit(cache=True)
def _rhs_ext(x, ny, nz, kappa0, ea):
    th = x[2]
    ty, tz = math.cos(th), math.sin(th)
    stretch = 1.0 + (ny * ty + nz * tz) / ea
    return np.array([stretch * ty, stretch * tz, kappa0 + x[3],
                     -stretch * (ty * nz - tz * ny)])


@njit(cache=True)
def _integrate_ext(y, z, th, m, ny, nz, length, kappa0, ea, n):
    """RK4 along the unstretched length. Columns are y, z, theta, moment (EI = 1)."""
    h = length / n
    out = np.empty((n + 1, 4))
    out[0, 0], out[0, 1], out[0, 2], out[0, 3] = y, z, th, m
    for i in range(n):
        x = out[i]
        k1 = _rhs_ext(x, ny, nz, kappa0, ea)
        k2 = _rhs_ext(x + h / 2 * k1, ny, nz, kappa0, ea)
        k3 = _rhs_ext(x + h / 2 * k2, ny, nz, kappa0, ea)
        k4 = _rhs_ext(x + h * k3, ny, nz, kappa0, ea)
        out[i + 1] = x + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return out


class Strap(rom.Leaf):
    """An A3 strap: a dorsal arc of ``radius`` between the two fixed clamp points.

    Extensible: EA is ``12 / thickness**2`` in units where EI = 1.
    """

    def __init__(self, radius: float, thickness: float):  # noqa: D107
        self.thickness = thickness
        self.ea = 12.0 / thickness ** 2
        self.radius = radius
        self.a = np.array((CLAMP_Y[0], END_Z))
        self.b = np.array((CLAMP_Y[1], END_Z))
        half = (CLAMP_Y[1] - CLAMP_Y[0]) / 2
        phi = math.asin(half / radius)
        self.theta_a, self.theta_b = phi, -phi
        self.arc_length = 2 * radius * phi
        self.kappa0 = -1.0 / radius
        self.travel = 0.0

    def shoot(self, m0, ny, nz, length):
        return _integrate_ext(self.a[0], self.a[1], self.theta_a, m0, ny, nz, length,
                              self.kappa0, self.ea, rom.N_STEPS)

    def energy(self, params):
        """Bending plus stretching energy, peak surface strain, and the shape."""
        shape = self.shoot(*params).T
        s = np.linspace(0.0, params[3], rom.N_STEPS + 1)
        m = shape[3]
        axial = (params[1] * np.cos(shape[2]) + params[2] * np.sin(shape[2])) / self.ea
        u = 0.5 * np.trapezoid(m ** 2, s) + 0.5 * self.ea * np.trapezoid(axial ** 2, s)
        strain = float(np.max(np.abs(axial) + self.thickness / 2 * np.abs(m)))
        return float(u), strain, shape


def follow(strap: Strap, axis) -> dict:
    """Clamped-clamped continuation from 0 to the flexion target, EI = 1."""
    guess = np.array([0.0, 0.0, 0.0, strap.arc_length])
    rows = {0.0: guess}
    previous = 0.0
    for deg in np.arange(rom.STEP_DEG, rom.FLEXION_TARGET + rom.STEP_DEG / 2, rom.STEP_DEG):
        params, err = rom._step(strap, axis, previous, deg, guess, strap.arc_length)
        if err > rom.TOL:
            break
        guess, previous = params, float(deg)
        rows[float(deg)] = params
    angles = np.array(list(rows))
    energy, strain, approach = [], [], []
    for deg in angles:
        u, eps, shape = strap.energy(rows[deg])
        energy.append(u)
        strain.append(eps)
        approach.append(float(np.min(np.hypot(shape[0] - axis[0], shape[1] - axis[1]))))
    energy = np.array(energy)
    torque = np.gradient(energy, np.radians(angles)) if len(angles) > 2 else energy * 0
    return {"angles": angles, "energy": energy, "torque": torque,
            "strain": np.array(strain), "approach": np.array(approach), "rows": rows}


def simulate(job) -> dict:
    """Per-EI results for one arch radius and thickness at every axis position."""
    radius, thickness = job
    strap = Strap(radius, thickness)
    per_axis = []
    for axis in AXIS_POSITIONS:
        res = follow(strap, axis)
        angles, torque = res["angles"], res["torque"]
        per_axis.append({
            "axis_y_mm": axis[0],
            "max_flexion_deg": float(angles.max()),
            "reaches_target": bool(angles.max() >= rom.FLEXION_TARGET),
            "always_restoring": bool(len(torque) > 1 and torque[1:].min() > 0),
            "clears_joint": bool(res["approach"].min() >= rom.JOINT_RADIUS),
            "closest_to_axis_mm": round(float(res["approach"].min()), 2),
            "energy_per_ei": float(res["energy"][-1]),
            "torque_105_per_ei": float(torque[-1]),
            "stiffness_0_per_ei": float(np.interp(math.radians(3), np.radians(angles), torque)
                                        / math.radians(3)),
            "strain_max": float(res["strain"].max()),
        })
    geometry_ok = all(a["reaches_target"] and a["always_restoring"] and a["clears_joint"]
                      for a in per_axis)
    reason = ""
    if not geometry_ok:
        if not all(a["reaches_target"] for a in per_axis):
            reason = "no equilibrium before 105 deg"
        elif not all(a["always_restoring"] for a in per_axis):
            reason = "snaps"
        else:
            reason = "cuts through the joint"
    print(f"R{radius:g} t{thickness:g}: {'ok' if geometry_ok else reason}", flush=True)
    return {
        "radius_mm": radius,
        "thickness_mm": thickness,
        "arc_length_mm": round(strap.arc_length, 3),
        "arch_height_above_ends_mm": round(_sagitta(radius), 2),
        "top_of_arch_z_mm": round(END_Z + _sagitta(radius), 2),
        "valid_geometry": geometry_ok,
        "reason": reason,
        "per_axis": per_axis,
        "energy_per_ei_worst": min(a["energy_per_ei"] for a in per_axis),
        "torque_105_per_ei_worst": min(a["torque_105_per_ei"] for a in per_axis),
        "strain_max_worst": max(a["strain_max"] for a in per_axis),
        "closest_to_axis_mm": min(a["closest_to_axis_mm"] for a in per_axis),
    }


def combine(sim, width, strain_limit) -> dict:
    thickness = sim["thickness_mm"]
    row = {"radius_mm": sim["radius_mm"], "thickness_mm": thickness, "width_mm": width,
           "strap_count": STRAP_COUNT}
    strain = 100 * sim["strain_max_worst"]
    ei = STRAP_COUNT * MODULUS * width * thickness ** 3 / 12
    row.update({
        "peak_strain_pct": round(strain, 1),
        "mean_torque_Nmm": round(sim["energy_per_ei_worst"] * ei
                                 / math.radians(rom.FLEXION_TARGET), 3),
        "torque_at_105_Nmm": round(sim["torque_105_per_ei_worst"] * ei, 3),
        "closest_to_axis_mm": sim["closest_to_axis_mm"],
        "top_of_arch_z_mm": sim["top_of_arch_z_mm"],
    })
    if not sim["valid_geometry"]:
        return {**row, "valid": False, "reason": sim["reason"]}
    if width > MAX_WIDTH:
        return {**row, "valid": False, "reason": "straps closer than 1.5 mm"}
    if strain > strain_limit:
        return {**row, "valid": False, "reason": f"strain over {strain_limit:g}%"}
    return {**row, "valid": True, "reason": ""}


def best(rows):
    valid = [r for r in rows if r["valid"]]
    if not valid:
        return None
    return max(valid, key=lambda r: (r["mean_torque_Nmm"], -r["peak_strain_pct"],
                                     -r["top_of_arch_z_mm"]))


SHORT = {"no equilibrium before 105 deg": "over-stretched", "snaps": "snaps",
         "cuts through the joint": "hits joint"}


def label(row) -> str:
    if "strain" in row["reason"]:
        return f"strain {row['peak_strain_pct']:.0f}%"
    return SHORT.get(row["reason"], row["reason"])


def matrix_markdown(rows, winner, width) -> str:
    cell = {(r["radius_mm"], r["thickness_mm"]): r for r in rows if r["width_mm"] == width}
    lines = ["| R \\ t | " + " | ".join(f"{t:g} mm" for t in THICKNESSES) + " |",
             "|---" * (len(THICKNESSES) + 1) + "|"]
    for radius in RADII:
        out = []
        for t in THICKNESSES:
            r = cell[(radius, t)]
            if r["valid"]:
                text = f"{r['mean_torque_Nmm']:.2f}"
                if winner and (radius, t) == (winner["radius_mm"], winner["thickness_mm"]):
                    text = f"**{text} ★**"
            else:
                text = "✗ " + label(r)
            out.append(text)
        name = f"R{radius:g}" + (" (A3 as built)" if radius == 41.4 else "")
        lines.append(f"| {name} | " + " | ".join(out) + " |")
    return "\n".join(lines)


def worst_reach(sim) -> float:
    """Flexion reached at the worst axis position, in degrees."""
    return min(a["max_flexion_deg"] for a in sim["per_axis"])


def flags(sim) -> list[str]:
    """Every way a variant misbehaves on the way, not just the first."""
    out = []
    if not all(a["always_restoring"] for a in sim["per_axis"]):
        out.append("snaps")
    if not all(a["clears_joint"] for a in sim["per_axis"]):
        out.append("hits joint")
    return out


def reach_markdown(sims) -> str:
    """Curvature x thickness: flexion reached at the worst axis, and how it ends."""
    cell = {(s["radius_mm"], s["thickness_mm"]): s for s in sims}
    lines = ["| R \\ t | " + " | ".join(f"{t:g} mm" for t in THICKNESSES) + " |",
             "|---" * (len(THICKNESSES) + 1) + "|"]
    for radius in RADII:
        out = []
        for t in THICKNESSES:
            sim = cell[(radius, t)]
            text = f"{worst_reach(sim):.0f}°"
            if sim["valid_geometry"]:
                text += " ✓"
            elif flags(sim):
                text += f" ({', '.join(flags(sim))})"
            out.append(text)
        name = f"R{radius:g}" + (" (A3 as built)" if radius == 41.4 else "")
        lines.append(f"| {name} | " + " | ".join(out) + " |")
    return "\n".join(lines)


def plot_reach(path, sims) -> None:
    """When no variant is valid, the useful picture is how far each one gets."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, bx = plt.subplots(figsize=(9, 6))
    reach = np.full((len(RADII), len(THICKNESSES)), np.nan)
    for sim in sims:
        reach[RADII.index(sim["radius_mm"]), THICKNESSES.index(sim["thickness_mm"])] = \
            worst_reach(sim)
    im2 = bx.imshow(reach, cmap="magma", aspect="auto", vmin=0, vmax=rom.FLEXION_TARGET)
    fig.colorbar(im2, ax=bx, label="flexion reached at the worst axis (deg)")
    for sim in sims:
        i, j = RADII.index(sim["radius_mm"]), THICKNESSES.index(sim["thickness_mm"])
        text = "\n".join([f"{worst_reach(sim):.0f}", *flags(sim)])
        bx.text(j, i, text, ha="center", va="center", fontsize=7,
                color="w" if worst_reach(sim) < 60 else "k")
    bx.set_xticks(range(len(THICKNESSES)), [f"{t:g}" for t in THICKNESSES])
    bx.set_yticks(range(len(RADII)), [f"R{r:g}" for r in RADII])
    bx.set_xlabel("strap thickness (mm)")
    bx.set_title(f"How far each A3 variant gets (target {rom.FLEXION_TARGET:g} deg)",
                 fontsize=10)
    bx.set_ylabel("strap arch radius")
    bx.text(1.0, -0.12, f"No variant is valid: none reaches {rom.FLEXION_TARGET:g} deg "
            "without over-stretching, snapping or hitting the joint at every axis.",
            transform=bx.transAxes, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def plot(path, rows, winner, sims) -> None:
    if not winner:
        plot_reach(path, sims)
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    width = winner["width_mm"] if winner else max(w for w in WIDTHS if w <= MAX_WIDTH)
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14, 6),
                                 gridspec_kw={"width_ratios": [1.6, 1]})
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
        text = f"{r['mean_torque_Nmm']:.2f}" if r["valid"] else label(r).replace(" ", "\n")
        ax.text(j, i, text, ha="center", va="center", fontsize=7,
                color="w" if r["valid"] else "0.35")
    if winner:
        i, j = RADII.index(winner["radius_mm"]), THICKNESSES.index(winner["thickness_mm"])
        ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec="red", lw=3))
    i = RADII.index(41.4)
    ax.add_patch(Rectangle((THICKNESSES.index(1.0) - 0.5, i - 0.5), 1, 1, fill=False,
                           ec="white", lw=2, ls="--"))
    ax.set_xticks(range(len(THICKNESSES)), [f"{t:g}" for t in THICKNESSES])
    ax.set_yticks(range(len(RADII)), [f"R{r:g}" for r in RADII])
    ax.set_xlabel("strap thickness (mm)")
    ax.set_ylabel("strap arch radius")
    ax.set_title(f"A3: curvature x thickness at {width:g} mm per strap, strain limit "
                 f"{rom.STRAIN_LIMIT:g}% (red: best, dashed: A3 as built)", fontsize=9)
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
        bx.set_xlabel("strap thickness (mm)")
        bx.set_ylabel("width of each strap (mm)")
        bx.set_title(f"Width x thickness at R{rad:g}", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def validate() -> dict:
    """The measured A3 against its FEA, at the FEA's axis and modulus."""
    strap = Strap(MEASURED_RADIUS, A3_THICKNESS)
    res = follow(strap, FEA_AXIS)
    ei = STRAP_COUNT * FEA_MODULUS * A3_WIDTH * A3_THICKNESS ** 3 / 12
    k0 = float(np.interp(math.radians(2), np.radians(res["angles"]), res["torque"])
               / math.radians(2)) * ei
    strain90 = 100 * float(res["strain"][res["angles"] <= 90].max())
    out = {
        "measured_radius_mm": round(MEASURED_RADIUS, 2),
        "end_z_mm": round(END_Z, 3),
        "elastica_stiffness_at_2deg_Nmm_per_rad": round(k0, 3),
        "fea_stiffness_Nmm_per_rad": FEA_STIFFNESS,
        "reduced_order_stiffness_Nmm_per_rad": ROM_STIFFNESS,
        "elastica_over_fea": round(k0 / FEA_STIFFNESS, 3),
        "peak_strain_to_90deg_pct": round(strain90, 1),
        "reached_deg": float(res["angles"].max()),
    }
    print(json.dumps(out, indent=2))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--from-json", action="store_true",
                        help="rebuild tables and figure from parameter_sweep.json")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.validate:
        (args.out / "validation.json").write_text(json.dumps(validate(), indent=2))
        return

    if args.from_json:
        sims = json.loads((args.out / "parameter_sweep.json").read_text())["simulations"]
    else:
        with Pool(4) as pool:
            sims = pool.map(simulate, [(r, t) for r in RADII for t in THICKNESSES],
                            chunksize=1)

    grid = [(s, w) for s in sims for w in WIDTHS]
    rows = [combine(s, w, rom.STRAIN_LIMIT) for s, w in grid]
    winner = best(rows)
    sensitivity = {}
    for limit in STRAIN_LIMITS:
        pick = best([combine(s, w, limit) for s, w in grid])
        sensitivity[f"{limit:g}"] = pick and {k: pick[k] for k in (
            "radius_mm", "thickness_mm", "width_mm", "mean_torque_Nmm",
            "torque_at_105_Nmm", "peak_strain_pct")}
    as_built = combine(next(s for s in sims if s["radius_mm"] == 41.4
                            and s["thickness_mm"] == A3_THICKNESS),
                       A3_WIDTH, rom.STRAIN_LIMIT)
    # The variant that follows the finger furthest cleanly: reaches the most flexion at
    # the worst axis without snapping or touching the joint on the way.
    clean = [s for s in sims if not flags(s)]
    far = max(clean, key=lambda s: (worst_reach(s), -s["strain_max_worst"]))
    furthest = {"radius_mm": far["radius_mm"], "thickness_mm": far["thickness_mm"],
                "worst_case_reach_deg": worst_reach(far),
                "peak_strain_pct": round(100 * far["strain_max_worst"], 1)}

    fields = ["radius_mm", "thickness_mm", "width_mm", "strap_count", "valid", "reason",
              "mean_torque_Nmm", "torque_at_105_Nmm", "peak_strain_pct",
              "closest_to_axis_mm", "top_of_arch_z_mm"]
    with open(args.out / "parameter_sweep.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
    summary = {
        "figure_of_merit": "worst-case (over assumed PIP axis positions) mean restoring "
                           "torque over 0-105 deg flexion = stored energy / angle",
        "modulus_MPa": MODULUS,
        "strain_limit_pct": rom.STRAIN_LIMIT,
        "axis_positions_mm": AXIS_POSITIONS,
        "max_strap_width_mm": MAX_WIDTH,
        "as_built": as_built,
        "best": winner,
        "best_by_strain_limit": sensitivity,
        "furthest_reaching_clean": furthest,
        "simulations": sims,
    }
    (args.out / "parameter_sweep.json").write_text(json.dumps(summary, indent=2))
    plot(args.out / "parameter_sweep.png", rows, winner, sims)
    print(matrix_markdown(rows, winner, winner["width_mm"] if winner else 4.0))
    print(reach_markdown(sims))
    print("furthest-reaching clean variant:", furthest)
    print("as built:", as_built)
    print("best:", winner)
    print("by strain limit:", json.dumps(sensitivity, indent=1))


if __name__ == "__main__":
    main()
