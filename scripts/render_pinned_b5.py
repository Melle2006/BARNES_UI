"""Render the pinned B5 hybrid at the PIP: straight and flexed, parts in colour.

    python scripts/render_pinned_b5.py       # needs CadQuery (venv) for the STEP parts

Writes docs/report/figures/models/B5_pinned_{straight,flexed}.png. The flexed view is
the PLA parts turned rigidly about the pin (the TPU module is drawn straight, as a
ghost, since its bent shape comes from the FEA, not the CAD).
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "TYPE B" / "round2"))
import b5_pinned as BP  # noqa: E402

OUT = REPO / "docs" / "report" / "figures" / "models"


def mesh_of(shape, tol=0.05):
    import cadquery as cq
    import tempfile
    p = Path(tempfile.mkdtemp()) / "m.stl"
    cq.exporters.export(cq.Workplane().add(shape), str(p), tolerance=tol, angularTolerance=0.2)
    return trimesh.load(p, force="mesh")


def draw(parts, title, out, elev=18, azim=-62):
    fig = plt.figure(figsize=(6.4, 4.4))
    ax = fig.add_subplot(111, projection="3d")
    allv = np.vstack([m.vertices for m, _, _ in parts])
    ctr = (allv.max(0) + allv.min(0)) / 2
    e, a = np.radians(elev), np.radians(azim)
    light = np.array([np.cos(e) * np.cos(a + 0.6), np.cos(e) * np.sin(a + 0.6), np.sin(e) + 0.4])
    light /= np.linalg.norm(light)
    for m, base, alpha in parts:
        if len(m.faces) > 50000:
            idx = np.random.default_rng(0).choice(len(m.faces), 50000, replace=False)
            m = trimesh.Trimesh(m.vertices, m.faces[idx], process=False)
        tris = m.vertices[m.faces] - ctr
        n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        shade = 0.35 + 0.65 * np.abs(n @ light)
        col = np.clip(np.array(base)[None, :] * shade[:, None] + 0.1 * shade[:, None], 0, 1)
        ax.add_collection3d(Poly3DCollection(tris, facecolors=np.c_[col, np.full(len(col), alpha)],
                                             edgecolors="none", linewidths=0))
    r = np.abs(allv - ctr).max(0)
    ax.set_xlim(-r[0], r[0]); ax.set_ylim(-r[1], r[1]); ax.set_zlim(-r[2], r[2])  # noqa: E702
    ax.set_box_aspect(2 * r)
    ax.view_init(elev, azim)
    ax.set_axis_off()
    ax.set_title(title, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)


def main():
    import cadquery as cq
    geo = BP.build(BP.HERE / "deep_offset" / "B5_t150_a45_deep")
    module, dz = BP.place(geo)
    p2 = geo["P2"].moved(cq.Location(cq.Vector(0, 0, dz)))
    # show only the joint end of each phalanx: crop to 22 mm either side of the pin
    zp = geo["pin1"]
    crop = cq.Workplane("XY").box(60, 60, 44).translate((0, 0, zp)).val()
    P1, P2, MOD = (mesh_of(s.intersect(crop)) for s in (geo["P1"], p2, module))
    pla1, pla2, tpu = (0.85, 0.85, 0.88), (0.95, 0.75, 0.35), (0.33, 0.52, 0.78)
    OUT.mkdir(parents=True, exist_ok=True)
    draw([(P1, pla1, 1.0), (MOD, tpu, 1.0), (P2, pla2, 1.0)],
         "Pinned B5 at the PIP: proximal phalanx (grey), B5 t1.5 module (blue), middle phalanx (orange);\n"
         "Ø2 pins through the overlapping plates, 0.65 mm palmar of the strip crossing",
         OUT / "B5_pinned_straight.png")
    ang = 70.0
    T = trimesh.transformations.rotation_matrix(np.radians(ang), [1, 0, 0], [0, geo["dy"], zp])
    P2f = P2.copy()
    P2f.apply_transform(T)
    draw([(P1, pla1, 1.0), (MOD, tpu, 0.25), (P2f, pla2, 1.0)],
         f"Same, middle phalanx turned {ang:.0f}° about the pin (PLA parts only; module ghosted straight)",
         OUT / "B5_pinned_flexed.png", elev=12, azim=-15)
    print("wrote", OUT / "B5_pinned_straight.png", OUT / "B5_pinned_flexed.png")


if __name__ == "__main__":
    main()
