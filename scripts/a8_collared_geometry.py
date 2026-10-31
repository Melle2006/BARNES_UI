"""Fit collars to the printable A8 strip: the A3 fit-check collars, fused to the strip.

The printable A8 strip (results/a8_index_pip_printable) was analysed and exported as
the strip alone, its ends rigidly held where the A3 strap leaves its collars. A
printed strip needs collars to hold it on the finger, and the original A8 rings were
sized for a finger inferred from the A8 exports, which the printable study showed
does not match the real index PIP. The A3 0.8 mm fit-check strap's collars were
designed for the real Index_PP and Index_MP, and the A8 strip's ends sit exactly
where the A3 straps leave them, so those collars are taken as they are and fused to
the strip.

Frames: the A3 strap and the phalanges are in the hand assembly's frame; the strip is
also exported in that frame, so the assembly-to-study transform is fitted from the
strip's own vertices (residual ~1e-11 mm) rather than assumed.

    python scripts/a8_collared_geometry.py [--sagitta 2.75]

Writes results/a8_collared/A8_PIP_2turn_printable_w1.2_h2.4_s<s>_collared.{step,stl}
in the A8 study frame and in the hand-assembly frame, and frame.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from OCP.BRep import BRep_Tool  # noqa: E402
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse  # noqa: E402
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism  # noqa: E402
from OCP.gp import gp_Pnt, gp_Trsf, gp_Vec  # noqa: E402
from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402

from barnes_ui.core.cad.registry import load_geometry  # noqa: E402

REF = REPO / "TYPE B" / "analysis" / "a3_reference"
MODEL = REPO / "results" / "a8_index_pip_printable" / "model"
OUT = REPO / "results" / "a8_collared"
SPAN = (24.0, 53.0)       # strip ends in the study frame (y), where the A3 straps leave the collars
#: The strip's ends stop where the collars stop and float 0.05-0.4 mm above the
#: collars' dorsal walls (z 3.2-3.45 at the centre line), so on their own they never
#: touch. Each end gets a foot: its end section run back along the collar's top, and
#: a pad under it reaching FOOT_Z, inside the collar wall (z 1.9-3.4 at |x| < 1.1).
FOOT_Z = 2.6


def verts(shape):
    e, out = TopExp_Explorer(shape, TopAbs_VERTEX), []
    while e.More():
        p = BRep_Tool.Pnt_s(TopoDS.Vertex(e.Current()))
        out.append((p.X(), p.Y(), p.Z()))
        e.Next()
    return np.array(out)


def assembly_to_study():
    """Rigid transform (R, t) from the hand-assembly frame to the A8 study frame.
    Fitted between the strip exported in the assembly frame and the same strip in the
    Index_PP frame; the study frame is the Index_PP frame turned 180 deg about Y."""
    a = verts(load_geometry(MODEL / "A8_PIP_2turn_printable_w1.2_h2.4_s2.75_Assem3_frame.step").solids[0].shape)
    b = verts(load_geometry(MODEL / "A8_PIP_2turn_printable_w1.2_h2.4_s2.75_IndexPP_frame.step").solids[0].shape)
    ca, cb = a.mean(0), b.mean(0)
    u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1, 1, d]) @ u.T
    t = cb - r @ ca
    res = float(np.linalg.norm((r @ a.T).T + t - b, axis=1).max())
    flip = np.diag([-1.0, 1.0, -1.0])
    return flip @ r, flip @ t, res


def transformed(shape, r, t):
    tr = gp_Trsf()
    tr.SetValues(*r[0], t[0], *r[1], t[1], *r[2], t[2])
    return BRepBuilderAPI_Transform(shape, tr, True).Shape()


def box(x0, x1, y0, y1, z0, z1):
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def build(sagitta):
    from a8_meander_study import _printable
    import a8_meander_study as A
    from barnes_ui.core.flexure.templates.a8_meander import build_a8_meander
    A.FINGER = "index_pip"
    r, t, res = assembly_to_study()
    a3 = transformed(load_geometry(REF / "A3_PIP_twin_strap_0.8mm.step").solids[0].shape, r, t)
    big = 100.0
    prox = BRepAlgoAPI_Common(a3, box(-big, big, -big, SPAN[0], -big, big)).Shape()
    dist = BRepAlgoAPI_Common(a3, box(-big, big, SPAN[1], big, -big, big)).Shape()
    strip = build_a8_meander(_printable(2, sagitta, 2.4, 1.2, "collared", None))
    feet = []
    e = TopExp_Explorer(strip, TopAbs_FACE)
    while e.More():
        f = TopoDS.Face(e.Current())
        v = verts(f)
        for y0, col, sgn in ((SPAN[0], prox, -1), (SPAN[1], dist, 1)):
            if np.allclose(v[:, 1], y0, atol=1e-4):
                cb = bounding_box_of(col)
                run = (y0 - cb.ymin if sgn < 0 else cb.ymax - y0) - 0.2
                prism = BRepPrimAPI_MakePrism(f, gp_Vec(0, sgn * run, 0)).Shape()
                y_lo, y_hi = sorted((y0, y0 + sgn * run))
                pad = box(v[:, 0].min(), v[:, 0].max(), y_lo, y_hi, FOOT_Z, v[:, 2].min() + 0.2)
                feet.append(BRepAlgoAPI_Fuse(prism, pad).Shape())
        e.Next()
    if len(feet) != 2:
        raise RuntimeError(f"expected two strip end faces, found {len(feet)}")
    part = strip
    for piece in (feet[0], feet[1], prox, dist):
        part = BRepAlgoAPI_Fuse(part, piece).Shape()
    return part, prox, dist, strip, (r, t, res)


def bounding_box_of(shape):
    from barnes_ui.core.cad.inspect import bounding_box
    return bounding_box(shape)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sagitta", type=float, default=2.75)
    a = ap.parse_args()
    from barnes_ui.core.cad.export import write_step
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.TopAbs import TopAbs_SOLID
    part, prox, dist, strip, (r, t, res) = build(a.sagitta)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"A8_PIP_2turn_printable_w1.2_h2.4_s{a.sagitta:.2f}_collared"

    def vol(s):
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(s, g)
        return g.Mass()
    e, n = TopExp_Explorer(part, TopAbs_SOLID), 0
    while e.More():
        n += 1
        e.Next()
    # back to the assembly frame for dropping into the hand
    ri, ti = r.T, -r.T @ t
    for frame, shp in (("study_frame", part), ("Assem3_frame", transformed(part, ri, ti))):
        write_step(shp, OUT / f"{stem}_{frame}.step")
        BRepMesh_IncrementalMesh(shp, 0.01, False, 0.1, True)
        w = StlAPI_Writer()
        w.Write(shp, str(OUT / f"{stem}_{frame}.stl"))
    info = dict(sagitta=a.sagitta, solids=n, volume_mm3=vol(part), strip_mm3=vol(strip),
                proximal_collar_mm3=vol(prox), distal_collar_mm3=vol(dist), fit_residual_mm=res,
                foot_z_mm=FOOT_Z,
                R_assembly_to_study=r.tolist(), t_assembly_to_study=t.tolist())
    (OUT / f"{stem}.json").write_text(json.dumps(info, indent=1))
    print(json.dumps({k: v for k, v in info.items() if not k.startswith(("R_", "t_"))}, indent=1))
