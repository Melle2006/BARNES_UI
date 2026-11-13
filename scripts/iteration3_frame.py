"""Put the iteration 3 index phalanges into the A8 study frame, straightened.

    python scripts/iteration3_frame.py

Reads reference_parts/iteration3_hand_assembly.step and writes, to results/iteration3/:

* Index_PP_study.step and Index_MP_study.step: the two phalanges in the A8 study
  frame, with the middle phalanx turned about the PIP pin to the straight pose;
* frame.json: the transform, the flexion the assembly was saved at, and the
  joint's measured features.

The A8 study frame (as for the old index finger): origin at the centre of the MCP
ball, +Y along the proximal phalanx towards the PIP, X along the PIP pin, +Z towards
the back of the finger. The old frame put the PIP pin at y = 41.875, which is the old
MCP-PIP distance, so it is the same convention.

Which side is the back of the finger: the assembly is saved with the middle phalanx
flexed by about 25 degrees, and a finger at rest flexes towards the palm, so +Z is
the side away from the middle phalanx's lean. Straight is the pose in which the
middle phalanx's DIP bore lies on the line through the MCP ball centre and the PIP
pin, the same rule applied to the old hand assembly (checked in the output).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform  # noqa: E402
from OCP.gp import gp_Trsf  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402

import type_a_geometry as G  # noqa: E402
from barnes_ui.core.assembly.loader import load_step_assembly  # noqa: E402
from barnes_ui.core.cad.export import write_step  # noqa: E402

OUT = REPO / "results" / "iteration3"


def transformed(shape, r, t):
    tr = gp_Trsf()
    tr.SetValues(*r[0], t[0], *r[1], t[1], *r[2], t[2])
    return BRepBuilderAPI_Transform(shape, tr, True).Shape()


def centroid(shape):
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    c = g.CentreOfMass()
    return np.array([c.X(), c.Y(), c.Z()])


def frame(step, pp_name, mp_name):
    names = G.product_names(Path(step).read_text(errors="replace"))
    parts = {names.get(c.name, c.name): c.shape for c in load_step_assembly(Path(step)).parts()}
    pp, mp = parts[pp_name], parts[mp_name]
    pip, a, _ = G.shared_axis(G.cylinders(pp, 1.6), G.cylinders(mp, 1.6))
    a = np.asarray(a, float) / np.linalg.norm(a)
    ball = min((s for s in G.spheres(pp) if 4 < s[1] < 9), key=lambda s: -s[2])
    mcp = np.asarray(ball[0], float)
    v = pip - mcp
    mcp_on = mcp + (v @ a) * a * 0              # ball centre itself is the origin
    u = v - (v @ a) * a
    L = float(np.linalg.norm(u))
    u /= L
    n = np.cross(a, u)
    # DIP bore of the middle phalanx: its 1.6 mm bores off the PIP axis
    dip = None
    for c in G.cylinders(mp, 1.6):
        cp, cd = np.asarray(c[0], float), np.asarray(c[1], float)
        w = cp - pip
        off = w - (w @ a) * a
        if np.linalg.norm(off) > 5 and abs(cd @ a) > 0.99:
            dip = off
    lean = float(np.degrees(np.arctan2(dip @ n, dip @ u)))      # MP flexion towards +n
    z = -np.sign(lean) * n if abs(lean) > 1 else n              # back of the finger
    x = np.cross(u, z)                                          # right-handed X, Y, Z
    R = np.vstack([x, u, z])                                    # rows: study axes in model frame
    t = -R @ mcp
    flex = abs(lean)                                            # towards the palm
    # straighten: turn the MP about the pin (study X axis through the pin) by -flex
    pin_s = R @ pip + t
    ang = np.radians(flex) * (1 if lean > 0 else -1)
    # rotation about X that takes the MP from flexed (towards -Z) back to straight
    ca, sa = np.cos(np.radians(flex)), np.sin(np.radians(flex))
    Rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
    # flexion turns +Y towards -Z (palm); undo it: check which sign lifts the DIP bore to z = 0
    dip_s = R @ (pip + dip) + t
    for Rc in (Rx, Rx.T):
        if abs((Rc @ (dip_s - pin_s))[2]) < 1e-6 * 10 + 0.05:
            Rmp = Rc
            break
    R2 = Rmp @ R
    t2 = Rmp @ (t - pin_s) + pin_s
    return dict(pp=transformed(pp, R, t), mp=transformed(mp, R2, t2), R=R, t=t, R_mp=R2, t_mp=t2,
                pin_y=float((R @ pip + t)[1]), pin_x=float((R @ pip + t)[0]), pin_z=float((R @ pip + t)[2]),
                mcp_to_pip=L, saved_flexion_deg=flex,
                pip_to_dip=float(np.linalg.norm(dip)), ball_r=float(ball[1]))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old = frame(REPO / "reference_parts/type_a_hand_assembly.step", "Index_PP", "Index_MP")
    new = frame(REPO / "reference_parts/iteration3_hand_assembly.step", "Index PP", "Index MP")
    write_step(new["pp"], OUT / "Index_PP_study.step")
    write_step(new["mp"], OUT / "Index_MP_study.step")
    write_step(old["pp"], OUT / "old_Index_PP_study.step")
    write_step(old["mp"], OUT / "old_Index_MP_study.step")
    info = {}
    for k, f in (("iteration3", new), ("old_hand_assembly", old)):
        info[k] = {q: (v.tolist() if isinstance(v, np.ndarray) else v) for q, v in f.items()
                   if q not in ("pp", "mp")}
    (OUT / "frame.json").write_text(json.dumps(info, indent=1))
    for k in info:
        print(k, {q: round(v, 3) for q, v in info[k].items() if isinstance(v, float)})


if __name__ == "__main__":
    main()
