"""Where to route the flexor tendon: Type A (pinned joints) and Type B (TPU joints).

Builds on ``tendon_pivot_optimizer.py`` (exact tendon geometry, virtual-work-checked
moment arm, torque margin against a fingertip load, single tendon sharing one servo's
force and stroke) and applies it to the two hand designs.

Type A -- TPU cover over a rigid joint
--------------------------------------

The pivots are fixed by the hardware: the MCP ball centre and the PIP/DIP pins,
measured from the hand assembly by ``type_a_geometry.py``. What is free is where the
tendon is guided on each side of each joint. The prototype phalanges carry a row of
3.2 mm holes on their centreline for exactly this. Instead of trying only those holes,
this sweeps every station along the full length of each link:

* ``a`` -- station of the last guide on the proximal link, measured back from the joint;
* ``x`` -- station of the first guide (or the anchor) on the distal link;
* ``h`` -- palmar offset of the tendon from the link centreline at both guides,
  measured from the line through the pivots. Two scenarios: ``flush``, where the
  offset is limited at each station by the measured palmar surface, and
  ``standoff``, where a screw or guide may stand proud of it up to
  ``FREE_OFFSET_MAX_MM`` (how the prototype's screws are meant to be used).

For every combination it computes the worst torque margin over the grasp and the
tendon excursion over the CAD range of motion. Each joint's Pareto front (margin up,
excursion down) then feeds a coupled search: the three joints share one tension and
one stroke. Results are given as the fingertip force each design can hold, because
the margin scales with that force (the TPU cover's torque is negligible beside it).

Type B -- the TPU is the joint
------------------------------

There is no pin, so there is no pivot position to choose. The analysis is therefore
different in kind:

* **Where the joint rotates.** A uniform leaf (B3, B6), a full-length notch (B1
  notch100) and the lattice bend roughly at constant curvature. The distal collar's
  instantaneous centre of rotation starts at mid flex zone and drifts as the joint
  closes; this computes that drift. A cross-axis pivot (B5) and a short notch (B1
  notch050) hold the centre near mid flex zone by construction.
* **The tendon lever.** The tendon crosses the flex zone in open air at offset ``d``
  from the flexure's neutral axis. Its moment arm follows from the same virtual-work
  identity, using the bent shape rather than a pin.
* **The constraint Type A does not have.** The tendon's tension compresses the
  joint. In Type A the pin carries that. In Type B the TPU leaves do, and a TPU leaf
  a millimetre thick buckles at a few newtons. So the binding limit is usually not the
  servo but the flexure's compressive capacity, and the lever ``d`` sets how much
  tension a given fingertip force needs.

Every material-dependent number uses the provisional 12 MPa modulus and scales
linearly with it. Every load case (fingertip force, grasp window, servo horn) is a
PLACEHOLDER stated at the top of this file.

Usage::

    python scripts/tendon_routing_analysis.py

Reads ``results/tendon_routing/type_a_geometry.json`` (run ``type_a_geometry.py``
first) and ``results/tendon_routing/type_b_inputs/*.csv``; writes CSVs and figures
next to them. Needs numpy; matplotlib for the figures.
"""

from __future__ import annotations

import csv
import json
import math
from functools import reduce
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "tendon_routing"

# -- load case and actuator (PLACEHOLDERS) -------------------------------------------

FINGERTIP_FORCE_N = 5.0        # normal to the distal phalanx, at the tip
CONTACT_START_DEG = 10.0       # grasp window: from here...
CONTACT_FRACTION = 0.7         # ...to this fraction of each joint's full flexion
SAFETY_FACTOR = 1.5

SERVO_STALL_TORQUE_NM = 0.94   # MG995 datasheet, 4.8 V (firmware/servo_hold_45)
SERVO_TRAVEL_RAD = math.pi
DERATE = 0.5
HORN_RADIUS_M = 0.010

#: A3 twin-strap cover, CalculiX at the provisional modulus (results/a3_rom_vs_fea.json).
TYPE_A_COVER_K_NM_PER_RAD = 6.10336e-3
MODULUS_MPA = 12.0             # provisional; 8-18 MPa is the project's stated range

#: Smallest lever allowed anywhere in the range (mm): below this the tendon is
#: crossing to the dorsal side and would extend the joint instead.
MIN_LEVER_MM = 0.5
#: Closest the two guides of a joint may come as it flexes (mm): two 3.2 mm posts.
MIN_GUIDE_GAP_MM = 3.5
#: Offset limit when guides may stand proud of the palmar surface, in mm.
FREE_OFFSET_MAX_MM = 12.0
SCENARIOS = ("flush", "standoff")
#: Material kept between a guide hole and the joint head (cam, ball socket), in mm.
HEAD_CLEARANCE_MM = 2.4        # hole radius 1.6 + 0.8 wall

