"""Check whether each A6 leaf can follow a human PIP through its range of motion.

A design passes when, at every assumed axis position, it

1. reaches ``FLEXION_TARGET`` with an equilibrium at every degree on the way;
2. pushes back toward extension at every angle, so it never snaps or pulls the finger
   into flexion;
3. keeps at least ``JOINT_RADIUS`` from the axis, so it does not cut through the joint;
4. stays under ``STRAIN_LIMIT`` peak bending strain.

``--tune`` searches for the travel each radius needs to pass and prints the table that
``make_a6_designs.TRAVEL_BY_RADIUS`` holds.

What is computed
----------------

The leaf is a planar elastica (an inextensible beam that bends through large angles)
running from the PP anchor to the guide mouth on the MP. The joint is flexed about an
axis by turning the guide's mouth and direction about that axis. The leaf satisfies four
conditions at the mouth:

* it passes through the mouth (two conditions);
* it leaves along the guide's direction;
* the guide pushes only sideways on it. A frictionless slot cannot carry axial load, so
  the leaf's internal force along the guide is zero.

The four unknowns are the moment at the anchor, the two components of the leaf force,
and the free length between anchor and mouth. That free length is what makes the end
*sliding*. Its change from neutral is how far the tip has moved in the guide, which the
T-head stop limits to the design's travel one way and ``TRAVEL_DISTAL`` the other.
Once the head is on a stop, the free length is pinned and the stop takes the axial load.

Each angle starts from the solution at the previous one (continuation), beginning at
neutral, where the pre-curved leaf is unstressed by construction. Restoring torque is
the derivative of stored bending energy with respect to joint angle. That holds for any
conservative system, so it does not depend on getting a sign convention right.

What is *not* known
-------------------

**Where the PIP axis sits relative to the cuffs.** The A8 export holds only the collars
and the spine, not the phalanges. The axis is therefore a swept input here, not a
measured one, and the results are reported for each position tried.

**The modulus.** Torque scales linearly with E. It is reported per unit bending rigidity
EI, and also at the 8 to 18 MPa bracket the rest of this project uses. Nothing here is
calibrated.

**Contact.** The leaf is free to pass through the finger. The closest approach to the
axis is reported so a leaf that would hit the joint is visible rather than silently
accepted.

    python scripts/a6_rom_check.py            # check the designs in make_a6_designs
    python scripts/a6_rom_check.py --tune     # find the travel for each radius
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
from numba import njit
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_a6_designs as a6  # noqa: E402

#: Human PIP active flexion, in degrees: about 100 to 110 (AAOS norms). Hyperextension
#: is left out for now. Positive is flexion.
FLEXION_TARGET = 105.0
PIP_RANGE = (0.0, FLEXION_TARGET)
#: Candidate PIP axis positions, (y, z) in mm, in the A8 frame. The phalanx centreline is
#: z = 0. These are guesses spanning the gap between the cuffs, not measurements.
AXIS_POSITIONS = ((10.0, 0.0), (15.0, 0.0), (20.0, 0.0), (24.0, 0.0))
#: Distance from the axis inside which the leaf is taken to be touching the finger, in mm.
#: The PP cuff's bore is 7.0 mm tall, so this is the bone's dorsal surface at the cuff.
#: The real knuckle is larger, so this is a lenient test.
JOINT_RADIUS = 3.5
#: Peak bending strain allowed, in per cent. A placeholder until the filament's tensile
#: test exists (docs/06-required-inputs.md), not a property of TPU.
STRAIN_LIMIT = 20.0
#: Radii and travels searched by ``--tune``, in mm.
TUNE_RADII = (24.0, 26.0, 28.0, 30.0, 32.0)
TUNE_TRAVELS = tuple(float(t) for t in np.arange(9.5, 14.51, 0.5))
#: Modulus bracket for the torque columns, in MPa. Not calibrated.
MODULUS_RANGE = (8.0, 18.0)
#: Angle step for the continuation, in degrees.
STEP_DEG = 1.0
#: Integration steps along the leaf.
N_STEPS = 400
#: Largest residual accepted as a solution: mm for position, rad for angle.
TOL = 1e-5


@njit(cache=True)
def _rhs(x, s, ny, nz, kappa0, arc_length):
    kap = kappa0 if s <= arc_length else 0.0
    ty, tz = math.cos(x[2]), math.sin(x[2])
    return np.array([ty, tz, kap + x[3], -(ty * nz - tz * ny)])


@njit(cache=True)
def _integrate(y, z, th, m, ny, nz, length, kappa0, arc_length, n):
    """Fixed-step RK4 along the leaf. Rows are nodes; columns are y, z, theta, moment."""
    h = length / n
    out = np.empty((n + 1, 4))
    out[0, 0], out[0, 1], out[0, 2], out[0, 3] = y, z, th, m
    for i in range(n):
        s, x = i * h, out[i]
        k1 = _rhs(x, s, ny, nz, kappa0, arc_length)
        k2 = _rhs(x + h / 2 * k1, s + h / 2, ny, nz, kappa0, arc_length)
        k3 = _rhs(x + h / 2 * k2, s + h / 2, ny, nz, kappa0, arc_length)
        k4 = _rhs(x + h * k3, s + h, ny, nz, kappa0, arc_length)
        out[i + 1] = x + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return out


def _rot(vec, angle):
    """Turn a Y-Z vector by ``-angle``. Flexion takes +Y toward -Z."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([vec[0] * c + vec[1] * s, -vec[0] * s + vec[1] * c])


