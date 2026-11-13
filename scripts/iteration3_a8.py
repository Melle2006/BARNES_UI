"""The A8 strip with new collars for the iteration 3 index finger.

    python scripts/iteration3_a8.py --height 2.4 --sagitta 0.75   # writes the part

The iteration 3 phalanges (reference_parts/iteration3_hand_assembly.step) are round
shafts of 14.8 mm diameter, so the A3 fit-check collars the old A8 used no longer
fit. scripts/iteration3_frame.py puts them in the A8 study frame (origin at the MCP
ball, +Y along the proximal phalanx, +Z the back of the finger, PIP pin along X at
y = 39.18) with the middle phalanx straight; this script designs the collars there.

The collars
-----------
Each is a ring of the shaft's own radius (7.40 mm inside, so it grips without a
gap), 1.2 mm wall, open across the palm side over +/-60 degrees so it clips on:
the 12.8 mm opening is 2 mm narrower than the shaft, 1 mm of snap each side.

* Proximal collar, on the proximal phalanx at y = 15.5 to 21.0: the shaft is fully
  round there (the cross-slots at y = 21.5 to 23 and the joint relief beyond
  y = 30 are avoided).
* Distal collar, on the middle phalanx at y = 48.0 to 54.0: the middle phalanx is
  only its 6 mm tongue before y = 47, and fully round from 48.5. Its dorsal side is
  chamfered beyond y = 50 (relief for the distal phalanx), so the collar's inner face
  sits on the bone round its sides and palm side the whole way and on its back for
  the first 2 mm; it is held where it touches.

The strip
---------
The printable 2-turn strip of the old study (1.2 mm true width, the 2-turn sine plan
of 4.4 mm amplitude), running from the proximal collar's distal edge (y = 21.0) to
the distal collar's proximal edge (y = 48.0), its underside on the collars' tops
(z = 8.6). The joint occupies a radius of 7.4 mm about the pin at every angle, so a
flat strip already clears it by 1.2 mm at rest; the sagitta adds arch on top. Each
end gets a foot: its end section run back along the collar's top, with a pad into
the collar wall, as for the old collared strip.

The finger the strip can touch
------------------------------
The real phalanges near the joint, the whole section (the proximal phalanx from the
proximal collar to the cheek tips, the middle phalanx from its tongue to the distal
collar), the proximal one fixed, the middle one turning with the distal collar. Not
idealised cams: where the shaft meets the r9.4 joint rounds the surface has a crease,
and the strip rides over it. The whole section, not just the back: once the joint
passes about 50 degrees, the part of the tongue and the cheek rounds that faces the
strip is what was underneath at rest. A first set of runs cut the bones at z > 2.5
and the strip fell through that gap to the pin; those runs were discarded.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism  # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec  # noqa: E402
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402

from barnes_ui.core.cad.registry import load_geometry  # noqa: E402

IT3 = REPO / "results" / "iteration3"
OUT = IT3 / "a8"
PIN_Y = 39.18
R_IN = 7.40
WALL = 1.2
R_OUT = R_IN + WALL
OPEN_DEG = 60.0                      # half-angle of the palm-side opening
PROX_BAND = (15.5, 21.0)
DIST_BAND = (48.0, 54.0)
SPAN = (PROX_BAND[1], DIST_BAND[0])
AMPLITUDE = 4.4
WIDTH = 1.2
CAP_Z = -12.0                        # the whole bone near the joint, every z
CAP_X = 7.6


def box(x0, x1, y0, y1, z0, z1):
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def ycyl(r, y0, y1):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, y0, 0), gp_Dir(0, 1, 0)), r, y1 - y0).Shape()


def solids(shape):
    e, out = TopExp_Explorer(shape, TopAbs_SOLID), []
    while e.More():
        out.append(TopoDS.Solid(e.Current()))
        e.Next()
    return out


def collar(y0, y1):
    ring = BRepAlgoAPI_Cut(ycyl(R_OUT, y0, y1), ycyl(R_IN, y0 - 1, y1 + 1)).Shape()
    z_cut = -R_IN * math.cos(math.radians(OPEN_DEG))
    return BRepAlgoAPI_Cut(ring, box(-20, 20, y0 - 1, y1 + 1, -20, z_cut)).Shape()


def bones():
    pp = [s.shape for s in load_geometry(IT3 / "Index_PP_study.step").solids]
    mp = [s.shape for s in load_geometry(IT3 / "Index_MP_study.step").solids]
    return pp, mp


def caps(pp, mp):
    """The bone the strip can touch near the joint: (name, shape, moves_with, cut box)."""
    out = []
    for name, parts, (y0, y1), moves in (("pp", pp, (SPAN[0] + 0.2, PIN_Y + 4.5), "proximal"),
                                         ("mp", mp, (PIN_Y - 4.5, SPAN[1] - 0.2), "distal")):
        cut = dict(x=CAP_X, y=(y0, y1), z=(CAP_Z, 12.0))
        k = 0
        for p in parts:
            c = BRepAlgoAPI_Common(p, box(-CAP_X, CAP_X, y0, y1, CAP_Z, 12.0)).Shape()
            for s in solids(c):
                out.append(dict(name=f"{name}cap{k}", shape=s, moves_with=moves, cut=cut))
                k += 1
    return out


def strip_params(height, sagitta, label):
    from barnes_ui.core.flexure.templates.a8_meander import A8MeanderParameters, sine_plan
    zc = R_OUT + height / 2.0
    return A8MeanderParameters(plan=sine_plan(2, AMPLITUDE), sagitta=sagitta, n_turns=2,
                               height_z=height, true_width=WIDTH, y_start=SPAN[0], y_end=SPAN[1],
                               z_start=zc, z_end=zc, stations_per_lobe=40, label=label)


def build(height, sagitta, label="it3"):
    from barnes_ui.core.flexure.templates.a8_meander import build_a8_meander
    from barnes_ui.core.cad.inspect import bounding_box
    params = strip_params(height, sagitta, label)
    strip = build_a8_meander(params)
    prox, dist = collar(*PROX_BAND), collar(*DIST_BAND)
    feet = []
    e = TopExp_Explorer(strip, TopAbs_FACE)
    while e.More():
        f = TopoDS.Face(e.Current())
        bb = bounding_box(f)
        for y0, band, sgn in ((SPAN[0], PROX_BAND, -1), (SPAN[1], DIST_BAND, 1)):
            if abs(bb.ymin - y0) < 1e-4 and abs(bb.ymax - y0) < 1e-4:
                run = (band[1] - band[0]) - 0.2
                prism = BRepPrimAPI_MakePrism(f, gp_Vec(0, sgn * run, 0)).Shape()
                ylo, yhi = sorted((y0, y0 + sgn * run))
                pad = box(bb.xmin, bb.xmax, ylo, yhi, R_IN + 0.4, bb.zmin + 0.2)
                feet.append(BRepAlgoAPI_Fuse(prism, pad).Shape())
        e.Next()
    if len(feet) != 2:
        raise RuntimeError(f"expected two strip end faces, found {len(feet)}")
    part = strip
    for piece in feet + [prox, dist]:
        part = BRepAlgoAPI_Fuse(part, piece).Shape()
    n = len(solids(part))
    if n != 1:
        raise RuntimeError(f"collared strip is {n} solids, not one")
    return part, prox, dist, strip, params


def bone_points(parts, spacing=0.05):
    """Points on the bone's surface at about ``spacing`` mm, for the collar hold."""
    import tempfile
    import trimesh
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer
    pts = []
    for p in parts:
        BRepMesh_IncrementalMesh(p, 0.01, False, 0.05, True)
        f = Path(tempfile.mkdtemp()) / "b.stl"
        StlAPI_Writer().Write(p, str(f))
        tri = trimesh.load(f)
        pts.append(trimesh.sample.sample_surface_even(tri, int(tri.area / spacing ** 2))[0])
    return np.vstack(pts)


