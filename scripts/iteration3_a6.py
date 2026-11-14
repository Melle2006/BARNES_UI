"""The A6 sliding-leaf spring re-designed for the iteration 3 index finger.

    python scripts/iteration3_a6.py sweep      # curvature x thickness, travel tuned (minutes)
    python scripts/iteration3_a6.py build      # the picks as CAD, in the A8 study frame

Needs CadQuery and numba (the scratchpad "venv").

Why it is turned round
----------------------
The old A6 put the leaf's anchor on the proximal phalanx and its sliding guide on the
middle phalanx. On the iteration 3 finger that does not fit: the leaf rides about
8.6 mm from the pin (the joint fills a 7.4 mm radius at every angle), so its tip has
to slide 10-15 mm over 105 degrees, and a guide that long cannot sit on the middle
phalanx, which is fully round only from 48.5 mm and reaches the DIP pin at 60.5 mm.
The proximal phalanx has 13.5 mm of round shaft (15.5 to 29 mm) to carry it. So here
the leaf is anchored on the middle phalanx and slides in a guide on the proximal
phalanx.

The leaf's mechanics depend only on the relative turn of the two cuffs about the pin,
so the old model (scripts/make_a6_designs.py, scripts/a6_rom_check.py) is used
unchanged, in a frame turned 180 degrees about Z: y' = 54 - y, x' = -x. There its
"proximal" (anchor) cuff is the real middle-phalanx ring, at y' = 0..6 (y = 48..54),
and its "distal" (guide) cuff is the real proximal-phalanx ring, starting at
y' = 25 (y = 29) and running away from the joint. Flexion in that frame turns the
guide side with +Y' towards -Z, which is the proximal phalanx dropping relative to the
middle one: the same relative motion as the real flexion.

What changed from the old A6, and why
-------------------------------------
* Cuffs are the iteration 3 snap-on rings (7.40 mm inside, 1.2 mm wall, open on the
  palm side over +/-60 degrees), the same as the iteration 3 A8's collars.
* The PIP axis is measured, not guessed: the pin at y = 39.18 (y' = 14.82). Each design
  must pass there and 0.5 mm either side along the finger (print and fit tolerance),
  instead of at four guessed positions.
* "Clears the joint" is 7.7 mm from the pin: the joint's 7.4 mm envelope plus 0.3 mm.
* The leaf rides 8.6-9.5 mm from the pin, so its tip has to slide 12-17 mm by 105
  degrees. The ring stays on the round shaft (y = 15.5 to 29) and the guide may run on
  proximally over the phalanx's tapered neck to y = 4.5, above the MCP ball and clear
  of the index metacarpal's socket (8.3 mm high there; the guide is above 8.8 and
  rises away from the joint, and MCP flexion moves it further away): at most 24.5 mm
  of guide; designs needing more are rejected. The 21 mm first tried (to y = 8)
  rejected every geometrically valid design: they need 22.5-24.5 mm.
"""

from __future__ import annotations

import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

OUT = REPO / "results" / "iteration3" / "a6"
Y_REF = 54.0                       # y' = Y_REF - y
PIN_Y = 39.18
R_OUT = 8.6
RING = (2 * R_OUT, 2 * R_OUT, R_OUT - 0.01)
OPEN_DEG = 60.0
#: The proximal ring stops where the shaft stops being round; under the free run of the
#: guide beyond it, nothing is kept below TRIM_Z (the guide's underside is above 8.8 mm).
RING_END_Y = 15.5
TRIM_Z = 8.7
MAX_GUIDE_CUFF = 24.5              # 29.0 -> 4.5 mm: the ring stays on the round shaft (to 15.5),
                                   # the guide runs on over the tapered neck and the MCP ball; the
                                   # index metacarpal's socket (top 8.3 mm at y = 4-6) stays under it