N_POSE = 61
MAX_FRONT = 150


def actuator(horn_radius_m: float = HORN_RADIUS_M) -> tuple[float, float]:
    """Usable tendon tension (N) and stroke (mm)."""
    return (DERATE * SERVO_STALL_TORQUE_NM / horn_radius_m,
            horn_radius_m * SERVO_TRAVEL_RAD * 1e3)


# -- shared geometry (mm, rad, N.mm) -------------------------------------------------


def pin_tendon_length(theta, a, x, h):
    """Guide (-a, h) on the proximal link to (x, h) on the distal link turned by theta."""
    c, s = np.cos(theta), np.sin(theta)
    bx, by = c * x - s * h, s * x + c * h
    return np.hypot(bx + a, by - h)


def pin_moment_arm(theta, a, x, h):
    """Exact lever of that tendon about the pin. Same expression as
    tendon_pivot_optimizer.moment_arm, vectorised over a, x and h."""
    c, s = np.cos(theta), np.sin(theta)
    bx, by = c * x - s * h, s * x + c * h
    return (bx * h + by * a) / np.hypot(bx + a, by - h)


def arc_tendon_length(theta, flex_len, d):
    """Tendon across a flex zone bent to constant curvature, offset d palmar.

    The collar faces sit at the ends of an arc of length L and angle theta. The
    tendon's exit points lie on the concentric arc of radius L/theta - d, so the
    straight tendon between them is that arc's chord.
    """
    theta = np.maximum(np.asarray(theta, float), 1e-9)
    return 2.0 * (flex_len / theta - d) * np.sin(theta / 2.0)


def arc_moment_arm(theta, flex_len, d, step=1e-5):
    """-dl/dtheta for the constant-curvature joint: the tendon's effective lever."""
    return -(arc_tendon_length(theta + step, flex_len, d)
             - arc_tendon_length(theta - step, flex_len, d)) / (2 * step)


def arc_centre_of_rotation(theta, flex_len):
    """Instantaneous centre of the distal collar of a constant-curvature joint.

    Returns (along, palmar) from the proximal collar face, in mm. For a planar rigid
    motion with unit rotation rate, velocity v = z x (P - c), so c = P + (-v_y, v_x)
    rotated back: c = (P_x - v_y, P_y + v_x).
    """
    theta = np.maximum(np.asarray(theta, float), 1e-6)

    def p(t):
        return flex_len / t * np.sin(t), flex_len / t * (1.0 - np.cos(t))

    h = 1e-6
    (x0, y0), (x1, y1) = p(theta - h), p(theta + h)
    px, py = p(theta)
    vx, vy = (x1 - x0) / (2 * h), (y1 - y0) / (2 * h)
    return px - vy, py + vx


def fingertip_load_torques(angles_rad, link_lengths_mm, force_n):
    """Torque (N.mm) each joint must resist from a fingertip force normal to the DP."""
    phi = np.cumsum(angles_rad, axis=-1)
    rel = np.cos(phi[..., -1:] - phi) * np.asarray(link_lengths_mm)
    return force_n * np.flip(np.cumsum(np.flip(rel, -1), -1), -1)


def grasp_angles(theta_max_rad):
    """Joint angles along the grasp window: shape (N_POSE,) + shape of theta_max."""
    q = np.linspace(0.0, 1.0, N_POSE).reshape((-1,) + (1,) * np.ndim(theta_max_rad))
    lo = np.radians(CONTACT_START_DEG)
    hi = CONTACT_FRACTION * np.asarray(theta_max_rad)
    return lo + q * (hi - lo)


def pareto(margin, excursion):
    """Indices of the (max margin, min excursion) front."""
    order = np.lexsort((-margin, excursion))
    keep, best = [], -np.inf
    for i in order:
        if margin[i] > best + 1e-12:
            keep.append(i)
            best = margin[i]
    return np.array(keep, int)


def couple(fronts, stroke_mm):
    """Pick one point per joint maximising the smallest margin, total excursion <= stroke.

    ``fronts`` holds (margin, excursion) arrays. Ties within 0.1 % go to the least
    total excursion. Returns indices into each front, or None if nothing fits.
    """
    if any(len(f[0]) == 0 for f in fronts):
        return None
    m = reduce(np.minimum, np.ix_(*[f[0] for f in fronts]))
    e = reduce(np.add, np.ix_(*[f[1] for f in fronts]))
    m = np.where(e <= stroke_mm, m, -np.inf)
    best = m.max()
    if not np.isfinite(best):
        return None
    tie = np.where(m >= best - 1e-3 * abs(best), e, np.inf)
    return [int(i) for i in np.unravel_index(np.argmin(tie), tie.shape)]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# -- Type A --------------------------------------------------------------------------

