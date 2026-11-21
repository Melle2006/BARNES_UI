"""Choose where the flexor tendon attaches on each phalanx: MCP, PIP and DIP.

What this replaces, and why
---------------------------

An earlier stand-alone script (``three_joint_pivot_optimizer.py``, never committed)
maximised ``T = x F sin(x theta / (L + x))`` over the anchor distance ``x`` for each
joint. Every strategy it offered returned ``x = Lp``, the upper bound, for every joint,
and its pose-sweep table was identical across the three strategies. Those were not
three agreeing answers; they were one answer forced three times. Four faults, in order
of how much they matter:

1. **The objective has no interior optimum.** A longer lever arm always gives more
   torque, under that formula and under the exact geometry alike. Maximising torque
   with only an upper bound on ``x`` therefore returns the upper bound by
   construction. What makes a pivot-to-anchor distance *best* is the cost of a longer
   lever: by virtual work the moment arm *is* the tendon excursion per radian, so
   every millimetre of lever spends actuator stroke. Without a stroke limit, and
   without a torque requirement to meet, there is nothing to optimise.

2. **The torque formula uses the wrong angle.** For a tendon running from a guide a
   distance ``L`` before the pivot to an anchor ``x`` beyond it, the triangle
   guide-pivot-anchor has an exterior angle ``theta`` at the pivot, split between the
   guide corner (about ``x theta/(L+x)``) and the anchor corner (about
   ``L theta/(L+x)``). The lever is ``x`` times the sine of the *anchor* corner, or
   equivalently ``L`` times the sine of the *guide* corner. The old formula multiplied
   ``x`` by the sine of the guide corner, mixing the two; it is not an approximation
   of the geometry and it fails the virtual-work check ``r = -dl/dtheta`` that the
   exact expression passes (see ``check_virtual_work``). At the MCP with the old
   placeholder dimensions it under-predicts the moment arm by about 25 % at 46 degrees.

3. **"Worst case" was degenerate.** It took the minimum raw torque over the angle
   range, which for a torque rising with angle is always the torque at
   ``theta_min``. The answer was decided by whichever ``theta_min`` was typed in.
   The meaningful worst case is the smallest *margin* of available torque over the
   torque the joint has to supply -- TPU return torque plus the fingertip load --
   which grows with flexion too.

4. **One tendon, independent joints.** All three joints are flexed by the same tendon,
   so they share its tension and their excursions add against a single actuator
   stroke. Optimising each joint alone cannot see that trade.

What this script does instead
-----------------------------

Exact planar tendon geometry with optional palmar offsets of the guide and anchor;
torque required at each joint from the TPU stiffness and a fingertip force through the
chain's statics; actuator force and stroke derived from the servo and horn radius. It
reports two designs, both well posed:

* **Minimum stroke** -- the shortest lever at each joint that still delivers the
  required torque with safety factor ``SAFETY_FACTOR`` at every pose of the grasp.
  Separable by joint, because the margin and the excursion of a joint depend only on
  its own anchor.
* **Maximum margin** -- the anchors that maximise the smallest margin across all
  three joints while the summed excursion fits the stroke. This one is coupled, and
  is solved by an exhaustive grid so nothing depends on the problem being convex.

It also reports the tension at which each joint, unloaded, flexes against its TPU
spring -- the order in which the joints close, which for an underactuated finger is
set by these same lever arms.

Every number in ``JOINTS`` and the actuator block is a PLACEHOLDER unless its comment
says where it came from. Replace them with measured CAD values before trusting an
anchor position to a print.

Usage
-----

    python scripts/tendon_pivot_optimizer.py [--out results/tendon_pivot]

Needs numpy; matplotlib is optional and only draws the figure.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass, replace
from functools import reduce
from pathlib import Path

import numpy as np

# -- inputs --------------------------------------------------------------------------


@dataclass(frozen=True)
class JointSpec:
    """One joint of the planar finger. Lengths in metres, angles in radians.

    Frame: pivot at the origin, the proximal link along -x, flexion turning the
    distal link counter-clockwise, palmar side +y. The tendon leaves the proximal
    link through a guide at ``(-guide_distance_m, guide_offset_m)`` and is anchored
    (or enters the next guide) on the distal link at ``(x, anchor_offset_m)`` in the
    distal link's own frame. ``x`` is the design variable.
    """

    name: str
    guide_distance_m: float     # was L_m in the old script
    distal_link_m: float        # pivot to next pivot (or fingertip); was Lp
    x_min_m: float
    x_max_m: float
    contact_theta_min_rad: float  # grasp window over which the fingertip load acts
    contact_theta_max_rad: float
    theta_max_rad: float          # full flexion; the excursion is counted to here
    tpu_stiffness_Nm_per_rad: float
    guide_offset_m: float = 0.0
    anchor_offset_m: float = 0.0


#: A3 twin-strap flexure, CalculiX, provisional 12 MPa modulus: 6.103 N.mm/rad
#: (results/a3_rom_vs_fea.json). Used at all three joints until each joint's own
#: flexure is analysed. PROVISIONAL -- the modulus is not calibrated.
A3_STIFFNESS_NM_PER_RAD = 6.10336e-3

#: Geometry and angle ranges carried over from the old script so the two can be
#: compared directly. PLACEHOLDERS, not CAD measurements. They are self-consistent as
#: a chain: palm 60 mm, proximal 45 mm, middle 25 mm, distal 18 mm.
#:
#: The contact window is new and also a placeholder: a cylindrical grasp loads the
#: fingertip part-way through the flexion range, not at full flexion, where the
#: proportional pose curls the tip back past the palm and a normal fingertip force
#: means nothing.
JOINTS = (
    JointSpec("MCP", guide_distance_m=0.060, distal_link_m=0.045,
              x_min_m=0.002, x_max_m=0.045,
              contact_theta_min_rad=0.20, contact_theta_max_rad=0.90,
              theta_max_rad=1.40,
              tpu_stiffness_Nm_per_rad=A3_STIFFNESS_NM_PER_RAD),
    JointSpec("PIP", guide_distance_m=0.045, distal_link_m=0.025,
              x_min_m=0.002, x_max_m=0.025,
              contact_theta_min_rad=0.20, contact_theta_max_rad=1.20,
              theta_max_rad=1.75,
              tpu_stiffness_Nm_per_rad=A3_STIFFNESS_NM_PER_RAD),
    JointSpec("DIP", guide_distance_m=0.025, distal_link_m=0.018,
              x_min_m=0.002, x_max_m=0.018,
              contact_theta_min_rad=0.20, contact_theta_max_rad=0.80,
              theta_max_rad=1.35,
              tpu_stiffness_Nm_per_rad=A3_STIFFNESS_NM_PER_RAD),
)

#: MG995-class servo (firmware/servo_hold_45). 0.94 N.m is the datasheet stall
#: torque at 4.8 V; DERATE keeps the working point well away from stall.
SERVO_STALL_TORQUE_NM = 0.94
SERVO_TRAVEL_RAD = math.pi
DERATE = 0.5
#: Horn (or spool) radius the tendon winds on. PLACEHOLDER. It sets the force/stroke
#: split: F = DERATE * stall / R, stroke = R * travel. Their product is fixed.
HORN_RADIUS_M = 0.010

#: Fingertip force the grasp must hold, normal to the distal phalanx. PLACEHOLDER.
FINGERTIP_FORCE_N = 5.0
SAFETY_FACTOR = 1.5

N_X = 241       # anchor positions per joint; the coupled search is N_X**3
N_POSE = 201    # poses along the grasp


# -- geometry ------------------------------------------------------------------------


def _points(spec: JointSpec, theta, x):
    """Guide (A) and anchor (B) positions, broadcast over theta and x."""
    theta = np.asarray(theta, dtype=float)
    x = np.asarray(x, dtype=float)
    ax, ay = -spec.guide_distance_m, spec.guide_offset_m
    c, s = np.cos(theta), np.sin(theta)
    bx = c * x - s * spec.anchor_offset_m
    by = s * x + c * spec.anchor_offset_m
    return ax, ay, bx, by


def tendon_length(spec: JointSpec, theta, x):
    """Guide-to-anchor length of the tendon crossing this joint (m)."""
    ax, ay, bx, by = _points(spec, theta, x)
    return np.hypot(bx - ax, by - ay)


def moment_arm(spec: JointSpec, theta, x):
    """Perpendicular distance from the pivot to the tendon (m); flexing is positive.

    Torque of a tension F pulling the anchor B toward the guide A about the pivot O is
    ``(B x F)_z = F (B x A)_z / |A - B|``.
    """
    ax, ay, bx, by = _points(spec, theta, x)
    return (bx * ay - by * ax) / np.hypot(bx - ax, by - ay)


def old_formula_moment_arm(spec: JointSpec, theta, x):
    """The lever implied by the old script's T = x F sin(x theta / (L + x))."""
    x = np.asarray(x, dtype=float)
    return x * np.sin(x * np.asarray(theta) / (spec.guide_distance_m + x))


