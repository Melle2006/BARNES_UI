"""
Turn the FEA results into the selection: metrics per variant, the scoring, the
winner of each Type B family, and the figures.

    python analyse_results.py PIP

Reads results/<joint>/*.json and results/A3_benchmark_PIP.json; writes
results/summary_<joint>.csv, results/selection_<joint>.json, results/tables_<joint>.md
and figures/<joint>/*.png.
"""

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Criteria (all stated in the report)
# ---------------------------------------------------------------------------
STRAIN_LIMIT = 0.20          # design limit on peak principal strain (assumption, see report)
STRAIN_LIMITS = (0.10, 0.20, 0.30)
REF_ANGLE = 60.0             # common angle for comparing strain and stress
TENDON_Y = {"MCP": -3.06, "PIP": -1.93, "DIP": -1.06}
GRAVITY_MOMENT = {"MCP": 3.678, "PIP": 0.797, "DIP": 0.147}   # N.mm, distal chain horizontal
JOINT_TO_TIP = {"MCP": 86.6, "PIP": 44.8, "DIP": 19.6}         # mm
RETURN_FACTOR = 2.0          # restoring moment at 20 deg must be >= 2x the weight moment
TWIST_ARM = 5.0              # mm: 1 N pinch force 5 mm off the finger axis

WEIGHTS = {
    "balanced": dict(rom=0.30, strain=0.25, force=0.15, side=0.10, twist=0.05, drift=0.10, comp=0.05),
    "range-first": dict(rom=0.50, strain=0.15, force=0.10, side=0.08, twist=0.04, drift=0.08, comp=0.05),
    "durability-first": dict(rom=0.20, strain=0.45, force=0.10, side=0.08, twist=0.04, drift=0.08, comp=0.05),
    "equal": dict(rom=1 / 7, strain=1 / 7, force=1 / 7, side=1 / 7, twist=1 / 7, drift=1 / 7, comp=1 / 7),
}
# metric key, better direction, minimum spread treated as a real difference
METRICS = {"rom": ("rom_eff_deg", +1, 3.0), "strain": ("strain_at_ref", -1, 0.02),
           "force": ("tendon_force_N", -1, 0.3), "side": ("side_defl_deg", -1, 1.0),
           "twist": ("twist_deg", -1, 1.0), "drift": ("centre_drift_mm", -1, 0.2),
           "comp": ("compression_mm", -1, 0.03)}

FAMILY_LABEL = {"B_lattice": "B-lattice (bow-tie)", "B3_dual_leaf": "B3 dual leaf",
                "B6_multi_leaf": "B6 multi-leaf", "B5_crossed_strip": "B5 crossed strip",
                "B1_hourglass": "B1 hourglass"}


def thickness_of(r):
    p = r["params"]
    return p.get("t_scale", p.get("t", p.get("throat")))


def second_param(r):
    p, fam = r["params"], r["family"]
    if fam == "B_lattice":
        return "original cells" if p["crossings"] is None else f"{p['crossings']} cells"
    if fam == "B3_dual_leaf":
        return f"w {p['w']} mm" + ("" if p["taper"] == 1.0 else f", taper {p['taper']}")
    if fam == "B6_multi_leaf":
        return f"{p['leaves']} leaves" + ("" if p["taper"] == 1.0 else f", taper {p['taper']}")
    if fam == "B5_crossed_strip":
        return f"{p['angle']} deg"
    if fam == "B1_hourglass":
        return f"notch {int(p['notch_frac'] * 100)} %"
    return ""


def interp_first_cross(xs, ys, level):
    xs, ys = [0.0] + list(xs), [0.0] + list(ys)
    for i in range(1, len(xs)):
        if ys[i] >= level:
            return xs[i - 1] + (level - ys[i - 1]) * (xs[i] - xs[i - 1]) / max(ys[i] - ys[i - 1], 1e-12)
    return None