def flexion_clash(dist_part, pp, angles=range(0, 121, 2)):
    """First flexion at which the distal collar, turned about the pin with the middle
    phalanx, would touch the proximal phalanx (rigid check, no contact in the FEA)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Trsf
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    for a in angles:
        tr = gp_Trsf()
        tr.SetRotation(gp_Ax1(gp_Pnt(0, PIN_Y, 0), gp_Dir(1, 0, 0)), -math.radians(a))
        moved = BRepBuilderAPI_Transform(dist_part, tr, True).Shape()
        for p in pp:
            g = GProp_GProps()
            BRepGProp.VolumeProperties_s(BRepAlgoAPI_Common(moved, p).Shape(), g)
            if g.Mass() > 0.05:
                return a
    return None


def export(part, stem):
    from barnes_ui.core.cad.export import write_step
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer
    OUT.mkdir(parents=True, exist_ok=True)
    write_step(part, OUT / f"{stem}.step")
    BRepMesh_IncrementalMesh(part, 0.01, False, 0.1, True)
    StlAPI_Writer().Write(part, str(OUT / f"{stem}.stl"))


def stem_for(height, sagitta):
    return f"A8_it3_2turn_w{WIDTH:.1f}_h{height:.1f}_s{sagitta:.2f}_collared"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--height", type=float, default=2.4)
    ap.add_argument("--sagitta", type=float, default=0.75)
    a = ap.parse_args()
    part, prox, dist, strip, params = build(a.height, a.sagitta)
    stem = stem_for(a.height, a.sagitta)
    export(part, stem)
    pp, mp = bones()
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp

    def vol(s):
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(s, g)
        return g.Mass()
    info = dict(height=a.height, sagitta=a.sagitta, volume_mm3=vol(part), strip_mm3=vol(strip),
                collar_mm3=[vol(prox), vol(dist)], span=SPAN, bands=[PROX_BAND, DIST_BAND],
                r_in=R_IN, wall=WALL, opening_half_deg=OPEN_DEG,
                distal_collar_meets_pp_at_deg=flexion_clash(dist, pp))
    (OUT / f"{stem}.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))