def check_virtual_work(spec: JointSpec, x: float, h: float = 1e-6) -> float:
    """Largest |r + dl/dtheta| over the range, in metres. Zero for correct geometry.

    The tendon does work F dl on the joint, which does work tau dtheta, so the moment
    arm must equal the rate the tendon shortens. This checks the torque expression
    against a quantity computed a completely different way.
    """
    th = np.linspace(h, spec.theta_max_rad, 400)
    dl = (tendon_length(spec, th + h, x) - tendon_length(spec, th - h, x)) / (2 * h)
    return float(np.max(np.abs(moment_arm(spec, th, x) + dl)))


def excursion(spec: JointSpec, x):
    """Tendon taken up flexing this joint from straight to theta_max (m)."""
    return tendon_length(spec, 0.0, x) - tendon_length(spec, spec.theta_max_rad, x)


# -- statics of the grasp ------------------------------------------------------------


def grasp_angles(joints=JOINTS, n: int = N_POSE) -> np.ndarray:
    """Joint angles along the grasp window, shape (n, n_joints).

    All joints move proportionally across their contact windows. That is a stand-in
    for the real closing path, which the object decides.
    """
    q = np.linspace(0.0, 1.0, n)[:, None]
    lo = np.array([j.contact_theta_min_rad for j in joints])
    hi = np.array([j.contact_theta_max_rad for j in joints])
    return lo + q * (hi - lo)


