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


CASES = {
    "B5_pinned": ("outside", "TYPE B/round2/deep_offset/B5_t150_a45_deep",
                  "Pinned B5, plates outside the module (18.1 mm wide): proximal phalanx (grey), B5 t1.5 module (blue),\n"
                  "middle phalanx (orange); Ø2 pins through the overlapping plates, 0.65 mm palmar of the strip crossing"),
    "B5_inset": ("inset", None,
                 "Inset pinned B5 (14.1 mm wide, the finger's own width): narrowed B5 module (blue) with the PLA\n"
                 "plates beside its collars; proximal phalanx plate outer, middle phalanx plate inner"),
}


def main(names=None):
    import cadquery as cq
    for key, (layout, folder, title) in CASES.items():
        if names and key not in names:
            continue
        if folder is None:
            folder = sorted((REPO / "TYPE B/round2/pinned_b5_inset").glob("B5i_*_deep"))[-1]
            sel = REPO / "TYPE B/round2/pinned_b5_inset/selected.txt"
            if sel.exists():
                folder = REPO / "TYPE B/round2/pinned_b5_inset" / sel.read_text().strip()
        geo = BP.build(REPO / folder, layout=layout)
        module, dz = BP.place(geo)
        p2 = geo["P2"].moved(cq.Location(cq.Vector(0, 0, dz)))
        zp = geo["pin1"]
        crop = cq.Workplane("XY").box(60, 60, 44).translate((0, 0, zp)).val()
        P1, P2, MOD = (mesh_of(s.intersect(crop)) for s in (geo["P1"], p2, module))
        pla1, pla2, tpu = (0.85, 0.85, 0.88), (0.95, 0.75, 0.35), (0.33, 0.52, 0.78)
        OUT.mkdir(parents=True, exist_ok=True)
        draw([(P1, pla1, 1.0), (MOD, tpu, 1.0), (P2, pla2, 1.0)], title, OUT / f"{key}_straight.png")
        ang = 70.0
        T = trimesh.transformations.rotation_matrix(np.radians(ang), [1, 0, 0], [0, geo["dy"], zp])
        P2f = P2.copy()
        P2f.apply_transform(T)
        draw([(P1, pla1, 1.0), (MOD, tpu, 0.25), (P2f, pla2, 1.0)],
             f"Same, middle phalanx turned {ang:.0f}° about the pin (PLA parts only; module ghosted straight)",
             OUT / f"{key}_flexed.png", elev=12, azim=-15)
        # end-on view: how wide the joint is against the phalanx
        draw([(P1, pla1, 1.0), (MOD, tpu, 1.0), (P2, pla2, 1.0)],
             f"{'Outside' if layout == 'outside' else 'Inset'} plates, seen from the back of the finger: "
             f"{geo['width_over_plates']:.1f} mm over the plates", OUT / f"{key}_top.png", elev=88, azim=-90)
        print("wrote", key)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