class Leaf:
    """One A6 variant reduced to what the elastica needs."""

    def __init__(self, radius, travel):
        arc = a6.solve_layout(radius, travel)
        self.radius = radius
        self.travel = travel
        self.a = np.array(arc.a)
        self.b = np.array(arc.b)
        self.theta_a = math.atan2(*reversed(arc.tangent(arc.a)))
        self.theta_b = math.atan2(*reversed(arc.tangent(arc.b)))
        self.arc_length = arc.length()
        # Bows dorsally, so it turns clockwise in Y-Z. Beyond the arc is the straight tail,
        # which leaves the guide when the tip is pulled toward the PP.
        self.kappa0 = 0.0 if radius is None else -1.0 / radius

    def shoot(self, m0, ny, nz, length):
        """Integrate from the anchor. Rows are nodes; columns are y, z, theta, moment."""
        return _integrate(self.a[0], self.a[1], self.theta_a, m0, ny, nz, length,
                          self.kappa0, self.arc_length, N_STEPS)

    def mouth(self, angle, axis):
        """Guide mouth position and direction at joint angle ``angle`` (radians)."""
        axis = np.array(axis)
        theta = self.theta_b - angle
        return axis + _rot(self.b - axis, angle), theta, np.array(
            [math.cos(theta), math.sin(theta)])

    def solve(self, angle, axis, guess, fixed_length=None):
        """Equilibrium shape at joint angle ``angle`` (radians), EI = 1.

        Sliding (``fixed_length`` None): the free length is an unknown and the leaf
        carries no force along the guide. Against a stop: the free length is pinned and
        the stop takes whatever axial force equilibrium needs.
        """
        mouth, theta_mouth, direction = self.mouth(angle, axis)

        def residual(p):
            m0, ny, nz = p[:3]
            length = p[3] if fixed_length is None else fixed_length
            end = self.shoot(m0, ny, nz, length)[-1]
            # Wrap the angle error into (-pi, pi]: the leaf may legitimately turn more
            # than half a revolution in total but not relative to where it should be.
            dth = (end[2] - theta_mouth + math.pi) % (2 * math.pi) - math.pi
            res = [end[0] - mouth[0], end[1] - mouth[1], dth]
            if fixed_length is None:
                res.append(ny * direction[0] + nz * direction[1])
            return res

        start = guess if fixed_length is None else guess[:3]
        fit = least_squares(residual, start, xtol=1e-12, ftol=1e-12, gtol=1e-12)
        params = fit.x if fixed_length is None else np.append(fit.x, fixed_length)
        return params, float(np.max(np.abs(fit.fun)))

    def axial_force(self, params, angle, axis):
        """Leaf force along the guide at the mouth, EI = 1. Positive pulls the tip out."""
        return float(params[1:3] @ self.mouth(angle, axis)[2])

    def energy(self, params):
        """Stored bending energy, and the largest curvature change, for EI = 1."""
        shape = self.shoot(*params).T
        s = np.linspace(0.0, params[3], N_STEPS + 1)
        m = shape[3]
        return float(0.5 * np.trapezoid(m ** 2, s)), float(np.max(np.abs(m))), shape


def _step(leaf: Leaf, axis, previous, deg, guess, fixed_length):
    """Solve at ``deg`` from the solution at ``previous``.

    A failed step is retried in smaller increments before giving up, so a failure marks
    where the leaf has no nearby equilibrium, not where the solver took too long a stride.
    """
    params, err = leaf.solve(math.radians(deg), axis, guess, fixed_length)
    sub = 1
    while err > TOL and sub < 64:
        sub *= 4
        trial = guess
        for frac in np.linspace(0.0, 1.0, sub + 1)[1:]:
            trial, err = leaf.solve(math.radians(previous + frac * (deg - previous)),
                                    axis, trial, fixed_length)
            if err > TOL:
                break
        params = trial
    return params, err