RADII = (18.0, 22.0, 26.0, 30.0, 35.0, 45.0, 60.0, 1000.0)   # 1000 mm: flat to 0.04 mm over the span
THICKNESSES = (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
WIDTHS = (4.0, 5.0, 6.0)
#: The first sweep's best leaf was the thickest (2.0 mm) at only 10 % strain, so thicker
#: leaves are added for the curvatures that worked.
THICK_RADII = (35.0, 45.0, 60.0)
THICK_EXTRA = (2.4, 2.8, 3.2)


def configure():
    """Point the old A6 model at the iteration 3 finger (see the module docstring)."""
    import make_a6_designs as a6
    import a6_rom_check as rom
    a6.CUFF_LENGTH = 6.0
    a6.CUFF_WALL = 1.2
    a6.PP_OUTER = RING              # the anchor cuff: the real middle-phalanx ring
    a6.MP_OUTER = RING              # the guide cuff: the real proximal-phalanx ring
    a6.MP_START = Y_REF - 29.0
    a6.GUIDE_MOUTH_Y = a6.MP_START + 0.5
    a6.ANCHOR_EXIT = a6.CUFF_LENGTH + 1.0
    # cuff() and _lumen() took CUFF_LENGTH as a default argument, fixed when they were
    # defined (3 mm); without this the middle-phalanx ring came out 3 mm long.
    a6.cuff.__defaults__ = (a6.CUFF_LENGTH,)
    a6._lumen.__defaults__ = (a6.CUFF_LENGTH,)
    a6.MAX_LEAF_WIDTH = max(WIDTHS)
    a6.set_section(a6.LEAF_WIDTH, a6.LEAF_THICKNESS)
    pin = Y_REF - PIN_Y
    rom.AXIS_POSITIONS = ((pin, 0.0), (pin - 0.5, 0.0), (pin + 0.5, 0.0))
    rom.JOINT_RADIUS = 7.7
    rom.TUNE_TRAVELS = tuple(8.0 + 0.5 * i for i in range(25))       # 8 .. 20 mm
    return a6, rom


def simulate(job):
    import a6_parameter_sweep as sw
    done = OUT / "sims" / f"R{job[0]}_t{job[1]}.json"
    if done.exists():
        return json.loads(done.read_text())
    a6, rom = configure()
    sw.a6, sw.rom = a6, rom
    res = sw.simulate(job)
    if res.get("valid_geometry"):
        cuff = res["mp_cuff_length_mm"]
        if cuff > MAX_GUIDE_CUFF:
            res.update(valid_geometry=False,
                       reason=f"guide needs {cuff:g} mm, more than the {MAX_GUIDE_CUFF:g} mm available")
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_text(json.dumps(res, default=str))
    return res


def sweep():
    import a6_parameter_sweep as sw
    a6, rom = configure()
    sw.a6, sw.rom = a6, rom
    jobs = [(r, t) for r in RADII for t in THICKNESSES] + [(r, t) for r in THICK_RADII for t in THICK_EXTRA]
    with Pool(4) as pool:
        sims = pool.map(simulate, jobs, chunksize=1)
    # cached results keep their numbers; re-apply the guide-length limit as it now stands
    for res in sims:
        why = res.get("reason") or ""
        if why.startswith("guide needs") and res.get("mp_cuff_length_mm", 99) <= MAX_GUIDE_CUFF:
            res.update(valid_geometry=True, reason="")
    rows = [sw.combine(s, w, rom.STRAIN_LIMIT) for s in sims for w in WIDTHS]
    winner = sw.best(rows)
    by_limit = {}
    for lim in (15.0, 17.5, 20.0):
        p = sw.best([sw.combine(s, w, lim) for s in sims for w in WIDTHS])
        by_limit[f"{lim:g}"] = p
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sweep.json").write_text(json.dumps(dict(
        frame="y' = 54 - y (A6 model frame); pin at y' = %.2f" % (Y_REF - PIN_Y),
        axis_positions=rom.AXIS_POSITIONS, joint_radius_mm=rom.JOINT_RADIUS,
        flexion_target_deg=rom.FLEXION_TARGET, strain_limit_pct=rom.STRAIN_LIMIT,
        modulus_mpa=sw.MODULUS, best=winner, best_by_strain_limit=by_limit,
        simulations=sims, rows=rows), indent=1, default=str))
    print("best:", winner)
    for k, v in by_limit.items():
        print(k, v and {q: v[q] for q in ("radius_mm", "thickness_mm", "width_mm", "travel_mm",
                                          "mean_torque_Nmm", "torque_at_105_Nmm", "peak_strain_pct")})


def build():
    """CAD for the sweep's pick (and the pick at 17.5 % strain, for margin), in the A8
    study frame, with the rings opened on the palm side."""
    import cadquery as cq
    a6, rom = configure()
    data = json.loads((OUT / "sweep.json").read_text())
    picks = {"best": data["best"], "margin": data["best_by_strain_limit"].get("17.5")}
    out = {}
    for tag, p in picks.items():
        if not p:
            continue
        r = None if p["radius_mm"] in (None, "None", "flat") else float(p["radius_mm"])
        a6.set_section(p["width_mm"], p["thickness_mm"])
        arc, anchor_side, guide_side = a6.build(r, p["travel_mm"])
        # back to the study frame: 180 degrees about Z through y = Y_REF / 2
        loc = cq.Location(cq.Vector(0, Y_REF, 0), cq.Vector(0, 0, 1), 180)
        z_cut = -(R_OUT - 1.2) * math.cos(math.radians(OPEN_DEG))
        slot = cq.Workplane("XY").box(40, 200, 20, centered=(True, True, False)).translate((0, 0, z_cut - 20))
        mp_body = anchor_side.val().moved(loc)
        pp_body = guide_side.val().moved(loc)
        mp_body = cq.Workplane().add(mp_body).cut(slot).val()
        pp_body = cq.Workplane().add(pp_body).cut(slot).val()
        # The old model runs the guide's cuff the whole length of the guide. Here the ring
        # must stay on the round shaft (y >= 15.5): beyond it the guide runs on alone, so
        # the ring and the bottom of the guide's saddle are cut away under it, which also
        # keeps them off the MCP ball and the index metacarpal's socket.
        under = (cq.Workplane("XY").box(40, 40, 40, centered=(True, False, False))
                 .translate((0, RING_END_Y - 40, TRIM_Z - 40)))
        pp_body = cq.Workplane().add(pp_body).cut(under).val()
        stem = (f"A6_it3_R{'flat' if r is None else f'{r:g}'}_t{p['thickness_mm']:g}_w{p['width_mm']:g}"
                f"_tr{p['travel_mm']:g}")
        both = cq.Compound.makeCompound([mp_body, pp_body])
        OUT.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(cq.Workplane().add(both), str(OUT / f"{stem}.step"))
        cq.exporters.export(cq.Workplane().add(both), str(OUT / f"{stem}.stl"), tolerance=0.01,
                            angularTolerance=0.1)
        for name, body in (("mp", mp_body), ("pp", pp_body)):
            cq.exporters.export(cq.Workplane().add(body), str(OUT / f"{stem}_{name}_body.step"))
        inter = cq.Workplane().add(mp_body).intersect(cq.Workplane().add(pp_body))
        out[tag] = dict(stem=stem, pick=p, solids=[len(cq.Workplane().add(b).solids().vals()) for b in (mp_body, pp_body)],
                        bodies_overlap_mm3=round(inter.val().Volume(), 4) if inter.solids().size() else 0.0,
                        summary=a6.summary(arc, p["travel_mm"], anchor_side, guide_side))
        print(tag, json.dumps(out[tag], default=str)[:400])
    (OUT / "build.json").write_text(json.dumps(out, indent=1, default=str))