def metrics(r, joint):
    m = dict(variant=r["variant"], family=r["family"], thickness=thickness_of(r), second=second_param(r))
    if r.get("error"):
        m["error"] = r["error"].splitlines()[0]
        return m
    target = r["target_deg"]
    fr = sorted(r["frames"], key=lambda f: f["angle"])
    curve = sorted(r["curve"], key=lambda c: c["angle"])
    reached = r["completed_fraction"] * target
    ang = [f["angle"] for f in fr]
    smax = [f["strain_max"] for f in fr]
    m["reached_deg"] = reached
    for lim in STRAIN_LIMITS:
        a = interp_first_cross(ang, smax, lim)
        m[f"rom_strain{int(lim * 100)}_deg"] = a
    col = r.get("collision", {}) or {}
    m["collision_deg"] = col.get("angle")
    m["first_contact"] = col.get("first_contact")
    sc = next((f["angle"] for f in fr if f["self_contact_pairs"] > 0), None)
    m["self_contact_deg"] = sc
    limits = {"target": target, "collision": m["collision_deg"],
              f"strain {int(STRAIN_LIMIT * 100)} %": m[f"rom_strain{int(STRAIN_LIMIT * 100)}_deg"],
              "self-contact": sc, "solver stopped": reached if reached < target - 0.5 else None}
    limits = {k: v for k, v in limits.items() if v is not None}
    key = min(limits, key=limits.get)
    m["rom_eff_deg"], m["rom_limited_by"] = limits[key], key
    ca = [0.0] + [c["angle"] for c in curve]
    cm = [0.0] + [c["moment"] for c in curve]
    M = lambda a: float(np.interp(a, ca, cm))
    m["k0_Nmm_per_rad"] = cm[1] / math.radians(ca[1]) if len(ca) > 1 and ca[1] > 0 else None
    m["moment_at_rom_Nmm"] = M(m["rom_eff_deg"])
    m["moment_at_20_Nmm"] = M(20.0)
    m["strain_at_ref"] = float(np.interp(REF_ANGLE, [0] + ang, [0] + smax)) if reached >= REF_ANGLE else None
    vm = [f["vm_max"] for f in fr]
    m["vm_at_ref_MPa"] = float(np.interp(REF_ANGLE, [0] + ang, [0] + vm)) if reached >= REF_ANGLE else None
    m["strain_at_rom"] = float(np.interp(m["rom_eff_deg"], [0] + ang, [0] + smax))
    m["vm_at_rom_MPa"] = float(np.interp(m["rom_eff_deg"], [0] + ang, [0] + vm))
    cy = [f["centre_y"] for f in fr if f["angle"] <= m["rom_eff_deg"] + 1e-6] or [fr[0]["centre_y"]]
    cz = [f["centre_z"] for f in fr if f["angle"] <= m["rom_eff_deg"] + 1e-6] or [fr[0]["centre_z"]]
    m["centre_y_mm"], m["centre_z_mm"] = cy[0], cz[0]
    m["centre_drift_mm"] = float(max(math.hypot(y - cy[0], z - cz[0]) for y, z in zip(cy, cz)))
    arm = cy[0] - TENDON_Y[joint]
    m["tendon_arm_mm"] = arm
    m["tendon_force_N"] = m["moment_at_rom_Nmm"] / arm if arm > 0.05 else None
    if r.get("k_lateral"):
        m["k_lateral"], m["k_torsion"], m["k_axial"] = r["k_lateral"], r["k_torsion"], r["k_axial"]
        m["side_defl_deg"] = math.degrees(1.0 * JOINT_TO_TIP[joint] / r["k_lateral"])
        m["twist_deg"] = math.degrees(1.0 * TWIST_ARM / r["k_torsion"])
        m["compression_mm"] = (m["tendon_force_N"] or 0) / r["k_axial"]
    m["returns_ok"] = m["moment_at_20_Nmm"] >= RETURN_FACTOR * GRAVITY_MOMENT[joint]
    m["elements"] = r.get("elements")
    m["model"] = r.get("model")
    return m


def score(rows, weights):
    ok = [r for r in rows if r.get("eligible")]
    for r in ok:
        r["_s"] = 0.0
    for name, (key, sign, floor) in METRICS.items():
        vals = [r[key] for r in ok if r.get(key) is not None]
        if not vals:
            continue
        best = max(vals) if sign > 0 else min(vals)
        worst = min(vals) if sign > 0 else max(vals)
        span = max(abs(best - worst), floor)
        for r in ok:
            v = r.get(key)
            s = 0.0 if v is None else 1.0 - abs(best - v) / span
            r["_s"] += weights[name] * max(0.0, s)
    return sorted(ok, key=lambda r: -r["_s"])