def fingertip_load_torques(angles: np.ndarray, joints=JOINTS,
                           fingertip_force_N: float = FINGERTIP_FORCE_N) -> np.ndarray:
    """Torque each joint needs to resist a fingertip force normal to the distal link.

    With absolute link angles phi_i (cumulative flexion), the torque about joint j is
    f * (p_tip - p_j) . e_last, i.e. f times the sum of link_i cos(phi_last - phi_i)
    over the links distal to j. Shape follows ``angles``.
    """
    lengths = np.array([j.distal_link_m for j in joints])
    phi = np.cumsum(angles, axis=-1)
    rel = np.cos(phi[..., -1:] - phi) * lengths
    # Torque about joint j sums the links from j outward: reverse cumulative sum.
    return fingertip_force_N * np.flip(np.cumsum(np.flip(rel, -1), -1), -1)


def required_torques(angles: np.ndarray, joints=JOINTS,
                     fingertip_force_N: float = FINGERTIP_FORCE_N) -> np.ndarray:
    k = np.array([j.tpu_stiffness_Nm_per_rad for j in joints])
    return k * angles + fingertip_load_torques(angles, joints, fingertip_force_N)


def actuator(horn_radius_m: float = HORN_RADIUS_M) -> tuple[float, float]:
    """Usable tendon tension (N) and stroke (m) for the servo on a given horn."""
    return (DERATE * SERVO_STALL_TORQUE_NM / horn_radius_m,
            horn_radius_m * SERVO_TRAVEL_RAD)


