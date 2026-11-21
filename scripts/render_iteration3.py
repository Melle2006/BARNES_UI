"""Figures for the iteration 3 A8 re-fit: the part on the bones, and the torque curves.

    python scripts/render_iteration3.py [stem ...]

Writes docs/report/figures/models/A8_it3_on_bones.png (the first stem given, or the
selected case) and docs/report/figures/it3_torque.png (every finished case).
"""

from __future__ import annotations

import json
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
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
IT3 = REPO / "results" / "iteration3"
FIG = REPO / "docs" / "report" / "figures"


def tm(shape):
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer
    BRepMesh_IncrementalMesh(shape, 0.05, False, 0.3, True)
    f = Path(tempfile.mkdtemp()) / "m.stl"
    StlAPI_Writer().Write(shape, str(f))
    return trimesh.load(f)


def on_bones(stem, out):
    from barnes_ui.core.cad.registry import load_geometry
    part = trimesh.load(IT3 / "a8" / f"{stem}.stl")
    bones = [tm(s.shape) for f in ("Index_PP_study.step", "Index_MP_study.step")
             for s in load_geometry(IT3 / f).solids]
    fig = plt.figure(figsize=(10, 4.2))
    light = np.array([0.3, -0.5, 0.8]) / np.linalg.norm([0.3, -0.5, 0.8])
    for k, (el, az, title) in enumerate(((22, -58, "three-quarter view"), (0, 0, "side view"))):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        for m, col in [(b, (0.75, 0.75, 0.75)) for b in bones] + [(part, (0.2, 0.45, 0.85))]:
            tri = m.vertices[m.faces]
            sh = 0.35 + 0.65 * np.abs(m.face_normals @ light)
            ax.add_collection3d(Poly3DCollection(tri, facecolors=np.clip(np.array(col)[None] * sh[:, None], 0, 1),
                                                 edgecolors="none"))
        ax.set_xlim(-10, 10)
        ax.set_ylim(10, 60)
        ax.set_zlim(-10, 12)
        ax.set_box_aspect((20, 50, 22))
        ax.view_init(el, az)
        ax.set_title(title, fontsize=9)
        ax.set_axis_off()
    fig.suptitle(f"{stem}: collars clipped on the iteration 3 Index PP and MP (grey)", fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def torque_curves(out):
    """Every finished case; those inside 20 % strain to 90 deg in colour, the rest grey,
    each grey curve marked where it first reaches 20 %."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("narrative", REPO / "docs/report/narrative.py")
    N = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(N)
    k = 12 / 19.3
    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    colours = iter(["#1f5fa8", "#c2571a", "#2a8a4a", "#7a3fa0"])
    for c in N.it3_cases(REPO):
        if not c.get("curve"):
            continue
        a, t = np.array(c["curve"]["angle_deg"]), np.array(c["curve"]["torque_n_mm"]) * k
        if c["ok"]:
            ax.plot(a, t, lw=2.2, color=next(colours), label=N.it3_name(c) + " (passes)")
        else:
            ax.plot(a, t, lw=0.9, color="#9aa3ad")
            fh = sorted((float(tt) * 100, v) for tt, v in c["field_history"].items() if "peak_strain_all" in v)
            hit = [x for x, v in fh if max(v["peak_strain_interior"], v.get("peak_strain_junction") or 0,
                                           v.get("peak_strain_collars") or 0) >= 0.2]
            if hit:
                ax.plot(hit[0], np.interp(hit[0], a, t), "x", color="#c0392b", ms=6, mew=1.5)
    ax.plot([], [], color="#9aa3ad", lw=0.9, label="cases over 20 % strain (× marks where)")
    ax.set(xlabel="PIP flexion (deg)", ylabel="restoring torque at 12 MPa (N·mm)",
           title="A8 on the iteration 3 finger: torque against flexion, every case")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    (FIG / "models").mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        on_bones(sys.argv[1], FIG / "models" / "A8_it3_on_bones.png")
    torque_curves(FIG / "it3_torque.png")