JOINT_LINKS = {"MCP": ("MC", "PP"), "PIP": ("PP", "MP"), "DIP": ("MP", "DP")}


def _envelope(geo, key):
    env = geo["section_envelope"][key]
    s, pal = np.array(env["s"]), np.array(env["palmar"])

    def palmar_at(station):
        return np.interp(station, s, pal)
    return palmar_at


def type_a_joint_grid(geo, joint, theta_max, loads_per_N, force_n, scenario,
                      n_ax=28, n_h=25):
    """Every (a, x, h) for one joint: margin over the grasp and excursion over the ROM.

    Stations measured from this joint's pivot. ``loads_per_N`` is the fingertip-load
    torque per newton at each grasp pose for this joint (N.mm/N); ``theta_max`` the
    joint's full flexion from straight.
    """
    prox, dist = JOINT_LINKS[joint]
    lengths = geo["link_lengths"]
    head = {j: HEAD_CLEARANCE_MM + r for j, r in joint_head_radii(geo).items()}
    pal_p, pal_d = _envelope(geo, prox), _envelope(geo, dist)

    # Guides anywhere along the link, clear of the joint head at either end.
    a_lo = head[joint]
    a_hi = MC_GUIDE_RANGE_MM if prox == "MC" else lengths[prox] - head[_previous(joint)]
    x_lo = head[joint]
    x_hi = lengths[dist] - (TIP_MARGIN_MM if dist == "DP" else head[_next(joint)])
    a = np.linspace(a_lo, a_hi, n_ax)
    x = np.linspace(x_lo, x_hi, n_ax)
    # Envelopes are tabulated from each link's own proximal end; the metacarpal's
    # frame already runs back from the MCP.
    pal_a = pal_p(a) if prox == "MC" else pal_p(lengths[prox] - a)
    pal_x = pal_d(x)
    surface = np.minimum(pal_a[:, None], pal_x[None, :])
    if scenario == "flush":
        h = np.linspace(0.0, float(surface.max()), n_h)
    else:
        h = np.linspace(0.0, FREE_OFFSET_MAX_MM, n_h)
    A, X, H = np.meshgrid(a, x, h, indexing="ij")
    allowed = (H <= surface[..., None] + 1e-9) if scenario == "flush" \
        else np.ones_like(H, bool)

    angles = grasp_angles(theta_max)                     # (N_POSE,)
    k = TYPE_A_COVER_K_NM_PER_RAD * 1e3                  # N.mm/rad
    req = k * angles + loads_per_N * force_n             # N.mm
    tension, _ = actuator()
    r = pin_moment_arm(angles[None, None, None, :], A[..., None], X[..., None],
                       H[..., None])
    ratio = np.where(req > 0, tension * r / np.where(req > 0, req, 1.0), np.inf)
    margin = ratio.min(axis=-1)
    exc = pin_tendon_length(0.0, A, X, H) - pin_tendon_length(theta_max, A, X, H)
    # The tendon must flex the joint at every angle it reaches, not only across the
    # grasp window, and the two guides must not run into each other as it closes.
    th_full = np.linspace(np.radians(CONTACT_START_DEG), theta_max, 46)
    lever = pin_moment_arm(th_full[None, None, None, :], A[..., None], X[..., None],
                           H[..., None])
    span = pin_tendon_length(th_full[None, None, None, :], A[..., None], X[..., None],
                             H[..., None])
    allowed &= (lever.min(axis=-1) >= MIN_LEVER_MM) & (span.min(axis=-1) >= MIN_GUIDE_GAP_MM)
    margin = np.where(allowed, margin, -np.inf)
    bow = pin_moment_arm(theta_max, A, X, H)             # lever at full flexion
    return dict(a=a, x=x, h=h, A=A, X=X, H=H, margin=margin, excursion=exc,
                allowed=allowed, lever_full=bow, pal_a=pal_a, pal_x=pal_x)


#: Radius of the joint head around each pin (mm): the clevis cams measured on the
#: index finger (PIP 5.195, DIP 5.0). The MCP uses each finger's measured ball.
PIN_HEAD_RADIUS_MM = {"PIP": 5.195, "DIP": 5.0}
#: Upper limit on flexion from straight, used where the CAD has no earlier stop.
ANATOMICAL_MAX_DEG = {"MCP": 90.0, "PIP": 110.0, "DIP": 90.0}
MC_GUIDE_RANGE_MM = 40.0  # how far back along the metacarpal a guide is considered
TIP_MARGIN_MM = 2.0


