"""
How far could each joint flex if the collars were relieved on the palmar side?

The FEA shows the two 0.8 mm collars meeting on the palmar side at about 76 deg
at the PIP, whatever the flexure. That is a property of the shared finger
geometry (11.4 mm tall collars, 7.55 mm apart), not of any flexure. This script
replays each saved FEA pose history with the collars left out, so the next
thing to touch is a phalanx end or a hard-stop nub: the range the joint would
have with palmar relief (chamfers) on the collars.

The FEA beyond the first collar contact did not include contact, so this is the
geometric range along the contact-free motion, a guide for redesign rather than
a simulated result.

    python relief_rom.py PIP [variants...]
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fea_typeb as T  # noqa: E402
import build_finger_type_b as B  # noqa: E402
import cadquery as cq  # noqa: E402


def relief_angle(r):
    joint = r["joint"]
    spec = T.BASE_SPEC[joint]
    c, F = B.COLLAR_LEN, spec["flex_len"]
    pn, dn = T._PHAL[joint]
    lengths = {"02_Phalanx1": B.L_PHAL1 - 2 * c, "04_Phalanx2": B.L_PHAL2 - 2 * c, "06_Phalanx3": B.L_PHAL3 - c}
    if pn is None:
        f = B.FLANGE
        prox = B._box(-f["w"] / 2, f["w"] / 2, -f["h"] / 2, f["h"] / 2, -f["t"], 0)
    else:
        prox = T._phalanx(pn).translate(cq.Vector(0, 0, -lengths[pn]))
    dist = T._phalanx(dn).translate(cq.Vector(0, 0, 2 * c + F))
    ref = (0.0, 0.0, c + F)
    hist = sorted(r["ref_disp"], key=lambda h: h["angle"])
    ang = np.array([0.0] + [h["angle"] for h in hist])
    uy = np.array([0.0] + [h["uy"] for h in hist])
    uz = np.array([0.0] + [h["uz"] for h in hist])

    def clash(a):
        return prox.intersect(T.place(dist, math.radians(a), ref, (0, np.interp(a, ang, uy), np.interp(a, ang, uz)))).Volume()

    prev = 0.0
    for a in ang[1:]:
        if clash(a) > T.CLASH_TOL:
            lo, hi = prev, a
            for _ in range(7):
                mid = (lo + hi) / 2
                lo, hi = (lo, mid) if clash(mid) > T.CLASH_TOL else (mid, hi)
            return hi
        prev = a
    return None


if __name__ == "__main__":
    joint = sys.argv[1]
    names = sys.argv[2:]
    rdir = Path(__file__).resolve().parent / "results" / joint
    out = {}
    for p in sorted(rdir.glob("*.json")):
        r = json.loads(p.read_text())
        if (names and r["variant"] not in names) or r.get("error"):
            continue
        out[r["variant"]] = dict(relief_rom_deg=relief_angle(r),
                                 reached_deg=r["completed_fraction"] * r["target_deg"])
        print(r["variant"], out[r["variant"]], flush=True)
    (rdir.parent / f"relief_rom_{joint}.json").write_text(json.dumps(out, indent=1))
