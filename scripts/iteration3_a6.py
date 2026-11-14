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
  proximally over the phalanx's tapered neck to y = 8, clear of the 7.25 mm MCP ball:
  at most 21 mm of guide; designs needing more are rejected.
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
MAX_GUIDE_CUFF = 21.0              # 29.0 -> 8.0 mm: the ring stays on the round shaft (to 15.5),
                                   # the guide runs on over the tapered neck, clear of the MCP ball

RADII = (18.0, 22.0, 26.0, 30.0, 35.0, 45.0, 60.0, None)
THICKNESSES = (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
WIDTHS = (4.0, 5.0, 6.0)


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
    jobs = [(r, t) for r in RADII for t in THICKNESSES]
    with Pool(4) as pool:
        sims = pool.map(simulate, jobs, chunksize=1)
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


if __name__ == "__main__":
    {"sweep": sweep, "build": build}[sys.argv[1]]()