def select(joint):
    rdir = HERE / "results" / joint
    raw = [json.loads(p.read_text()) for p in sorted(rdir.glob("*.json"))]
    rows = [metrics(r, joint) for r in raw]
    for m in rows:
        m["eligible"] = (not m.get("error")) and m.get("returns_ok", False) and m.get("strain_at_ref") is not None \
            and m.get("k_lateral") is not None
        if not m.get("error"):
            why = []
            if not m.get("returns_ok"):
                why.append("too weak to return the finger")
            if m.get("strain_at_ref") is None:
                why.append(f"solver stopped before {REF_ANGLE:.0f} deg")
            if m.get("k_lateral") is None:
                why.append("off-axis run missing")
            m["not_eligible_because"] = "; ".join(why)
    families = sorted({m["family"] for m in rows})
    selection = {}
    for fam in families:
        fr = [m for m in rows if m["family"] == fam]
        ranks = {}
        for wname, w in WEIGHTS.items():
            ranked = score([dict(x) for x in fr], w)
            ranks[wname] = [(x["variant"], round(x["_s"], 3)) for x in ranked]
        bal = score(fr, WEIGHTS["balanced"])
        for m in fr:
            m["score"] = round(m.get("_s", float("nan")), 3) if m.get("eligible") else None
        selection[fam] = dict(winner=bal[0]["variant"] if bal else None,
                              ranking_balanced=ranks["balanced"],
                              winners_by_weighting={k: (v[0][0] if v else None) for k, v in ranks.items()},
                              top3_by_weighting={k: v[:3] for k, v in ranks.items()})
    return rows, selection, raw