# -- optimisation --------------------------------------------------------------------


@dataclass
class JointTables:
    xs: np.ndarray          # (N_X,)
    margin: np.ndarray      # (N_X,) worst available/required ratio over the grasp
    worst_pose: np.ndarray  # (N_X,) index of the pose setting that ratio
    excursion: np.ndarray   # (N_X,)


def joint_tables(force_N: float, joints=JOINTS,
                 fingertip_force_N: float = FINGERTIP_FORCE_N) -> list[JointTables]:
    angles = grasp_angles(joints)
    req = required_torques(angles, joints, fingertip_force_N)
    tables = []
    for j, spec in enumerate(joints):
        xs = np.linspace(spec.x_min_m, spec.x_max_m, N_X)
        avail = force_N * moment_arm(spec, angles[:, j][None, :], xs[:, None])
        # A pose needing no flexion torque is met by any tension. (It is where the
        # tendon can over-flex the joint instead -- a stability question this ratio
        # does not answer; see free_closing_tension.)
        need = req[None, :, j]
        ratio = np.where(need > 0, avail / np.where(need > 0, need, 1.0), np.inf)
        tables.append(JointTables(xs, ratio.min(axis=1), ratio.argmin(axis=1),
                                  excursion(spec, xs)))
    return tables


def min_stroke_design(tables: list[JointTables], target: float = SAFETY_FACTOR):
    """Anchor at each joint using the least stroke whose worst margin reaches ``target``.

    For a collinear tendon this is simply the shortest feasible anchor. With a palmar
    offset neither the margin nor the excursion need be monotonic in x, so the
    feasible set is searched rather than its first point taken. Returns None for a
    joint that cannot reach the target anywhere in its range.
    """
    picks = []
    for t in tables:
        ok = np.nonzero(t.margin >= target)[0]
        picks.append(int(ok[np.argmin(t.excursion[ok])]) if ok.size else None)
    return picks


def max_margin_design(tables: list[JointTables], stroke_m: float):
    """Anchors maximising the smallest joint margin with total excursion <= stroke.

    Exhaustive over the grid. Ties (within 0.1 %) go to the smaller total excursion,
    which leaves stroke for tendon stretch and slack.
    """
    m = reduce(np.minimum, np.ix_(*[t.margin for t in tables]))
    e = reduce(np.add, np.ix_(*[t.excursion for t in tables]))
    m = np.where(e <= stroke_m, m, -np.inf)
    best = m.max()
    if not np.isfinite(best):
        return None
    near = np.where(m >= best - 1e-3 * abs(best), e, np.inf)
    return [int(i) for i in np.unravel_index(np.argmin(near), near.shape)]


def free_closing_tension(spec: JointSpec, x: float, n: int = 400):
    """Tension holding the unloaded joint at each angle against its TPU spring (N).

    Where this falls with angle the joint is unstable: once it starts to flex, the
    same tension carries it to its stop. With no palmar offset the moment arm is zero
    when straight, so the tension at theta -> 0 tends to k (L + x) / (L x), not zero.
    """
    th = np.linspace(1e-3, spec.theta_max_rad, n)
    return th, spec.tpu_stiffness_Nm_per_rad * th / moment_arm(spec, th, x)