def joint_head_radii(geo):
    return {"MCP": geo["mcp_ball_radius"], **PIN_HEAD_RADIUS_MM}


def _previous(joint):
    return {"PIP": "MCP", "DIP": "PIP"}[joint]


def _next(joint):
    return {"MCP": "PIP", "PIP": "DIP"}[joint]


def run_type_a(geom_path: Path, scenario: str) -> list[dict]:
    out = OUT / f"type_a_{scenario}"
    out.mkdir(exist_ok=True)
    data = json.loads(geom_path.read_text())
    tension, stroke = actuator()
    summary, all_slices, hole_rows, hole_best = [], [], [], []
    figs = {}
    for finger, geo in data["fingers"].items():
        L = geo["link_lengths"]
        theta_max = {j: math.radians(geo["rest_angles_deg"][j]
                                     + geo["rom_from_rest_deg"][j])
                     for j in ("MCP", "PIP", "DIP")}
        # The CAD stop where there is one; the MCP ball has none, so it and any stop
        # beyond the anatomical range fall back to that range.
        theta_max = {j: min(t, math.radians(ANATOMICAL_MAX_DEG[j]))
                     for j, t in theta_max.items()}
        # Grasp poses for all three joints together, for the chain statics.
        poses = np.stack([grasp_angles(theta_max[j]) for j in ("MCP", "PIP", "DIP")], 1)
        loads = fingertip_load_torques(poses, [L["PP"], L["MP"], L["DP"]], 1.0)

        grids, fronts = {}, []
        for j, joint in enumerate(("MCP", "PIP", "DIP")):
            g = type_a_joint_grid(geo, joint, theta_max[joint], loads[:, j],
                                  FINGERTIP_FORCE_N, scenario)
            flat_m, flat_e = g["margin"].ravel(), g["excursion"].ravel()
            ok = np.isfinite(flat_m)
            idx = np.nonzero(ok)[0][pareto(flat_m[ok], flat_e[ok])]
            if len(idx) > MAX_FRONT:     # the coupled search is cubic in front size
                idx = idx[np.unique(np.linspace(0, len(idx) - 1, MAX_FRONT).astype(int))]
            g["front"] = idx
            grids[joint] = g
            fronts.append((flat_m[idx], flat_e[idx]))
        pick = couple(fronts, stroke)
        figs[finger] = (grids, pick, theta_max)

        total = 0.0
        for joint, i_front in zip(("MCP", "PIP", "DIP"), pick or [None] * 3):
            g = grids[joint]
            if i_front is None:
                continue
            i = g["front"][i_front]
            ia, ix, ih = np.unravel_index(i, g["A"].shape)
            m, e = g["margin"].ravel()[i], g["excursion"].ravel()[i]
            total += e
            summary.append({
                "finger": finger, "joint": joint,
                "guide_on_proximal_mm_from_pivot": round(g["a"][ia], 2),
                "guide_on_distal_mm_from_pivot": round(g["x"][ix], 2),
                "palmar_offset_from_centreline_mm": round(g["h"][ih], 2),
                "offset_limit_here_mm": round(float(min(g["pal_a"][ia], g["pal_x"][ix])), 2),
                "worst_margin": round(m, 3),
                "holdable_fingertip_force_N": round(m * FINGERTIP_FORCE_N, 2),
                "excursion_mm": round(e, 2),
                "lever_at_full_flexion_mm": round(float(g["lever_full"][ia, ix, ih]), 2),
                "theta_max_deg": round(math.degrees(theta_max[joint]), 1),
            })
            # The full-length sweeps through the chosen point.
            for axis_name, values, sl in (
                    ("proximal_station", g["a"], (slice(None), ix, ih)),
                    ("distal_station", g["x"], (ia, slice(None), ih)),
                    ("palmar_offset", g["h"], (ia, ix, slice(None)))):
                for v, mm, ee in zip(values, g["margin"][sl], g["excursion"][sl]):
                    all_slices.append({
                        "finger": finger, "joint": joint, "swept": axis_name,
                        "value_mm": round(float(v), 3),
                        "worst_margin": round(float(mm), 4) if np.isfinite(mm) else "",
                        "holdable_fingertip_force_N":
                            round(float(mm) * FINGERTIP_FORCE_N, 3) if np.isfinite(mm) else "",
                        "excursion_mm": round(float(ee), 3)})
            # The prototype's own holes: every drilled pair, at every offset on the
            # grid the scenario allows, kept only where it passes the same checks
            # (positive lever through the range, guides clear of each other).
            prox, dist = JOINT_LINKS[joint]
            ph = geo["hole_stations"].get(prox, [])
            ph = ph if prox == "MC" else [L[prox] - s for s in ph]
            ph = [v for v in ph if v >= g["a"][0] - 1e-9]       # clear of the joint head
            dh = [v for v in geo["hole_stations"].get(dist, []) if v >= g["x"][0] - 1e-9]
            th = grasp_angles(theta_max[joint])
            th_full = np.linspace(np.radians(CONTACT_START_DEG), theta_max[joint], 46)
            jj = ("MCP", "PIP", "DIP").index(joint)
            req = TYPE_A_COVER_K_NM_PER_RAD * 1e3 * th + loads[:, jj] * FINGERTIP_FORCE_N
            for sa in ph:
                for sx in dh:
                    surface = min(np.interp(sa, g["a"], g["pal_a"]),
                                  np.interp(sx, g["x"], g["pal_x"]))
                    for hh in g["h"]:
                        if scenario == "flush" and hh > surface + 1e-9:
                            continue
                        if (pin_moment_arm(th_full, sa, sx, hh).min() < MIN_LEVER_MM or
                                pin_tendon_length(th_full, sa, sx, hh).min() < MIN_GUIDE_GAP_MM):
                            continue
                        r = pin_moment_arm(th, sa, sx, hh)
                        mm = float(np.min(np.where(req > 0, tension * r / req, np.inf)))
                        hole_rows.append({
                            "finger": finger, "joint": joint,
                            "proximal_hole_mm_from_pivot": round(sa, 2),
                            "distal_hole_mm_from_pivot": round(sx, 2),
                            "palmar_offset_mm": round(float(hh), 2),
                            "worst_margin": round(mm, 3),
                            "holdable_fingertip_force_N": round(mm * FINGERTIP_FORCE_N, 2),
                            "excursion_mm": round(float(
                                pin_tendon_length(0, sa, sx, hh)
                                - pin_tendon_length(theta_max[joint], sa, sx, hh)), 2)})
        print(f"Type A {finger}: total excursion {total:.1f} of {stroke:.1f} mm")
        hole_best.extend(_best_existing_holes(finger, hole_rows, stroke))
    write_csv(out / "optimum.csv", summary)
    write_csv(out / "sweeps.csv", all_slices)
    write_csv(out / "existing_holes_best.csv", hole_best)
    _plot_type_a(figs, data, out, scenario)
    return summary