def sweep(leaf: Leaf, axis):
    """Follow the leaf from neutral to each end of the PIP range.

    Returns ``{angle: (params, on_stop)}``. The tip slides freely until its slide would
    pass ``TRAVEL_PROXIMAL`` or ``-TRAVEL_DISTAL``, or until no sliding equilibrium
    exists, which happens when the leaf would keep pulling out. From then on the T-head
    sits on the stop, the free length is pinned, and the stop carries the axial load.
    It lets go again if that load reverses.
    """
    rows = {}
    limits = (leaf.arc_length - a6.TRAVEL_DISTAL, leaf.arc_length + leaf.travel)
    for end in PIP_RANGE:
        if end == 0:
            continue
        guess = np.array([0.0, 0.0, 0.0, leaf.arc_length])
        stop = None
        rows[0.0] = (guess, False)
        angles = np.arange(0.0, end + math.copysign(STEP_DEG, end) / 2,
                           math.copysign(STEP_DEG, end))[1:]
        previous = 0.0
        for deg in angles:
            if stop is not None:
                params, err = _step(leaf, axis, previous, deg, guess, stop)
                pull = leaf.axial_force(params, math.radians(deg), axis)
                if err <= TOL and (pull < 0) == (stop == limits[1]):
                    stop = None  # the load has reversed: the head leaves the stop
            if stop is None:
                params, err = _step(leaf, axis, previous, deg, guess, None)
                if err > TOL or not limits[0] <= params[3] <= limits[1]:
                    if err <= TOL:
                        stop = limits[1] if params[3] > limits[1] else limits[0]
                    else:
                        # No sliding equilibrium: the tip runs on to whichever stop it
                        # was heading for.
                        stop = limits[1] if guess[3] >= leaf.arc_length else limits[0]
                    params, err = _step(leaf, axis, previous, deg, guess, stop)
            if err > TOL:
                break
            guess, previous = params, deg
            rows[round(float(deg), 6)] = (params, stop is not None)
    return dict(sorted(rows.items()))


def analyse(leaf: Leaf, axis):
    """Per-angle results along the sweep, all for EI = 1.

    Torque is the derivative of stored energy with joint angle. That stays true with the
    head on its stop, because a stop that does not move does no work.
    """
    rows = sweep(leaf, axis)
    angles = np.array(list(rows))
    out = {k: [] for k in ("energy", "kappa", "slide", "approach", "on_stop", "pull")}
    for deg in angles:
        params, on_stop = rows[deg]
        u, k, shape = leaf.energy(params)
        out["energy"].append(u)
        out["kappa"].append(k)
        out["slide"].append(params[3] - leaf.arc_length)
        out["approach"].append(
            float(np.min(np.hypot(shape[0] - axis[0], shape[1] - axis[1]))))
        out["on_stop"].append(on_stop)
        out["pull"].append(leaf.axial_force(params, math.radians(deg), axis))
    out = {k: np.array(v) for k, v in out.items()}
    out["angles"] = angles
    out["torque"] = (np.gradient(out["energy"], np.radians(angles)) if len(angles) > 2
                     else out["energy"] * 0)
    return out


def evaluate(radius, travel) -> list[dict]:
    """One row per axis position, with the pass criteria applied."""
    leaf = Leaf(radius, travel)
    ei_per_e = a6.LEAF_WIDTH * a6.LEAF_THICKNESS ** 3 / 12  # mm^4
    rows = []
    for axis in AXIS_POSITIONS:
        res = analyse(leaf, axis)
        angles, torque = res["angles"], res["torque"]
        strain = 100 * a6.LEAF_THICKNESS / 2 * float(res["kappa"].max())
        stop = angles[res["on_stop"]]
        checks = {
            "reaches_target": bool(angles.max() >= FLEXION_TARGET),
            "always_restoring": bool(torque[1:].min() > 0),
            "clears_joint": bool(res["approach"].min() >= JOINT_RADIUS),
            "strain_ok": strain <= STRAIN_LIMIT,
        }
        tau = float(torque[-1])
        rows.append({
            "radius_mm": "flat" if radius is None else f"{radius:g}",
            "travel_mm": travel,
            "axis_y_mm": axis[0],
            "axis_z_mm": axis[1],
            "passes": all(checks.values()),
            **checks,
            "max_flexion_deg": float(angles.max()),
            "head_on_stop_from_deg": float(stop[0]) if stop.size else "never",
            "max_slide_mm": round(float(res["slide"].max()), 2),
            "closest_to_axis_mm": round(float(res["approach"].min()), 2),
            "peak_strain_pct": round(strain, 1),
            "min_torque_per_EI_1_per_mm": round(float(torque[1:].min()), 4),
            "torque_at_max_Nmm": " .. ".join(
                f"{tau * e * ei_per_e:.2f}" for e in MODULUS_RANGE),
            "stop_tension_at_max_N": " .. ".join(
                f"{max(float(res['pull'][-1]), 0.0) * e * ei_per_e:.2f}"
                for e in MODULUS_RANGE),
            "stiffness_near_0_Nmm_per_rad": " .. ".join(
                f"{float(np.interp(0.3, np.radians(angles), torque)) / 0.3 * e * ei_per_e:.2f}"
                for e in MODULUS_RANGE),
            "_angles": angles,
            "_torque": torque,
        })
    return rows