# ---------------------------------------------------------------------------
# FIGURES
# ---------------------------------------------------------------------------
def figures(joint, rows, selection, raw):
    out = HERE / "figures" / joint
    out.mkdir(parents=True, exist_ok=True)
    by = {r["variant"]: r for r in raw}
    met = {m["variant"]: m for m in rows}
    a3p = HERE / "results" / f"A3_benchmark_{joint}.json"
    a3 = json.loads(a3p.read_text()) if a3p.exists() else None
    for fam in selection:
        names = [m["variant"] for m in rows if m["family"] == fam and not m.get("error")]
        thk = sorted({met[n]["thickness"] for n in names})
        cmap = plt.get_cmap("viridis")
        sec = sorted({met[n]["second"] for n in names})
        styles = ["-", "--", ":", "-.", (0, (5, 1)), (0, (3, 1, 1, 1))]
        win = selection[fam]["winner"]
        fig, axs = plt.subplots(2, 2, figsize=(15, 11))
        for n in names:
            r, m = by[n], met[n]
            col = cmap(thk.index(m["thickness"]) / max(1, len(thk) - 1))
            ls = styles[sec.index(m["second"]) % len(styles)]
            lw, alpha = (3.2, 1.0) if n == win else (1.3, 0.75)
            c = sorted(r["curve"], key=lambda c: c["angle"])
            fr = sorted(r["frames"], key=lambda f: f["angle"])
            lab = f"{n}" + ("  << selected" if n == win else "")
            axs[0, 0].plot([0] + [p["angle"] for p in c], [0] + [p["moment"] for p in c], ls=ls, color=col, lw=lw, alpha=alpha, label=lab)
            axs[0, 1].plot([0] + [f["angle"] for f in fr], [0] + [100 * f["strain_max"] for f in fr], ls=ls, color=col, lw=lw, alpha=alpha)
            axs[1, 0].plot([0] + [f["angle"] for f in fr], [0] + [f["vm_max"] for f in fr], ls=ls, color=col, lw=lw, alpha=alpha)
            axs[1, 1].plot([0] + [100 * f["strain_max"] for f in fr], [0] + [f["vm_max"] for f in fr], ls=ls, color=col, lw=lw, alpha=alpha)
            if m.get("rom_eff_deg") is not None:
                axs[0, 0].plot(m["rom_eff_deg"], m["moment_at_rom_Nmm"], "o", color=col, ms=7 if n == win else 4)
        if a3:
            c = a3["curve"]
            fr = sorted(a3["frames"], key=lambda f: f["angle"])
            kw = dict(color="k", ls=(0, (6, 3)), lw=2.2)
            axs[0, 0].plot([0] + [p["angle"] for p in c], [0] + [p["moment"] for p in c], label="A3 0.8 mm (current part, pinned hinge)", **kw)
            axs[0, 1].plot([0] + [f["angle"] for f in fr], [0] + [100 * f["strain_max"] for f in fr], **kw)
            axs[1, 0].plot([0] + [f["angle"] for f in fr], [0] + [f["vm_max"] for f in fr], **kw)
            axs[1, 1].plot([0] + [100 * f["strain_max"] for f in fr], [0] + [f["vm_max"] for f in fr], **kw)
        cols = [met[n]["collision_deg"] for n in names if met[n].get("collision_deg")]
        for ax in (axs[0, 0], axs[0, 1], axs[1, 0]):
            if cols:
                ax.axvspan(min(cols), max(cols), color="red", alpha=0.08, label="collars touch (range across variants)")
            ax.set_xlabel("joint flexion (deg)")
            ax.grid(alpha=0.3)
        for lim in STRAIN_LIMITS:
            axs[0, 1].axhline(100 * lim, color="grey", lw=0.8, ls="--")
        axs[0, 1].axhline(100 * STRAIN_LIMIT, color="red", lw=1.2, ls="--", label=f"{int(STRAIN_LIMIT * 100)} % design limit")
        axs[0, 0].set_ylabel("moment needed (N.mm, at E = 12 MPa)")
        axs[0, 0].set_title("Moment vs flexion (joint stiffness curve)")
        axs[0, 1].set_ylabel("peak principal strain (%)")
        axs[0, 1].set_title("Peak strain vs flexion")
        axs[0, 1].legend(fontsize=8)
        axs[1, 0].set_ylabel("peak von Mises stress (MPa, at E = 12 MPa)")
        axs[1, 0].set_title("Peak stress vs flexion")
        axs[1, 1].set_xlabel("peak principal strain (%)")
        axs[1, 1].set_ylabel("peak von Mises stress (MPa)")
        axs[1, 1].set_title("Stress-strain path of the most-strained point")
        axs[1, 1].grid(alpha=0.3)
        axs[0, 0].legend(fontsize=7, ncol=2, loc="upper left")
        fig.suptitle(f"{FAMILY_LABEL.get(fam, fam)}: {joint} joint, all variants (colour = thickness, line style = "
                     f"{'cells' if fam == 'B_lattice' else 'second parameter'}; thick line = selected)", fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        fig.savefig(out / f"{fam}_curves.png", dpi=80)
        plt.close(fig)

        # parameter effects
        fig, axs = plt.subplots(1, 4, figsize=(20, 4.8))
        for s in sec:
            ns = sorted([n for n in names if met[n]["second"] == s], key=lambda n: met[n]["thickness"])
            x = [met[n]["thickness"] for n in ns]
            for ax, key, f in ((axs[0], "rom_eff_deg", 1), (axs[1], "strain_at_ref", 100),
                               (axs[2], "tendon_force_N", 1), (axs[3], "side_defl_deg", 1)):
                y = [None if met[n].get(key) is None else met[n][key] * f for n in ns]
                ax.plot(x, [np.nan if v is None else v for v in y], "o-", label=s)
        for n in names:
            if n == win:
                for ax, key, f in ((axs[0], "rom_eff_deg", 1), (axs[1], "strain_at_ref", 100),
                                   (axs[2], "tendon_force_N", 1), (axs[3], "side_defl_deg", 1)):
                    if met[n].get(key) is not None:
                        ax.plot(met[n]["thickness"], met[n][key] * f, "*", ms=18, color="red", zorder=5)
        xl = "strut thickness scale" if fam == "B_lattice" else "thickness at the PIP (mm)"
        for ax, t in zip(axs, ("usable range of motion (deg)", f"peak strain at {REF_ANGLE:.0f} deg (%)",
                               "tendon force at end of range (N)", "sideways tip deflection, 1 N (deg)")):
            ax.set_xlabel(xl)
            ax.set_title(t)
            ax.grid(alpha=0.3)
        axs[0].legend(fontsize=8)
        fig.suptitle(f"{FAMILY_LABEL.get(fam, fam)}: effect of each parameter ({joint}); red star = selected", fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        fig.savefig(out / f"{fam}_parameters.png", dpi=80)
        plt.close(fig)

    # winners overview
    fig, axs = plt.subplots(1, 3, figsize=(20, 6))
    colors = plt.get_cmap("tab10")
    for i, fam in enumerate(selection):
        n = selection[fam]["winner"]
        if not n:
            continue
        r = by[n]
        c = sorted(r["curve"], key=lambda c: c["angle"])
        fr = sorted(r["frames"], key=lambda f: f["angle"])
        lab = f"{FAMILY_LABEL.get(fam, fam)}: {n}"
        axs[0].plot([0] + [p["angle"] for p in c], [0] + [p["moment"] for p in c], color=colors(i), lw=2.2, label=lab)
        axs[1].plot([0] + [f["angle"] for f in fr], [0] + [100 * f["strain_max"] for f in fr], color=colors(i), lw=2.2)
        axs[2].plot([0] + [100 * f["strain_max"] for f in fr], [0] + [f["vm_max"] for f in fr], color=colors(i), lw=2.2)
        m = met[n]
        axs[0].plot(m["rom_eff_deg"], m["moment_at_rom_Nmm"], "o", color=colors(i), ms=8)
    if a3:
        fr = sorted(a3["frames"], key=lambda f: f["angle"])
        axs[0].plot([0] + [p["angle"] for p in a3["curve"]], [0] + [p["moment"] for p in a3["curve"]], "k--", lw=2, label="A3 0.8 mm (current)")
        axs[1].plot([0] + [f["angle"] for f in fr], [0] + [100 * f["strain_max"] for f in fr], "k--", lw=2)
        axs[2].plot([0] + [100 * f["strain_max"] for f in fr], [0] + [f["vm_max"] for f in fr], "k--", lw=2)
    axs[1].axhline(100 * STRAIN_LIMIT, color="red", ls="--", lw=1)
    for ax, (xl, yl) in zip(axs, (("flexion (deg)", "moment (N.mm, E = 12 MPa)"), ("flexion (deg)", "peak principal strain (%)"),
                                  ("peak principal strain (%)", "peak von Mises (MPa)"))):
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.grid(alpha=0.3)
    axs[0].legend(fontsize=9)
    fig.suptitle(f"Selected variant of each Type B design vs the current A3 strap ({joint}); dot = end of usable range", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out / "winners_overview.png", dpi=80)
    plt.close(fig)


def fmt(v, f="{:.2f}"):
    return "–" if v is None else (f.format(v) if isinstance(v, (int, float)) else str(v))


def tables(joint, rows, selection):
    lines = []
    for fam in selection:
        fr = sorted([m for m in rows if m["family"] == fam], key=lambda m: (-(m.get("score") or -1)))
        lines.append(f"### {FAMILY_LABEL.get(fam, fam)}\n")
        lines.append("| Variant | Range (deg) | Limited by | Strain @60° | Strain @end | Stress @end (MPa) | "
                     "k₀ (N·mm/rad) | Moment @end (N·mm) | Tendon force (N) | Side defl. 1 N (°) | Twist 1 N·5 mm (°) | "
                     "Centre drift (mm) | Score |")
        lines.append("|" + "---|" * 14)
        for m in fr:
            if m.get("error"):
                lines.append(f"| `{m['variant']}` | run failed: {m['error'][:60]} |" + " |" * 12)
                continue
            sc = fmt(m.get("score"), "{:.3f}") if m.get("eligible") else f"not eligible: {m.get('not_eligible_because')}"
            star = " **(selected)**" if m["variant"] == selection[fam]["winner"] else ""
            lines.append(
                f"| `{m['variant']}`{star} | {fmt(m['rom_eff_deg'], '{:.1f}')} | {m['rom_limited_by']} | "
                f"{fmt(m['strain_at_ref'] and 100 * m['strain_at_ref'], '{:.1f} %')} | {fmt(100 * m['strain_at_rom'], '{:.1f} %')} | "
                f"{fmt(m['vm_at_rom_MPa'])} | {fmt(m['k0_Nmm_per_rad'])} | {fmt(m['moment_at_rom_Nmm'])} | "
                f"{fmt(m['tendon_force_N'])} | {fmt(m.get('side_defl_deg'), '{:.1f}')} | {fmt(m.get('twist_deg'), '{:.1f}')} | "
                f"{fmt(m['centre_drift_mm'])} | {sc} |")
        w = selection[fam]["winners_by_weighting"]
        lines.append("")
        lines.append("Winner under each weighting: " + ", ".join(f"{k}: `{v}`" for k, v in w.items()))
        lines.append("")
    (HERE / "results" / f"tables_{joint}.md").write_text("\n".join(lines))


def main(joint):
    rows, selection, raw = select(joint)
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys and not k.startswith("_")]
    with open(HERE / "results" / f"summary_{joint}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (HERE / "results" / f"selection_{joint}.json").write_text(json.dumps(selection, indent=1))
    figures(joint, rows, selection, raw)
    tables(joint, rows, selection)
    for fam, s in selection.items():
        print(fam, "->", s["winner"], "| by weighting:", s["winners_by_weighting"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "PIP")