# -- reporting -----------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run(out_dir: Path, joints=JOINTS, fingertip_force_N: float = FINGERTIP_FORCE_N,
        horn_radius_m: float = HORN_RADIUS_M) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    force, stroke = actuator(horn_radius_m)
    tables = joint_tables(force, joints, fingertip_force_N)
    designs = {"min_stroke": min_stroke_design(tables),
               "max_margin": max_margin_design(tables, stroke)}

    print(f"Actuator: {force:.1f} N usable tension, {stroke * 1e3:.1f} mm stroke "
          f"(horn {horn_radius_m * 1e3:.0f} mm, derate {DERATE})")
    print(f"Requirement: {fingertip_force_N} N at the fingertip, "
          f"safety factor {SAFETY_FACTOR}\n")

    for spec in joints:
        err = check_virtual_work(spec, spec.x_max_m)
        print(f"{spec.name}: virtual-work residual {err * 1e9:.2f} nm "
              f"(exact model; must be ~0)")
    print()

    angles = grasp_angles(joints)
    req = required_torques(angles, joints, fingertip_force_N)
    summary, sweep = [], []
    for name, picks in designs.items():
        if picks is None:
            print(f"{name}: no design fits the {stroke * 1e3:.1f} mm stroke at all")
            continue
        total = 0.0
        print(f"{name}:")
        for j, (spec, t, i) in enumerate(zip(joints, tables, picks)):
            if i is None:
                print(f"  {spec.name}: cannot reach SF {SAFETY_FACTOR} even at "
                      f"x = {spec.x_max_m * 1e3:.1f} mm "
                      f"(best margin {t.margin[-1]:.2f})")
                summary.append({"design": name, "joint": spec.name, "x_opt_mm": "",
                                "x_max_mm": spec.x_max_m * 1e3,
                                "worst_margin": t.margin[-1],
                                "worst_pose_theta_deg": "", "excursion_mm": "",
                                "at_upper_bound": "infeasible"})
                continue
            x = t.xs[i]
            total += t.excursion[i]
            worst = math.degrees(angles[t.worst_pose[i], j])
            print(f"  {spec.name}: x = {x * 1e3:6.2f} mm of {spec.x_max_m * 1e3:.1f} | "
                  f"worst margin {t.margin[i]:.2f} at {worst:5.1f} deg | "
                  f"excursion {t.excursion[i] * 1e3:5.2f} mm")
            summary.append({"design": name, "joint": spec.name, "x_opt_mm": x * 1e3,
                            "x_max_mm": spec.x_max_m * 1e3,
                            "worst_margin": t.margin[i],
                            "worst_pose_theta_deg": worst,
                            "excursion_mm": t.excursion[i] * 1e3,
                            "at_upper_bound": bool(i == len(t.xs) - 1)})
            for q_i in range(0, N_POSE, (N_POSE - 1) // 8):
                th = angles[q_i, j]
                sweep.append({
                    "design": name, "pose_q": q_i / (N_POSE - 1), "joint": spec.name,
                    "theta_deg": math.degrees(th), "x_mm": x * 1e3,
                    "moment_arm_mm": float(moment_arm(spec, th, x)) * 1e3,
                    "old_formula_arm_mm": float(old_formula_moment_arm(spec, th, x)) * 1e3,
                    "available_torque_Nm": float(force * moment_arm(spec, th, x)),
                    "required_torque_Nm": float(req[q_i, j]),
                    "margin": float(force * moment_arm(spec, th, x) / req[q_i, j]),
                })
        if all(i is not None for i in picks):
            fits = "fits" if total <= stroke else "DOES NOT FIT"
            print(f"  total excursion {total * 1e3:.2f} mm -- {fits} the "
                  f"{stroke * 1e3:.1f} mm stroke")
        print()

    _write_csv(out_dir / "pivot_optimum.csv", summary)
    _write_csv(out_dir / "pose_sweep.csv", sweep)

    # How the answer moves with the horn radius: force falls as stroke rises.
    horn_rows = []
    for r in (0.006, 0.008, 0.010, 0.012, 0.015, 0.020):
        f_r, s_r = actuator(r)
        tb = joint_tables(f_r, joints, fingertip_force_N)
        picks = max_margin_design(tb, s_r)
        row = {"horn_radius_mm": r * 1e3, "tension_N": f_r, "stroke_mm": s_r * 1e3}
        for spec, t, i in zip(joints, tb, picks or [None] * len(joints)):
            row[f"{spec.name}_x_mm"] = t.xs[i] * 1e3 if i is not None else ""
        row["min_margin"] = (min(t.margin[i] for t, i in zip(tb, picks))
                             if picks else "")
        horn_rows.append(row)
    _write_csv(out_dir / "horn_radius_sweep.csv", horn_rows)
    print("Horn radius sweep (max-margin design):")
    for row in horn_rows:
        print("  " + ", ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}"
                               for k, v in row.items()))

    _plot(out_dir, joints, tables, designs, force, fingertip_force_N)
    print(f"\nWrote results to {out_dir}")
    return {"tables": tables, "designs": designs, "force": force, "stroke": stroke}


