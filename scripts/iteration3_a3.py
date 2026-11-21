"""The A3 twin strap swept on the iteration 3 index finger.

    python scripts/iteration3_a3.py          # about 25 minutes on 4 cores

The A3 sweep (scripts/a3_parameter_sweep.py: two straps, each an extensible planar
elastica clamped at both ends) was run on the old index finger and found no valid
variant: a strap clamped at both ends has to stretch as the attachment points move
apart. This repeats it on the iteration 3 finger, in the A8 study frame
(scripts/iteration3_frame.py), so the conclusion is checked rather than assumed:

* the straps leave snap-on rings like the iteration 3 A8's: clamped at y = 21.0
  (proximal ring edge) and y = 48.0 (distal ring edge), their underside on the rings'
  tops (z = 8.6), so the end centreline is at 8.6 + t/2;
* the PIP pin is measured, y = 39.18, z = 0; each variant must pass there and 0.5 mm
  either side along the finger;
* "clears the joint" is 7.7 mm from the pin (the joint's 7.4 mm envelope plus 0.3);
* the criteria are otherwise the A3 sweep's own: reach 105 degrees, restoring at every
  angle, peak strain (axial plus bending) at most 20 %.
"""

from __future__ import annotations

import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

OUT = REPO / "results" / "iteration3" / "a3"
PIN_Y = 39.18
RING_TOP = 8.6
CLAMP = (21.0, 48.0)
#: The span is 27 mm, so 13.5 mm is a half circle.
RADII = (14.0, 16.0, 20.0, 25.0, 30.0, 41.4, 50.0, 80.0, 120.0)


def configure():
    import a3_parameter_sweep as A
    A.CLAMP_Y = CLAMP
    A.AXIS_POSITIONS = ((PIN_Y, 0.0), (PIN_Y - 0.5, 0.0), (PIN_Y + 0.5, 0.0))
    A.rom.JOINT_RADIUS = 7.7
    A.RADII = RADII
    base_init = A.Strap.__init__

    def init(self, radius, thickness):
        base_init(self, radius, thickness)
        z = RING_TOP + thickness / 2          # the strap's underside on the ring's top
        self.a = np.array((CLAMP[0], z))
        self.b = np.array((CLAMP[1], z))
    if not getattr(A.Strap, "_it3", False):
        A.Strap.__init__ = init
        A.Strap._it3 = True
    A.END_Z = RING_TOP + 0.5
    return A


def simulate(job):
    A = configure()
    done = OUT / "sims" / f"R{job[0]}_t{job[1]}.json"
    if done.exists():
        return json.loads(done.read_text())
    res = A.simulate(job)
    res["top_of_arch_z_mm"] = round(RING_TOP + job[1] / 2 + A._sagitta(job[0]), 2)
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_text(json.dumps(res))
    return res


def main():
    A = configure()
    jobs = [(r, t) for r in RADII for t in A.THICKNESSES]
    with Pool(4) as pool:
        sims = pool.map(simulate, jobs, chunksize=1)
    rows = [A.combine(s, w, 20.0) for s in sims for w in A.WIDTHS]
    winner = A.best(rows)
    by_limit = {f"{lim:g}": A.best([A.combine(s, w, lim) for s in sims for w in A.WIDTHS])
                for lim in A.STRAIN_LIMITS}
    reach = A.reach_markdown(sims)
    from collections import Counter
    reasons = Counter(s["reason"] or "valid" for s in sims)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sweep.json").write_text(json.dumps(dict(
        clamp_y=CLAMP, pin=[PIN_Y, 0.0], axis_positions=A.AXIS_POSITIONS, joint_radius_mm=7.7,
        modulus_mpa=A.MODULUS, best=winner, best_by_strain_limit=by_limit,
        reasons=dict(reasons), simulations=sims, rows=rows), indent=1, default=str))
    (OUT / "reach.md").write_text(reach)
    A.plot_reach(OUT / "reach.png", sims)
    print("reasons:", dict(reasons))
    print("best:", winner)
    print(reach)


if __name__ == "__main__":
    main()