def figures():
    """Report figures: the picks on the iteration 3 bones, and their torque curves."""
    import cadquery as cq
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    a6, rom = configure()
    built = json.loads((OUT / "build.json").read_text())
    fig_dir = REPO / "docs" / "report" / "figures"

    def tris(shape):
        v, f = shape.tessellate(0.08, 0.3)
        v = np.array([(p.x, p.y, p.z) for p in v])
        return v[np.array(f)]

    bones = [s for f in ("Index_PP_study.step", "Index_MP_study.step")
             for s in cq.importers.importStep(str(REPO / "results/iteration3" / f)).solids().vals()]
    bone_tris = [tris(b) for b in bones]
    light = np.array([0.3, -0.5, 0.8]) / np.linalg.norm([0.3, -0.5, 0.8])
    for tag, info in built.items():
        parts = [cq.importers.importStep(str(OUT / f"{info['stem']}_{n}_body.step")).val() for n in ("mp", "pp")]
        fig = plt.figure(figsize=(10, 4.2))
        for k, (el, az, title) in enumerate(((22, -58, "three-quarter view"), (0, 0, "side view"))):
            ax = fig.add_subplot(1, 2, k + 1, projection="3d")
            for t, col in [(b, (0.75, 0.75, 0.75)) for b in bone_tris] + \
                          [(tris(parts[0]), (0.85, 0.45, 0.2)), (tris(parts[1]), (0.2, 0.45, 0.85))]:
                n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
                n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
                sh = 0.35 + 0.65 * np.abs(n @ light)
                ax.add_collection3d(Poly3DCollection(t, facecolors=np.clip(np.array(col)[None] * sh[:, None], 0, 1),
                                                     edgecolors="none"))
            ax.set_xlim(-10, 10)
            ax.set_ylim(0, 60)
            ax.set_zlim(-10, 18)
            ax.set_box_aspect((20, 60, 28))
            ax.view_init(el, az)
            ax.set_title(title, fontsize=9)
            ax.set_axis_off()
        fig.suptitle(f"{info['stem']}: leaf and anchor on the middle phalanx (orange), guide on the proximal "
                     "phalanx (blue)", fontsize=9)
        fig.tight_layout()
        (fig_dir / "models").mkdir(parents=True, exist_ok=True)
        fig.savefig(fig_dir / "models" / f"A6_it3_{tag}_on_bones.png", dpi=150)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for (tag, info), col in zip(built.items(), ("#1f5fa8", "#c2571a")):
        p = info["pick"]
        a6.set_section(p["width_mm"], p["thickness_mm"])
        ei = 12.0 * p["width_mm"] * p["thickness_mm"] ** 3 / 12
        for row, ls in zip(rom.evaluate(float(p["radius_mm"]), p["travel_mm"]), ("-", ":", "--")):
            ax.plot(row["_angles"], row["_torque"] * ei, ls, color=col, lw=1.6 if ls == "-" else 0.9,
                    label=(f"R{float(p['radius_mm']):g} / {p['thickness_mm']:g} × {p['width_mm']:g} mm, "
                           f"travel {p['travel_mm']:g} mm") if ls == "-" else None)
    ax.set(xlabel="PIP flexion (deg)", ylabel="restoring torque at 12 MPa (N·mm)",
           title="A6 on the iteration 3 finger (solid: measured pin; dotted, dashed: pin ±0.5 mm)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "it3_a6_torque.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    {"sweep": sweep, "build": build, "figures": figures}[sys.argv[1]]()
