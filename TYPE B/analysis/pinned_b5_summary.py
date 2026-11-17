"""Pinned B5 hybrid: summary of the pinned FEA against the free B5, and the tendon budget.

    python "TYPE B/analysis/pinned_b5_summary.py"

Reads results/PIP/<V>.json (round 1, free B5) and results/PIP_pinned/<V>[_dy<dy>].json
(the distal collar turning about a fixed pin, `fea_typeb.py --pinned --pin-dy`), and
writes results/PIP_pinned/summary.json and figures/PIP/pinned_b5.png.

Range = the first of: 20 % peak strain, or the module's two collars meeting (the FEA's
own rigid-collar check, following the pose). With the pin carrying the tendon's squeeze,
the TPU sees only the bend, so the tendon capacity is the servo's 47 N at every angle;
the joint torque left for the fingertip is

    T * lever - M_spring(angle) - mu * T * r_pin

with the lever the tendon's palmar offset (3.4 mm, deep channel) less the pin's palmar
offset, and fingertip force = that / 44.8 mm (the rig's PIP-to-hook distance). The free
B5's figures are its round-2 capacities (TYPE B/round2/fea/results) on the 3.4 mm lever.
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
R2 = HERE.parent / "round2" / "fea" / "results"
LIMIT = 0.20
SERVO_T, TENDON_Y, HOOK, MU, PIN_R = 47.0, 3.4, 44.8, 0.3, 1.0


def curve(r, key):
    a = [c["angle"] for c in r["curve"]]
    if key == "moment":
        return a, [c["moment"] for c in r["curve"]]
    return a, [f[key] for f in r["frames"]]


def strain_rom(r):
    prev = (0.0, 0.0)
    for c, f in zip(r["curve"], r["frames"]):
        if f["strain_max"] > LIMIT:
            a0, e0 = prev
            return a0 + (c["angle"] - a0) * (LIMIT - e0) / (f["strain_max"] - e0)
        prev = (c["angle"], f["strain_max"])
    return None


def row(path):
    r = json.loads(Path(path).read_text())
    srom = strain_rom(r)
    col = (r.get("collision") or {}).get("angle")
    cands = [(v, why) for v, why in ((srom, "20 % strain"), (col, "collars meet")) if v is not None]
    rom, why = min(cands) if cands else (r["curve"][-1]["angle"], "end of run")
    a, m = curve(r, "moment")
    _, e = curve(r, "strain_max")
    M = lambda x: float(np.interp(x, a, m))  # noqa: E731
    dy = r.get("pin_dy") or 0.0
    out = dict(variant=r["variant"], pinned=bool(r.get("pinned")), pin_dy_mm=dy, rom_deg=round(rom, 1),
               limited_by=why, strain_rom_deg=None if srom is None else round(srom, 1),
               collars_meet_deg=None if col is None else round(col, 1),
               M30_Nmm=round(M(30), 2), M60_Nmm=round(M(60), 2), M_at_rom_Nmm=round(M(rom), 2),
               strain_at_rom_pct=round(100 * float(np.interp(rom, a, e)), 1))
    if out["pinned"]:
        lever = TENDON_Y - abs(dy) if dy < 0 else TENDON_Y + dy
        fr = MU * SERVO_T * PIN_R
        out.update(lever_mm=round(lever, 2), tendon_capacity_N=SERVO_T,
                   fingertip_0deg_N=round((SERVO_T * lever - fr) / HOOK, 2),
                   fingertip_60deg_N=round((SERVO_T * lever - M(60) - fr) / HOOK, 2) if rom >= 60 else None)
    else:
        caps = {}
        for ang in (0, 60):
            p = R2 / f"{r['variant']}_deep_{ang}deg.json"
            if p.exists():
                caps[ang] = json.loads(p.read_text())["capacity_T"]
        out.update(lever_mm=TENDON_Y, tendon_capacity_0deg_N=caps.get(0), tendon_capacity_60deg_N=caps.get(60),
                   fingertip_0deg_N=None if 0 not in caps else round(min(caps[0], SERVO_T) * TENDON_Y / HOOK, 2),
                   fingertip_60deg_N=None if 60 not in caps else round(min(caps[60], SERVO_T) * TENDON_Y / HOOK, 2))
    return out, r


def main():
    rows, runs = [], {}
    for p in sorted(glob.glob(str(RES / "PIP_pinned" / "B5_*.json"))):
        if re.search(r"summary", p):
            continue
        o, r = row(p)
        rows.append(o)
        runs[Path(p).stem] = r
    for v in ("B5_t100_a45", "B5_t125_a45", "B5_t150_a45", "B5_t200_a45"):
        o, r = row(RES / "PIP" / f"{v}.json")
        rows.append(o)
        runs[v + "_free"] = r
    (RES / "PIP_pinned" / "summary.json").write_text(json.dumps(rows, indent=1))
    for o in rows:
        print(o)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    colours = {"B5_t125_a45": "#2a7ab9", "B5_t150_a45": "#d0702a", "B5_t200_a45": "#6a6a6a"}
    for v, col in colours.items():
        for stem, ls, lab in ((v + "_free", ":", "free"), (v, "--", "pin on crossing"),
                              (v + "_dy-0.65", "-", "pin 0.65 mm palmar"), (v + "_dy-0.5", "-", "pin 0.5 mm palmar")):
            r = runs.get(stem)
            if r is None or (stem.endswith("_dy-0.5") and (v + "_dy-0.65") in runs):
                continue
            a, m = curve(r, "moment")
            _, e = curve(r, "strain_max")
            name = v.replace("B5_", "").replace("_a45", "")
            ax[0].plot(a, m, ls, color=col, lw=1.6, label=f"{name} {lab}")
            ax[1].plot(a, 100 * np.array(e), ls, color=col, lw=1.6)
    ax[1].axhline(20, color="r", lw=0.8)
    for x in ax:      # collars meet, pin 0.65 mm palmar (the FEA's rigid-collar check)
        x.axvline(74.1, color="k", lw=0.8, alpha=0.5)
    ax[1].text(75, 2, "collars meet\n(pin 0.65 palmar)", fontsize=7)
    ax[0].set(xlabel="PIP flexion (deg)", ylabel="B5 return moment (N·mm, 12 MPa)", xlim=(0, 100), ylim=(0, 30))
    ax[1].set(xlabel="PIP flexion (deg)", ylabel="peak strain (%)", xlim=(0, 100), ylim=(0, 45))
    ax[0].legend(fontsize=7, ncol=1, frameon=False)
    for x in ax:
        x.grid(alpha=0.3)
    fig.suptitle("B5 with a hinge pin: free (dotted), pin on the strip crossing (dashed), pin moved palmar (solid)",
                 fontsize=10)
    fig.tight_layout()
    out = HERE / "figures" / "PIP" / "pinned_b5.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    print("wrote", out)

    # inset layout (narrow collars, 0.9 mm strips) against the outside layout's selection
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    cases = [("B5_t150_a45_dy-0.65", "k", "-", "outside: B5 t1.5 (1.95 mm strips), pin 0.65")]
    cols = {"150": "#9ecae1", "175": "#2a7ab9", "200": "#d0702a", "225": "#6a3d9a"}
    for stem in sorted(runs):
        m_ = re.match(r"B5i_t(\d+)_a45_dy(-[\d.]+)$", stem)
        if m_:
            t, dy = m_.groups()
            cases.append((stem, cols.get(t, "grey"), {"-0.65": "-", "-0.5": "--", "-0.8": ":"}[dy],
                          f"inset: t{int(t) / 100:.2f} (0.9 mm strips), pin {-float(dy):.2f}"))
    for stem, col, ls, lab in cases:
        r = runs.get(stem)
        if r is None:
            continue
        a, m = curve(r, "moment")
        _, e = curve(r, "strain_max")
        ax[0].plot(a, m, ls, color=col, lw=1.6, label=lab)
        ax[1].plot(a, 100 * np.array(e), ls, color=col, lw=1.6)
    ax[1].axhline(20, color="r", lw=0.8)
    ax[0].set(xlabel="PIP flexion (deg)", ylabel="B5 return moment (N·mm, 12 MPa)", xlim=(0, 100), ylim=(0, 25))
    ax[1].set(xlabel="PIP flexion (deg)", ylabel="peak strain (%)", xlim=(0, 100), ylim=(0, 45))
    ax[0].legend(fontsize=7, frameon=False)
    for x in ax:
        x.grid(alpha=0.3)
    fig.suptitle("Inset pinned B5 (14.1 mm joint) against the outside-plate selection (18.1 mm)", fontsize=10)
    fig.tight_layout()
    out = HERE / "figures" / "PIP" / "pinned_b5_inset.png"
    fig.savefig(out, dpi=160)
    print("wrote", out)


if __name__ == "__main__":
    main()