def tune(radius) -> float | None:
    """The middle of the longest run of travels that pass at every axis position.

    None when no two neighbouring travels pass.

    The middle, because the window is bounded on both sides: shorter travel lets the
    leaf go taut or hit the joint, and longer travel lets the tip snap onto its stop.
    Taking the centre leaves the most margin for an axis or a print that is off.
    """
    passing = [t for t in TUNE_TRAVELS if all(r["passes"] for r in evaluate(radius, t))]
    print(f"R{radius:g}: passing travels {passing}", flush=True)
    if not passing:
        return None
    # Longest unbroken run of passing travels, then its middle.
    runs, run = [], [passing[0]]
    for t in passing[1:]:
        if abs(t - run[-1] - 0.5) < 1e-9:
            run.append(t)
        else:
            runs.append(run)
            run = [t]
    runs.append(run)
    best = max(runs, key=len)
    if len(best) < 2:
        return None  # a lone passing travel fails 0.5 mm either side: too fragile to build
    return float(best[(len(best) - 1) // 2])


def plot(path: Path, axis, angles=(0, 30, 60, 90, 105)) -> None:
    """Leaf shapes through the range and torque curves, one row per design."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(a6.RADII), 2, figsize=(10, 2.8 * len(a6.RADII)),
                             gridspec_kw={"width_ratios": [1.3, 1]}, squeeze=False)
    colours = plt.cm.viridis(np.linspace(0, 0.9, len(angles)))
    for (ax, tax), radius in zip(axes, a6.RADII):
        travel = a6.TRAVEL_BY_RADIUS[radius]
        leaf = Leaf(radius, travel)
        rows = sweep(leaf, axis)
        for deg, colour in zip(angles, colours):
            if float(deg) not in rows:
                continue
            params, on_stop = rows[float(deg)]
            y, z = leaf.shoot(*params).T[:2]
            slide = params[3] - leaf.arc_length
            ax.plot(y, z, color=colour, lw=1.6, label=f"{deg} deg, slide {slide:+.1f} mm"
                    + (" (on stop)" if on_stop else ""))
        ax.add_patch(plt.Circle(axis, JOINT_RADIUS, color="0.85", zorder=0))
        ax.plot(*axis, "k+")
        ax.set_aspect("equal")
        ax.set_xlim(-2, 38)
        ax.set_ylim(-28, 14)
        ax.set_title(f"A6 R{radius:g}, travel {travel:g} mm: shapes, PIP axis at "
                     f"y={axis[0]:g} (grey: {JOINT_RADIUS} mm finger proxy)", fontsize=8)
        ax.legend(fontsize=6, loc="lower left")
        ei = a6.LEAF_WIDTH * a6.LEAF_THICKNESS ** 3 / 12 * np.mean(MODULUS_RANGE)
        for row in evaluate(radius, travel):
            tax.plot(row["_angles"], row["_torque"] * ei,
                     label=f"axis y={row['axis_y_mm']:g}")
        tax.axhline(0, color="k", lw=0.5)
        tax.set_xlabel("PIP flexion (deg)", fontsize=8)
        tax.set_ylabel(f"torque (N mm), E={np.mean(MODULUS_RANGE):g} MPa", fontsize=8)
        tax.set_title("restoring torque", fontsize=8)
        tax.legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "A6 designs")
    parser.add_argument("--tune", action="store_true",
                        help="search for each radius's travel instead of checking")
    args = parser.parse_args()

    if args.tune:
        table = {r: tune(r) for r in TUNE_RADII}
        print("TRAVEL_BY_RADIUS = {")
        for r, t in table.items():
            if t is not None:
                print(f"    {r}: {t},")
        print("}")
        return

    summary = []
    for radius in a6.RADII:
        for row in evaluate(radius, a6.TRAVEL_BY_RADIUS[radius]):
            row = {k: v for k, v in row.items() if not k.startswith("_")}
            summary.append(row)
            print(row, flush=True)

    with open(args.out / "A6_pip_rom_check.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    plot(args.out / "A6_pip_rom_shapes.png", AXIS_POSITIONS[1])

    failed = [r for r in summary if not r["passes"]]
    print(f"{len(summary) - len(failed)} of {len(summary)} design/axis cases pass")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
