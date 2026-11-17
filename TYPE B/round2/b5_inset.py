"""Inset pinned B5: a PIP module narrowed so the PLA hinge plates fit inside the finger.

    python "TYPE B/round2/b5_inset.py" [t]          # strip thickness, default 1.75

The pinned B5 (b5_pinned.py, layout "outside") puts its hinge plates outboard of the
module's 13.4 mm collars, so the joint is 18-19 mm wide on a 14 mm finger. Here the
collars are cut down to 9.2 mm wide (|x| <= 4.6) and the crossed strips are laid out in
the narrower band that leaves (TYPE B/build_flexure_families.py, family B5i: lanes
1.9-4.3 mm from the centreline, so each strip is 0.9 mm wide instead of 1.95 mm, and a
thicker strip makes up the stiffness). The collars still seat: they are 11.4 mm tall,
the socket 9.6 mm, so they bear on its dorsal and palmar rims. The tabs, retention pins,
deep tendon channel and sensor channel are the round-2 deep build's, unchanged, so the
module goes into the same deep phalanges.

Writes TYPE B/round2/pinned_b5_inset/B5i_t<t>_a45_deep/03_PIP_module.{step,stl}; the
phalanges with inset plates come from `b5_pinned.py --layout inset --module <that folder>`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
TYPEB = HERE.parent
sys.path[:0] = [str(TYPEB), str(HERE)]
import build_finger_type_b as B  # noqa: E402
import build_flexure_families as FF  # noqa: E402

DEEP = {"MCP": 4.4, "PIP": 3.4, "DIP": 2.3}      # build_round2.py's deep offsets


def build(t: float):
    name = f"B5i_t{FF.tag(t)}_a45"
    fx = FF.crossed_strips_inset(t, 45)
    parts, z, rep = B.build_finger(flexure=fx, verbose=False, tendon_offsets=DEEP)
    mod = parts["03_PIP_module"]
    e, c, F = B.PIP["end_len"], B.COLLAR_LEN, B.PIP["flex_len"]
    h = FF.INSET_COLLAR_HALF
    cuts = []
    for z0 in (e, e + c + F):                     # the two collars
        for sx in (1, -1):
            x0 = h if sx > 0 else -h - 20
            cuts.append(cq.Workplane("XY").box(20, 40, c, centered=False).translate((x0, -20, z0)).val())
    mod = mod.cut(B.fuse(cuts)).clean()
    out = HERE / "pinned_b5_inset" / f"{name}_deep"
    out.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(cq.Workplane().add(mod), str(out / "03_PIP_module.step"))
    cq.exporters.export(cq.Workplane().add(mod), str(out / "03_PIP_module.stl"), tolerance=0.01, angularTolerance=0.1)
    info = rep["lattice"]["PIP"]
    bb = mod.BoundingBox()
    print(name, "valid", mod.isValid(), "solids", len(mod.Solids()), "x", round(bb.xmin, 2), round(bb.xmax, 2),
          "strip", {k: round(v, 3) if isinstance(v, float) else v for k, v in info.items()})
    return out


if __name__ == "__main__":
    build(float(sys.argv[1]) if len(sys.argv) > 1 else 1.75)