def _best_existing_holes(finger, hole_rows, stroke):
    """One hole pair per joint, chosen together: the prototype's own answer.

    Same coupled rule as the continuous optimum -- maximise the weakest joint's
    holdable fingertip force with the three excursions inside the stroke -- but over
    the drilled holes only, at the offset the continuous optimum chose.
    """
    per_joint = [[r for r in hole_rows if r["finger"] == finger and r["joint"] == j]
                 for j in ("MCP", "PIP", "DIP")]
    pruned = []
    for rows in per_joint:
        m = np.array([r["worst_margin"] for r in rows], float)
        e = np.array([r["excursion_mm"] for r in rows], float)
        pruned.append([rows[i] for i in pareto(m, e)] if rows else [])
    per_joint = pruned
    fronts = [(np.array([r["worst_margin"] for r in rows], float),
               np.array([r["excursion_mm"] for r in rows], float)) for rows in per_joint]
    pick = couple(fronts, stroke)
    if pick is None:
        return []
    return [dict(rows[i], total_excursion_mm=round(sum(f[1][k] for f, k in
                                                      zip(fronts, pick)), 2))
            for rows, i in zip(per_joint, pick)]


def _plot_type_a(figs, data, out, scenario) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    for finger, (grids, pick, theta_max) in figs.items():
        geo = data["fingers"][finger]
        fig, axes = plt.subplots(3, 3, figsize=(16, 12), constrained_layout=True)
        for row, joint in enumerate(("MCP", "PIP", "DIP")):
            g = grids[joint]
            if pick is None:
                continue
            i = g["front"][pick[row]]
            ia, ix, ih = np.unravel_index(i, g["A"].shape)
            prox, dist = JOINT_LINKS[joint]
            for col, (vals, sl, label, holes) in enumerate((
                    (g["a"], (slice(None), ix, ih),
                     f"guide station on {prox}, mm back from the {joint} pivot",
                     geo["hole_stations"].get(prox, []) if prox == "MC"
                     else [geo["link_lengths"][prox] - s
                           for s in geo["hole_stations"].get(prox, [])]),
                    (g["x"], (ia, slice(None), ih),
                     f"guide station on {dist}, mm from the {joint} pivot",
                     geo["hole_stations"].get(dist, [])),
                    (g["h"], (ia, ix, slice(None)),
                     "palmar offset of the tendon from the centreline, mm", []))):
                ax = axes[row, col]
                mm = np.where(np.isfinite(g["margin"][sl]), g["margin"][sl], np.nan)
                ax.plot(vals, mm * FINGERTIP_FORCE_N, "C0", label="holdable fingertip force")
                ax.axvline(vals[(ia, ix, ih)[col]], color="C3", ls="--", label="chosen")
                for hs in holes:
                    ax.axvline(hs, color="grey", lw=0.6, alpha=0.6)
                ax.set_xlabel(label)
                ax.set_ylabel("fingertip force held (N)")
                ax2 = ax.twinx()
                ax2.plot(vals, g["excursion"][sl], "C2")
                ax2.set_ylabel("excursion over full flexion (mm)", color="C2")
                ax.set_title(f"{finger} {joint}")
                if row == 0 and col == 0:
                    ax.legend(loc="upper left", fontsize=8)
        fig.suptitle(f"Type A {finger}, {scenario} guides: sweeps through the coupled optimum "
                     f"(grey lines: the prototype's holes; {FINGERTIP_FORCE_N} N "
                     "reference load, placeholder actuator)")
        fig.savefig(out / f"{finger.lower()}.png", dpi=120)
        plt.close(fig)