def _plot(out_dir: Path, joints, tables, designs, force, fingertip_force_N) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping the figure.")
        return

    pick = designs["max_margin"] or [len(t.xs) - 1 for t in tables]
    fig, axes = plt.subplots(len(joints), 3, figsize=(15, 10), constrained_layout=True)
    for row, (spec, t, i) in enumerate(zip(joints, tables, pick)):
        x = t.xs[i]
        th = np.linspace(0.0, spec.theta_max_rad, 300)
        ax = axes[row, 0]
        ax.plot(np.degrees(th), moment_arm(spec, th, x) * 1e3, label="exact geometry")
        ax.plot(np.degrees(th), old_formula_moment_arm(spec, th, x) * 1e3, "--",
                label="old formula (ignores offset)" if spec.guide_offset_m else "old formula")
        ax.set(title=f"{spec.name}: moment arm at x = {x * 1e3:.1f} mm",
               xlabel="joint angle (deg)", ylabel="moment arm (mm)")
        ax.legend()

        ax = axes[row, 1]
        ax.plot(t.xs * 1e3, t.margin, label="worst margin over grasp")
        ax.axhline(SAFETY_FACTOR, color="grey", ls=":", label=f"SF {SAFETY_FACTOR}")
        ax.set(xlabel="anchor distance x (mm)", ylabel="available / required torque")
        ax2 = ax.twinx()
        ax2.plot(t.xs * 1e3, t.excursion * 1e3, color="C2", label="excursion")
        ax2.set_ylabel("excursion over full flexion (mm)")
        for name, style in (("min_stroke", "C3"), ("max_margin", "C1")):
            p = designs[name]
            if p and p[row] is not None:
                ax.axvline(t.xs[p[row]] * 1e3, color=style, ls="--", label=name)
        ax.set_title(f"{spec.name}: margin vs stroke cost")
        ax.legend(loc="lower right", fontsize=8)

        ax = axes[row, 2]
        th, f = free_closing_tension(spec, x)
        ax.plot(np.degrees(th), f)
        ax.set(title=f"{spec.name}: unloaded closing tension",
               xlabel="joint angle (deg)", ylabel="tendon tension (N)")
    h = joints[0].guide_offset_m * 1e3
    fig.suptitle(f"Tendon anchor optimisation -- {force:.0f} N tension, "
                 f"{fingertip_force_N} N fingertip load, {h:.1f} mm palmar offset "
                 f"(placeholder geometry)")
    fig.savefig(out_dir / "tendon_pivot.png", dpi=150)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path,
                   default=Path(__file__).resolve().parents[1] / "results" / "tendon_pivot")
    p.add_argument("--palmar-offset-mm", type=float, default=0.0,
                   help="palmar offset of every guide and anchor from the link axis; "
                        "0 reproduces the old script's collinear tendon")
    p.add_argument("--fingertip-force-n", type=float, default=FINGERTIP_FORCE_N)
    p.add_argument("--horn-radius-mm", type=float, default=HORN_RADIUS_M * 1e3)
    args = p.parse_args()
    h = args.palmar_offset_mm * 1e-3
    run(args.out, tuple(replace(j, guide_offset_m=h, anchor_offset_m=h) for j in JOINTS),
        args.fingertip_force_n, args.horn_radius_mm * 1e-3)


if __name__ == "__main__":
    main()
