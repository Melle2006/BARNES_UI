"""Render the parts the print-decision report discusses, as shaded PNGs.

    python scripts/render_models.py

Writes docs/report/figures/models/<name>.png. Uses matplotlib only (no display,
no OpenGL), so it runs headless. STEP-only parts are tessellated first.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "report" / "figures" / "models"
sys.path.insert(0, str(REPO / "src"))

TB = "TYPE B"
#: name -> (file, title, view elevation, view azimuth)
MODELS = {
    "A3_twin_strap": ("reference_parts/A3_PIP_twin_strap_1.0mm.step", "A3 twin strap, 1.0 mm (current part)", 25, -60),
    "A6_R28_t1.4": ("A6 designs/A6_PIP_SlidingLeaf_R28_t1.4_w6.STL", "A6 sliding leaf R28 / 1.4 / 6 mm", 15, -35),
    "A6_R32_t1.8": ("A6 designs/A6_PIP_SlidingLeaf_R32_t1.8_w6.STL", "A6 sliding leaf R32 / 1.8 / 6 mm", 15, -35),
    "A8_strip_s2.75": ("results/a8_index_pip_printable/model/A8_PIP_2turn_printable_w1.2_h2.4_s2.75_IndexPP_frame.stl",
                       "A8 2-turn printable strip, sagitta 2.75 mm (strip only)", 35, -60),
    "A8_collared_s2.75": ("results/a8_collared/A8_PIP_2turn_printable_w1.2_h2.4_s2.75_collared_study_frame.stl",
                          "A8 strip with A3 fit-check collars, sagitta 2.75 mm", 30, -55),
    "A8_original_export": ("results/a8_meander_study/input_step/A8_PIP_Meander_3turn_2mm.STEP",
                           "Original A8 export (3-turn, 2 mm) with its rings", 30, -55),
    "B5_t200_a45_deep": (f"{TB}/round2/deep_offset/B5_t200_a45_deep/03_PIP_module.stl", "B5 crossed strip t2.0 / 45°, deep tendon (PIP module)", 20, -50),
    "B5_t150_a45": (f"{TB}/B5_crossed_strip/B5_t150_a45/03_PIP_module.stl", "B5 crossed strip t1.5 / 45° (PIP module)", 20, -50),
    "B3_t150_w30": (f"{TB}/B3_dual_leaf/B3_t150_w30/03_PIP_module.stl", "B3 dual leaf t1.5 / w3.0 (PIP module)", 20, -50),
    "B6_n4_t150_taper15": (f"{TB}/B6_multi_leaf/B6_n4_t150_taper15/03_PIP_module.stl", "B6 multi-leaf, 4 leaves t1.5, taper 1.5 (PIP module)", 20, -50),
    "B1_t100_notch100": (f"{TB}/B1_hourglass/B1_t100_notch100/03_PIP_module.stl", "B1 hourglass t1.0, full notch (PIP module)", 20, -50),
    "B1_t200_notch050": (f"{TB}/B1_hourglass/B1_t200_notch050/03_PIP_module.stl", "B1 hourglass t2.0, half notch (PIP module)", 20, -50),
    "B_T090_X3": (f"{TB}/B_lattice/B_T090_X3/03_PIP_module.stl", "Bow-tie lattice, struts ×0.9, 3 cells (PIP module)", 20, -50),
    "B4_t100_a60_deep": (f"{TB}/round2/deep_offset/B4_t100_a60_deep/03_PIP_module.stl", "B4 rolling contact t1.0 / 60°, deep tendon (PIP module)", 20, -50),
    "B8_y00_r150": (f"{TB}/round2/B8_y00_r150/03_PIP_module.stl", "B8 knuckle-in-cup, central, r1.5 (PIP module)", 20, -50),
    "B8_y20_r125_deep": (f"{TB}/round2/deep_offset/B8_y20_r125_deep/03_PIP_module.stl", "B8 knuckle 2 mm dorsal, r1.25, deep (PIP module)", 20, -50),
    "B9_n150": (f"{TB}/round2/B9_n150/03_PIP_module.stl", "B9 compression strut, neck 1.5 (PIP module)", 20, -50),
    "test_rig": (f"{TB}/round2/test_rig/rig_assembly.step", "Single-joint test rig (assembly)", 25, -45),
}


def load(path: Path) -> trimesh.Trimesh:
    if path.suffix.lower() in (".stl",):
        m = trimesh.load(path, force="mesh")
    else:
        from barnes_ui.core.cad.registry import load_geometry
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound
        model = load_geometry(path)
        comp, bld = TopoDS_Compound(), BRep_Builder()
        bld.MakeCompound(comp)
        for s in model.solids:
            bld.Add(comp, s.shape)
        BRepMesh_IncrementalMesh(comp, 0.05, False, 0.3, True)
        tmp = Path(tempfile.mkdtemp()) / "m.stl"
        StlAPI_Writer().Write(comp, str(tmp))
        m = trimesh.load(tmp, force="mesh")
    return m


def render(mesh: trimesh.Trimesh, title: str, elev: float, azim: float, out: Path, max_faces=60000):
    if len(mesh.faces) > max_faces:
        idx = np.random.default_rng(0).choice(len(mesh.faces), max_faces, replace=False)
        mesh = trimesh.Trimesh(mesh.vertices, mesh.faces[idx], process=False)
    v = mesh.vertices - mesh.bounds.mean(axis=0)
    tris = v[mesh.faces]
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    e, a = np.radians(elev), np.radians(azim)
    light = np.array([np.cos(e) * np.cos(a + 0.6), np.cos(e) * np.sin(a + 0.6), np.sin(e) + 0.4])
    light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.abs(n @ light)
    base = np.array([0.33, 0.52, 0.78])
    colours = np.clip(base[None, :] * shade[:, None] + 0.12 * shade[:, None], 0, 1)
    fig = plt.figure(figsize=(5.2, 3.6))
    ax = fig.add_subplot(111, projection="3d")
    ax.add_collection3d(Poly3DCollection(tris, facecolors=colours, edgecolors="none", linewidths=0))
    r = np.abs(v).max(axis=0)
    ax.set_xlim(-r[0], r[0])
    ax.set_ylim(-r[1], r[1])
    ax.set_zlim(-r[2], r[2])
    ax.set_box_aspect(2 * r)
    ax.view_init(elev, azim)
    ax.set_axis_off()
    ext = mesh.bounds[1] - mesh.bounds[0]
    ax.set_title(f"{title}\n{ext[0]:.1f} × {ext[1]:.1f} × {ext[2]:.1f} mm", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)


def main(names=None):
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (rel, title, elev, azim) in MODELS.items():
        if names and name not in names:
            continue
        p = REPO / rel
        if not p.exists():
            print("missing", rel)
            continue
        render(load(p), title, elev, azim, OUT / f"{name}.png")
        print("rendered", name)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