# -- Type B --------------------------------------------------------------------------

#: Type B finger (branch claude/keen-keller-s1cv0n, build_finger_type_b.py). Phalanx
#: lengths are "measured to the original joint gap"; pivot-to-pivot adds half of each
#: flex zone either side.
TYPE_B_PHALANX = (32.86, 17.76, 15.98)
TYPE_B_FLEX = {"MCP": 10.25, "PIP": 7.55, "DIP": 7.3}
#: Section heights (palmar-dorsal), mm, and the channel rule the builder uses: the
#: tendon channel (3 mm) must keep 0.8 mm of wall inside the section.
TYPE_B_SECTION_H = {"MCP": 14.0, "PIP": 12.0, "DIP": 10.0}
TYPE_B_ROM_DEG = {"MCP": 90.0, "PIP": 105.0, "DIP": 80.0}  # PLACEHOLDER (A6 used 0-105 PIP)


def type_b_link_lengths():
    f = TYPE_B_FLEX
    return (TYPE_B_PHALANX[0] + (f["MCP"] + f["PIP"]) / 2,
            TYPE_B_PHALANX[1] + (f["PIP"] + f["DIP"]) / 2,
            TYPE_B_PHALANX[2] + f["DIP"] / 2)


def _rows(name):
    with (OUT / "type_b_inputs" / f"{name}.csv").open() as f:
        return list(csv.DictReader(f))


def type_b_variants():
    """One record per variant and joint: kinematic model, stiffness, buckling load."""
    E = MODULUS_MPA
    out = []
    for r in _rows("B3_dual_leaf") + _rows("B6_multi_leaf"):
        t, w, n, L = float(r["t_mm"]), float(r["w_mm"]), int(r["n"]), float(r["flex_len_mm"])
        family = "B3" if r["variant"].startswith("B3") else "B6"
        out.append(dict(variant=r["variant"], family=family, joint=r["joint"], model="arc",
                        flex_len=L, d=float(r["tendon_moment_arm_mm"]),
                        k=float(r["k_over_E_mm3"]) * E,
                        p_cr=n * 4 * math.pi**2 * E * w * t**3 / 12 / L**2,
                        axial_area=n * w * t))
    for r in _rows("B5_crossed_strip"):
        t, w, Ls = float(r["t_mm"]), float(r["w_mm"]), float(r["strip_len_mm"])
        half = math.radians(float(r["angle"]) / 2)
        n = 4                                   # lanes A | B || B | A
        out.append(dict(variant=r["variant"], family="B5", joint=r["joint"], model="pivot",
                        flex_len=float(r["flex_len_mm"]), d=float(r["tendon_moment_arm_mm"]),
                        k=float(r["k_over_E_mm3"]) * E,
                        p_cr=n * math.cos(half) * 4 * math.pi**2 * E * w * t**3 / 12 / Ls**2,
                        axial_area=n * w * t * math.cos(half)**2 * float(r["flex_len_mm"]) / Ls))
    for r in _rows("B1_hourglass"):
        t, w, Ln = float(r["t_mm"]), float(r["w_mm"]), float(r["notch_len_mm"])
        short = float(r["notch_frac"]) < 0.75
        out.append(dict(variant=r["variant"], family="B1", joint=r["joint"],
                        model="pivot" if short else "arc",
                        flex_len=float(r["flex_len_mm"]), d=float(r["tendon_moment_arm_mm"]),
                        k=float(r["k_over_E_mm3"]) * E,
                        p_cr=2 * 4 * math.pi**2 * E * w * t**3 / 12 / Ln**2,
                        axial_area=2 * w * t))
    for r in _rows("B_lattice"):
        out.append(dict(variant=r["variant"], family="lattice", joint=r["joint"],
                        model="arc", flex_len=TYPE_B_FLEX[r["joint"]],
                        d=float(r["tendon_moment_arm_mm"]), k=float("nan"),
                        p_cr=float("nan"), axial_area=float("nan")))
    return out


