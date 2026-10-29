"""Check whether each A6 leaf can follow a human PIP through its range of motion.

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
T-head stop limits to ``TRAVEL_PROXIMAL`` one way and ``TRAVEL_DISTAL`` the other.

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

    python scripts/a6_rom_check.py
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

#: Human PIP active range, in degrees: about 100 to 110 flexion and 0 to a few degrees of
#: hyperextension (AAOS norms). Positive is flexion.
PIP_RANGE = (-5.0, 110.0)
#: Candidate PIP axis positions, (y, z) in mm, in the A8 frame. The phalanx centreline is
#: z = 0. These are guesses spanning the gap between the cuffs, not measurements.
AXIS_POSITIONS = ((10.0, 0.0), (15.0, 0.0), (20.0, 0.0), (24.0, 0.0))
#: Distance from the axis inside which the leaf is taken to be touching the finger, in mm.
#: The PP cuff's bore is 7.0 mm tall, so this is the bone's dorsal surface at the cuff.
#: The real knuckle is larger, so this is a lenient test.
JOINT_RADIUS = 3.5
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

    def __init__(self, radius):
        arc = a6.solve_layout(radius)
        self.radius = radius
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

    def solve(self, angle, axis, guess):
        """Equilibrium shape at joint angle ``angle`` (radians), EI = 1."""
        axis = np.array(axis)
        mouth = axis + _rot(self.b - axis, angle)
        theta_mouth = self.theta_b - angle
        direction = np.array([math.cos(theta_mouth), math.sin(theta_mouth)])

        def residual(p):
            m0, ny, nz, length = p
            end = self.shoot(m0, ny, nz, length)[-1]
            # Wrap the angle error into (-pi, pi]: the leaf may legitimately turn more
            # than half a revolution in total but not relative to where it should be.
            dth = (end[2] - theta_mouth + math.pi) % (2 * math.pi) - math.pi
            return [end[0] - mouth[0], end[1] - mouth[1], dth,
                    ny * direction[0] + nz * direction[1]]

        fit = least_squares(residual, guess, xtol=1e-12, ftol=1e-12, gtol=1e-12)
        return fit.x, float(np.max(np.abs(fit.fun)))

    def energy(self, params):
        """Stored bending energy, and the largest curvature change, for EI = 1."""
        shape = self.shoot(*params).T
        s = np.linspace(0.0, params[3], N_STEPS + 1)
        m = shape[3]
        return float(0.5 * np.trapezoid(m ** 2, s)), float(np.max(np.abs(m))), shape


def sweep(leaf: Leaf, axis):
    """Follow the leaf from neutral to each end of the PIP range."""
    rows = {}
    for end in PIP_RANGE:
        guess = np.array([0.0, 0.0, 0.0, leaf.arc_length])
        angles = np.arange(0.0, end + math.copysign(STEP_DEG, end) / 2,
                           math.copysign(STEP_DEG, end))
        previous = 0.0
        for deg in angles:
            params, err = leaf.solve(math.radians(deg), axis, guess)
            # A failed step is retried in smaller increments before the sweep gives up,
            # so a stop marks where the leaf has no nearby equilibrium (it snaps), not
            # where the solver happened to take too large a stride.
            sub = 1
            while err > TOL and sub < 64:
                sub *= 4
                trial = guess
                for frac in np.linspace(0.0, 1.0, sub + 1)[1:]:
                    trial, err = leaf.solve(math.radians(previous + frac * (deg - previous)),
                                            axis, trial)
                    if err > TOL:
                        break
                params = trial
            if err > TOL:
                break
            guess, previous = params, deg
            rows[round(deg, 6)] = params
    return dict(sorted(rows.items()))


def analyse(leaf: Leaf, axis):
    rows = sweep(leaf, axis)
    angles = np.array(list(rows))
    energy, kappa, slide, approach = [], [], [], []
    for deg in angles:
        params = rows[deg]
        u, k, shape = leaf.energy(params)
        energy.append(u)
        kappa.append(k)
        slide.append(params[3] - leaf.arc_length)
        approach.append(float(np.min(np.hypot(shape[0] - axis[0], shape[1] - axis[1]))))
    energy = np.array(energy)
    torque = np.gradient(energy, np.radians(angles)) if len(angles) > 2 else energy * 0
    return angles, energy, torque, np.array(kappa), np.array(slide), np.array(approach)


def plot_shapes(path: Path, axis, angles=(0, 30, 60, 90, 110)) -> None:
    """Leaf shapes through the range, one panel per radius, with the stroke marked."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(a6.RADII), 1, figsize=(7, 2.4 * len(a6.RADII)))
    colours = plt.cm.viridis(np.linspace(0, 0.9, len(angles)))
    for ax, radius in zip(axes, a6.RADII):
        leaf = Leaf(radius)
        rows = sweep(leaf, axis)
        for deg, colour in zip(angles, colours):
            if float(deg) not in rows:
                continue
            params = rows[float(deg)]
            y, z = leaf.shoot(*params).T[:2]
            slide = params[3] - leaf.arc_length
            ax.plot(y, z, color=colour, lw=1.6,
                    label=f"{deg} deg, slide {slide:+.1f} mm")
        ax.add_patch(plt.Circle(axis, JOINT_RADIUS, color="0.85", zorder=0))
        ax.plot(*axis, "k+")
        ax.set_aspect("equal")
        ax.set_xlim(-2, 36)
        ax.set_ylim(-26, 12)
        name = "flat" if radius is None else f"R{radius:g}"
        ax.set_title(f"A6 {name}: PIP axis at y={axis[0]:g}, z={axis[1]:g} "
                     f"(grey: {JOINT_RADIUS} mm finger proxy)", fontsize=8)
        ax.legend(fontsize=6, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=110)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "A6 designs")
    args = parser.parse_args()

    ei_per_e = a6.LEAF_WIDTH * a6.LEAF_THICKNESS ** 3 / 12  # mm^4
    half_t = a6.LEAF_THICKNESS / 2
    summary = []
    for radius in a6.RADII:
        leaf = Leaf(radius)
        for axis in AXIS_POSITIONS:
            angles, _, torque, kappa, slide, approach = analyse(leaf, axis)
            flex = angles >= 0
            reached = float(angles.max())
            in_travel = (slide <= a6.TRAVEL_PROXIMAL) & (slide >= -a6.TRAVEL_DISTAL)
            # Largest flexion reached with the tip still inside its travel the whole way.
            ok = flex & in_travel
            first_bad = np.where(flex & ~in_travel)[0]
            rom_travel = float(angles[first_bad[0] - 1]) if first_bad.size else reached
            top = angles == reached
            tau_full = float(torque[top][0])
            row = {
                "radius_mm": "flat" if radius is None else f"{radius:g}",
                "axis_y_mm": axis[0],
                "axis_z_mm": axis[1],
                "max_flexion_solved_deg": reached,
                "max_flexion_within_travel_deg": rom_travel,
                "slide_at_max_mm": round(float(slide[top][0]), 2),
                "slide_range_mm": f"{slide[ok | ~flex].min():.2f} .. {slide.max():.2f}",
                "peak_strain_pct": round(100 * half_t * float(kappa.max()), 1),
                "closest_to_axis_mm": round(float(approach.min()), 2),
                "touches_finger_from_deg": next(
                    (float(d) for d, r in zip(angles, approach) if d > 0 and r < JOINT_RADIUS),
                    "never"),
                "torque_at_max_per_EI_1_per_mm": round(tau_full, 4),
                "torque_at_max_Nmm": " .. ".join(
                    f"{tau_full * e * ei_per_e:.2f}" for e in MODULUS_RANGE),
                "stiffness_near_0_Nmm_per_rad": " .. ".join(
                    f"{float(np.interp(0.3, np.radians(angles), torque)) / 0.3 * e * ei_per_e:.2f}"
                    for e in MODULUS_RANGE),
            }
            summary.append(row)
            print(row)

    with open(args.out / "A6_pip_rom_check.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    plot_shapes(args.out / "A6_pip_rom_shapes.png", AXIS_POSITIONS[1])


if __name__ == "__main__":
    main()
