"""
Benchmark: the A3 0.8 mm twin strap from Assem3_A3_0.8_PIP_FitCheck, run through
the same flexion protocol as the Type B joints, so every Type B number has the
part you use today beside it.

The A3 is a return spring beside a pinned PIP hinge, so here the distal collar
rotates about the real hinge axis (pinned), recovered from the Ø3.2 mm pin holes
in Index_PP and Index_MP:

    direction  (0.95, -0.20, -0.23)   (lateral)
    point      the midpoint of the two Index_PP hole centres

Collars are the 3.2 mm at each end of the strap along the finger axis, the same
attachment depth the repo's A3 stiffness study used.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fea_typeb as T  # noqa: E402
import cadquery as cq  # noqa: E402

REF = Path(__file__).resolve().parent / "a3_reference"
COLLAR = 3.2
TARGET = 100.0


def hinge_frame():
    """Hinge axis from the PP pin-hole halves; finger axis from the A3 collars."""
    pp = cq.importers.importStep(str(REF / "Index_PP.step")).val()
    a3 = cq.importers.importStep(str(REF / "A3_PIP_twin_strap_0.8mm.step")).val()
    centres, hdir = [], None
    for f in pp.Faces():
        if f.geomType() != "CYLINDER":
            continue
        cyl = f._geomAdaptor().Cylinder()
        d = cyl.Axis().Direction()
        d = np.array([d.X(), d.Y(), d.Z()])
        if abs(cyl.Radius() - 1.6) < 0.01 and abs(d[0]) > 0.8:
            c = f.Center()
            if 115 < c.y < 125:
                centres.append(np.array([c.x, c.y, c.z]))
                hdir = d if d[0] > 0 else -d
    centres = np.array(centres)
    point = centres.mean(axis=0)
    span = None
    for f in a3.Faces():
        if f.geomType() == "CYLINDER":
            d = f._geomAdaptor().Cylinder().Axis().Direction()
            span = np.array([d.X(), d.Y(), d.Z()])
            break
    span = span if span[1] > 0 else -span
    X = hdir / np.linalg.norm(hdir)
    Z = span - (span @ X) * X
    Z /= np.linalg.norm(Z)
    Y = np.cross(Z, X)
    if Y[2] < 0:                 # +Y must be dorsal (+Z of the hand)
        X, Y = -X, -Y
    return point, np.vstack([X, Y, Z]), a3


def main(work, out_json, threads=4, size=0.4):
    point, Rm, a3 = hinge_frame()
    mesh = T.generate_mesh(a3.wrapped, T.MeshSettings(element_size=size, second_order=True),
                           smallest_dimension=0.8)
    mesh.nodes = (mesh.nodes - point) @ Rm.T          # into the hinge frame
    z = mesh.nodes[:, 2]
    zmin, zmax = z.min(), z.max()
    prox = np.where(z <= zmin + COLLAR)[0]
    dist = np.where(z >= zmax - COLLAR)[0]
    material = T.provisional_tpu(T.E_MPA)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / "flex.inp").write_text(T.flexion_deck(mesh, material, prox, dist, (0.0, 0.0, 0.0),
                                                  TARGET, pin_ref=True))
    env = dict(T.os.environ, OMP_NUM_THREADS=str(threads), CCX_NPROC_EQUATION_SOLVER=str(threads))
    p = subprocess.run(["ccx", "flex"], cwd=work, env=env, capture_output=True, text=True)
    (work / "flex.log").write_text(p.stdout + p.stderr)
    hist = T.parse_dat(work / "flex.dat")
    mom = hist.get(("forces", "ROT"), [])
    res = dict(variant="A3_twin_strap_0.8mm", joint="PIP", family="A3 (reference)",
               model="whole strap, pinned hinge", target_deg=TARGET, element_size=size,
               elements=int(mesh.element_count), nodes=int(mesh.node_count),
               hinge_point_hand_mm=point.tolist(), frame_rows_XYZ=Rm.tolist(),
               curve=[dict(angle=t * TARGET, moment=m[0]) for t, m in mom],
               completed_fraction=mom[-1][0] if mom else 0.0)
    res["converged_full"] = res["completed_fraction"] > 0.999
    frames = []
    fr = T.parse_frd(work / "flex.frd", mesh.node_count)
    flex_nodes = np.where((z > zmin + COLLAR + T.ROOT_EXCLUSION) & (z < zmax - COLLAR - T.ROOT_EXCLUSION))[0]
    surf = T.surface_nodes(mesh.elements)
    surf = surf[(z[surf] > zmin + COLLAR) & (z[surf] < zmax - COLLAR)]
    from scipy.spatial import cKDTree
    for t in sorted(fr):
        d = fr[t]
        if "TOSTRAIN" not in d:
            continue
        E, S = d["TOSTRAIN"][flex_nodes], d["STRESS"][flex_nodes]
        ok = ~np.isnan(E).any(axis=1)
        lam = T.principal(E[ok])
        smax = np.sqrt(np.clip(1 + 2 * lam[:, 2], 1e-9, None)) - 1
        smin = np.sqrt(np.clip(1 + 2 * lam[:, 0], 1e-9, None)) - 1
        vm = T.von_mises(S[ok])
        U = d["DISP"]
        p0 = mesh.nodes[surf]          # the deck is written in the hinge frame, so U is too
        pos = p0 + U[surf]
        pairs = cKDTree(pos).query_pairs(0.10, output_type="ndarray")
        contact = int((np.linalg.norm(p0[pairs[:, 0]] - p0[pairs[:, 1]], axis=1) > 1.5).sum()) if len(pairs) else 0
        frames.append(dict(angle=t * TARGET, strain_max=float(smax.max()),
                           strain_p99=float(np.percentile(smax, 99.5)), strain_min=float(smin.min()),
                           vm_max=float(vm.max()), vm_p99=float(np.percentile(vm, 99.5)),
                           self_contact_pairs=contact))
    res["frames"] = frames
    res["ccx_tail"] = p.stdout[-600:]
    Path(out_json).write_text(json.dumps(res, indent=1))
    (work / "flex.frd").unlink(missing_ok=True)
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
    print(r["elements"], r["completed_fraction"])
    for f in r["frames"]:
        print({k: round(v, 4) for k, v in f.items()})