def type_b_lever(model, theta, flex_len, d):
    if model == "arc":
        return arc_moment_arm(theta, flex_len, d)
    return pin_moment_arm(theta, flex_len / 2, flex_len / 2, d)


def type_b_excursion(model, theta, flex_len, d):
    if model == "arc":
        return flex_len - arc_tendon_length(theta, flex_len, d)
    return (pin_tendon_length(0.0, flex_len / 2, flex_len / 2, d)
            - pin_tendon_length(theta, flex_len / 2, flex_len / 2, d))


def run_type_b() -> list[dict]:
    tension, stroke = actuator()
    links = type_b_link_lengths()
    th_max = np.radians([TYPE_B_ROM_DEG[j] for j in ("MCP", "PIP", "DIP")])
    poses = np.stack([grasp_angles(t) for t in th_max], 1)
    load_per_N = fingertip_load_torques(poses, links, 1.0)       # N.mm per N, (pose, joint)

    by_variant: dict[str, dict] = {}
    for rec in type_b_variants():
        by_variant.setdefault(rec["variant"], {})[rec["joint"]] = rec

    rows, d_rows = [], []
    for variant, joints in by_variant.items():
        # Tendon tension needed per newton at the fingertip, worst over the grasp and
        # over the three joints (one tendon), ignoring the TPU spring for now.
        t_per_N, exc, f_servo = [], 0.0, np.inf
        for j, joint in enumerate(("MCP", "PIP", "DIP")):
            rec = joints[joint]
            r = type_b_lever(rec["model"], poses[:, j], rec["flex_len"], rec["d"])
            k = 0.0 if math.isnan(rec["k"]) else rec["k"]
            t_per_N.append(np.max(load_per_N[:, j] / r))
            # Fingertip force the servo can hold at this joint, TPU spring included.
            f_servo = min(f_servo, float(np.min((tension * r - k * poses[:, j])
                                                / load_per_N[:, j])))
            exc += float(type_b_excursion(rec["model"], th_max[j], rec["flex_len"], rec["d"]))
        t_per_N = max(t_per_N)
        p_cr = min(joints[j]["p_cr"] for j in joints)
        weakest = min(joints, key=lambda j: joints[j]["p_cr"])
        f_buckle = p_cr / t_per_N if np.isfinite(p_cr) else float("nan")
        area = joints[weakest]["axial_area"]
        rows.append({
            "variant": variant, "family": joints["PIP"]["family"],
            "kinematic_model": joints["PIP"]["model"],
            "tendon_offset_MCP_PIP_DIP_mm": "/".join(f"{joints[j]['d']:.2f}"
                                                      for j in ("MCP", "PIP", "DIP")),
            "tension_per_N_fingertip": round(float(t_per_N), 1),
            "fingertip_N_servo_limit": round(f_servo, 2),
            "buckling_load_weakest_joint_N": round(p_cr, 2) if np.isfinite(p_cr) else "",
            "weakest_joint": weakest if np.isfinite(p_cr) else "",
            "fingertip_N_buckling_limit": round(float(f_buckle), 3) if np.isfinite(f_buckle) else "",
            "axial_strain_at_servo_tension": round(tension / (MODULUS_MPA * area), 2)
            if np.isfinite(area) else "",
            "total_excursion_mm": round(exc, 2),
            "stroke_mm": round(stroke, 1),
        })

    # How the answer moves with the tendon offset d: same for every variant of a
    # family, so done once per joint and kinematic model.
    for joint, j in (("MCP", 0), ("PIP", 1), ("DIP", 2)):
        L = TYPE_B_FLEX[joint]
        d_section = TYPE_B_SECTION_H[joint] / 2 - 1.5 - 0.8
        for model in ("arc", "pivot"):
            for d in np.round(np.arange(0.5, 10.01, 0.25), 2):
                r = type_b_lever(model, poses[:, j], L, d)
                d_rows.append({
                    "joint": joint, "model": model, "offset_d_mm": d,
                    "inside_section": bool(d <= d_section + 1e-9),
                    "tension_per_N_fingertip": round(float(np.max(load_per_N[:, j] / r)), 2),
                    "fingertip_N_at_servo_tension":
                        round(tension / float(np.max(load_per_N[:, j] / r)), 2),
                    "lever_min_mm": round(float(r.min()), 3),
                    "lever_max_mm": round(float(r.max()), 3),
                    "excursion_mm": round(float(type_b_excursion(model, th_max[j], L, d)), 2)})

    write_csv(OUT / "type_b_variants.csv", rows)
    write_csv(OUT / "type_b_offset_sweep.csv", d_rows)
    _plot_type_b(rows, d_rows, th_max)
    return rows


def _plot_type_b(rows, d_rows, th_max) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, axes = plt.subplots(2, 2, figsize=(16, 11), constrained_layout=True)

    ax = axes[0, 0]
    th = np.linspace(0.01, np.radians(105), 200)
    for joint, c in (("MCP", "C0"), ("PIP", "C1"), ("DIP", "C2")):
        L = TYPE_B_FLEX[joint]
        cx, cy = arc_centre_of_rotation(th, L)
        ax.plot(np.degrees(th), cx - L / 2, c, label=f"{joint} along the axis")
        ax.plot(np.degrees(th), cy, c + "--", label=f"{joint} palmar")
    ax.set(title="Constant-curvature joints (B3, B6, B1 full notch, lattice): "
                 "drift of the centre of rotation\nfrom mid flex zone",
           xlabel="joint flexion (deg)", ylabel="drift (mm)")
    ax.legend(fontsize=8)

    ax = axes[0, 1]
    for joint, c, d in (("MCP", "C0", 3.06), ("PIP", "C1", 1.93), ("DIP", "C2", 1.06)):
        L = TYPE_B_FLEX[joint]
        ax.plot(np.degrees(th), type_b_lever("arc", th, L, d), c,
                label=f"{joint} bending (d = {d} mm)")
        ax.plot(np.degrees(th), type_b_lever("pivot", th, L, d), c + "--",
                label=f"{joint} mid pivot")
    ax.set(title="Tendon lever across the flex zone at the as-built offsets",
           xlabel="joint flexion (deg)", ylabel="lever (mm)")
    ax.legend(fontsize=8)

    ax = axes[1, 0]
    for joint, c in (("MCP", "C0"), ("PIP", "C1"), ("DIP", "C2")):
        sel = [r for r in d_rows if r["joint"] == joint and r["model"] == "arc"]
        d = [r["offset_d_mm"] for r in sel]
        ax.plot(d, [r["tension_per_N_fingertip"] for r in sel], c, label=joint)
        d_sec = TYPE_B_SECTION_H[joint] / 2 - 2.3
        ax.axvline(d_sec, color=c, ls=":", lw=1)
    ax.set(yscale="log", title="Tendon tension per newton at the fingertip vs offset d\n"
                               "(dotted: deepest offset the section allows)",
           xlabel="tendon offset from the flexure's neutral axis, d (mm)",
           ylabel="tension per N fingertip (N/N)")
    ax.legend()
    ax.grid(alpha=0.3, which="both")

    ax = axes[1, 1]
    ok = [r for r in rows if r["fingertip_N_buckling_limit"] != ""]
    ok.sort(key=lambda r: r["fingertip_N_buckling_limit"])
    y = np.arange(len(ok))
    ax.barh(y, [r["fingertip_N_buckling_limit"] for r in ok], color="C3",
            label="buckling of the weakest joint")
    ax.barh(y, [min(r["fingertip_N_servo_limit"], 0) for r in ok], color="C0")
    ax.set_yticks(y, [r["variant"] for r in ok], fontsize=6)
    ax.set(xscale="log", xlabel=f"fingertip force before buckling (N), E = {MODULUS_MPA} MPa",
           title="Type B: fingertip force each variant can take before a flexure buckles\n"
                 "(the servo alone would allow far more)")
    fig.savefig(OUT / "type_b.png", dpi=120)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tension, stroke = actuator()
    print(f"Servo: {tension:.0f} N, {stroke:.1f} mm stroke. Reference fingertip load "
          f"{FINGERTIP_FORCE_N} N.\n")
    for scenario in SCENARIOS:
        print(f"Type A, {scenario} guides:")
        for r in run_type_a(OUT / "type_a_geometry.json", scenario):
            print("  " + ", ".join(f"{k}={v}" for k, v in r.items()))
    print()
    rows = run_type_b()
    for r in sorted(rows, key=lambda r: -(r["fingertip_N_buckling_limit"] or 0))[:12]:
        print("  " + ", ".join(f"{k}={v}" for k, v in r.items()))
    print(f"\nWrote results to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
