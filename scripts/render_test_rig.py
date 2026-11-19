"""Pictures of the single-joint PIP bending rig (TYPE B/round2/test_rig/build_test_rig.py).

    python scripts/render_test_rig.py        # needs CadQuery (builds the rig and a finger)

Writes docs/figures/test_rig/:
  rig_overview.png   the rig clamped to a table edge, joint straight, strings and weights
  rig_side_60.png    seen from the finger side of the protractor, joint at 60 deg, vane on 60
  rig_exploded.png   assembly order, parts pulled apart along the finger
The finger in the pictures carries the builder's reference module (B3 t1.5 / w3.0); any
Type B PIP module drops in the same way.
"""

from __future__ import annotations

import math
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
RIGDIR = REPO / "TYPE B" / "round2" / "test_rig"
sys.path.insert(0, str(RIGDIR))
OUT = REPO / "docs" / "figures" / "test_rig"

PLA_RIG = (0.93, 0.91, 0.84)
PLA_PH = (0.80, 0.80, 0.80)
TPU = (0.25, 0.48, 0.80)
ADAPT = (0.93, 0.62, 0.22)
PULLEY = (0.45, 0.45, 0.48)
TABLE = (0.78, 0.62, 0.42)
INK = "#222222"
NOTE = "#b5481d"


def world(p):
    """Finger frame (x lateral, y dorsal = DOWN on the rig, z along the finger) to the
    picture's frame (X along the finger, Y lateral, Z up)."""
    p = np.asarray(p, float)
    return np.stack([p[..., 2], p[..., 0], -p[..., 1]], axis=-1)


def mesh_of(shape, tol=0.08):
    import cadquery as cq
    path = Path(tempfile.mkdtemp()) / "m.stl"
    cq.exporters.export(cq.Workplane().add(shape), str(path), tolerance=tol, angularTolerance=0.3)
    m = trimesh.load(path, force="mesh")
    # small faces only: matplotlib sorts whole faces by depth, so big flat faces get drawn
    # over parts in front of them
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=3.0)
    return trimesh.Trimesh(v, f, process=False)


def rot_about_pivot(v, deg, pz):
    """+deg about +x through (y=0, z=pz): flexion, the distal part rises (-y)."""
    a = math.radians(deg)
    y, z = v[:, 1], v[:, 2] - pz
    out = v.copy()
    out[:, 1] = y * math.cos(a) - z * math.sin(a)
    out[:, 2] = y * math.sin(a) + z * math.cos(a) + pz
    return out


def rot_pt(p, deg, pz):
    return rot_about_pivot(np.array([p], float), deg, pz)[0]


class Scene:
    def __init__(self):
        self.tris, self.cols = [], []

    def add(self, verts_finger, faces, colour, alpha=1.0, shift=(0, 0, 0)):
        v = world(verts_finger) + np.asarray(shift)
        self.tris.append(v[faces])
        self.cols.append(np.tile([*colour, alpha], (len(faces), 1)))

    def add_box(self, lo, hi, colour, alpha=1.0):
        b = trimesh.creation.box(extents=np.subtract(hi, lo))
        b.apply_translation((np.add(lo, hi)) / 2)
        t = b.vertices[b.faces]
        self.tris.append(t)
        self.cols.append(np.tile([*colour, alpha], (len(b.faces), 1)))

    def draw(self, ax, view):
        tris = np.concatenate(self.tris)
        cols = np.concatenate(self.cols)
        n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        e, a = np.radians(view[0]), np.radians(view[1])
        light = np.array([np.cos(e) * np.cos(a + 0.7), np.cos(e) * np.sin(a + 0.7), np.sin(e) + 0.6])
        light /= np.linalg.norm(light)
        s = 0.42 + 0.58 * np.abs(n @ light)
        rgb = np.clip(cols[:, :3] * s[:, None] + 0.08 * s[:, None], 0, 1)
        ax.add_collection3d(Poly3DCollection(tris, facecolors=np.c_[rgb, cols[:, 3]], edgecolors="none",
                                             linewidths=0))
        return tris.reshape(-1, 3)


def frame(ax, pts, view, pad=4.0):
    lo, hi = pts.min(0) - pad, pts.max(0) + pad
    c, r = (lo + hi) / 2, (hi - lo) / 2
    ax.set_xlim(c[0] - r[0], c[0] + r[0])
    ax.set_ylim(c[1] - r[1], c[1] + r[1])
    ax.set_zlim(c[2] - r[2], c[2] + r[2])
    ax.set_box_aspect(2 * r)
    ax.view_init(*view)
    ax.set_axis_off()


def line(ax, pts_finger, **kw):
    w = world(np.asarray(pts_finger, float))
    ax.plot(w[:, 0], w[:, 1], w[:, 2], **kw)


def label(ax, p_finger, text, off=(40, 40), colour=INK, fs=8.5, shift=(0, 0, 0)):
    """Callout drawn flat over the picture: the 3D point is projected with the current
    view, and the text sits `off` points away. Call after frame()."""
    from mpl_toolkits.mplot3d import proj3d
    w = world(np.asarray(p_finger, float)) + np.asarray(shift)
    x2, y2, _ = proj3d.proj_transform(w[0], w[1], w[2], ax.get_proj())
    ax.annotate(text, (x2, y2), xytext=off, textcoords="offset points", fontsize=fs, color=colour, zorder=20,
                ha="center", va="center", annotation_clip=False,
                arrowprops=dict(arrowstyle="-", color="#666666", lw=0.8, shrinkA=0, shrinkB=0),
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#bbbbbb", lw=0.5))


def build():
    import cadquery as cq
    import build_test_rig as R
    g = R.geometry()
    base, info = R.rig_base(g)
    adapter = R.load_adapter(g)
    pul = R.pulley().translate(cq.Vector(-3.0, info["pulley_axle_y"], R.PULLEY_Z))
    parts = {
        "base": (mesh_of(base, 0.05), PLA_RIG),
        "P1": (mesh_of(g["parts"]["02_Phalanx1"].translate(cq.Vector(0, 0, g["z"]["02_Phalanx1"]))), PLA_PH),
        "module": (mesh_of(g["parts"]["03_PIP_module"].translate(cq.Vector(0, 0, g["z"]["03_PIP_module"])), 0.04), TPU),
        "P2": (mesh_of(g["parts"]["04_Phalanx2"].translate(cq.Vector(0, 0, g["z"]["04_Phalanx2"]))), PLA_PH),
        "adapter": (mesh_of(adapter), ADAPT),
        "pulley": (mesh_of(pul), PULLEY),
    }
    lay = g["lay"]
    geo = dict(pz=g["pivot_z"], y_t=info["y_tendon_line"], yc=info["pulley_axle_y"], pulley_z=R.PULLEY_Z,
               rg=R.PULLEY_RG, hooks=R.HOOK_R, z05=g["z"]["05_DIP_module"], e_dip=R.B.DIP["end_len"],
               y_anchor=(lay["DIP"]["tendon_y"] - g["deep"]["DIP"]) / 2, tick=R.TICK, plate_x=R.PLATE_X,
               angle_max=R.ANGLE_MAX)
    return parts, geo


def strings(ax, geo, deg, hook_r=44.8, weight_drop=45.0):
    pz = geo["pz"]
    # tendon: anchor in the adapter, back along the finger at the tendon line, over the pulley, down
    za = geo["z05"] + geo["e_dip"] + 1.2
    anchor = rot_pt((0, geo["y_anchor"], za), deg, pz)
    knee = rot_pt((0, geo["y_t"], pz + 4), deg, pz)
    ptop = (0, geo["y_t"], geo["pulley_z"])
    arc = [(0, geo["yc"] - geo["rg"] * math.cos(t), geo["pulley_z"] - geo["rg"] * math.sin(t))
           for t in np.linspace(0, math.pi / 2, 10)]
    hang = (0, geo["yc"] + weight_drop, geo["pulley_z"] - geo["rg"])
    line(ax, [anchor, knee, (0, geo["y_t"], pz - 4), ptop], color="#c0392b", lw=1.6)
    line(ax, arc + [hang], color="#c0392b", lw=1.6)
    # hook weight on the arm hole
    hole = rot_pt((-10.0, 0, pz + hook_r), deg, pz)
    hw = (hole[0], hole[1] + weight_drop * 0.75, hole[2])
    line(ax, [hole, hw], color="#2c3e50", lw=1.2)
    return hang, hw


def weight(sc, at_finger, size=(9, 9, 12), colour=(0.35, 0.35, 0.38)):
    w = world(np.asarray(at_finger, float))
    lo = (w[0] - size[0] / 2, w[1] - size[1] / 2, w[2] - size[2])
    hi = (w[0] + size[0] / 2, w[1] + size[1] / 2, w[2])
    sc.add_box(lo, hi, colour)


def add_parts(sc, parts, deg, pz, ghost_module=False, shift=None):
    for k, (m, col) in parts.items():
        v = m.vertices.copy()
        if k in ("P2", "adapter"):
            v = rot_about_pivot(v, deg, pz)
        alpha = 0.3 if (k == "module" and ghost_module) else 1.0
        sc.add(v, m.faces, col, alpha, shift=(shift or {}).get(k, (0, 0, 0)))


def overview(parts, geo):
    view = (24, 62)
    fig = plt.figure(figsize=(11, 8))
    ax = fig.add_subplot(111, projection="3d")
    sc = Scene()
    add_parts(sc, parts, 0, geo["pz"])
    hang, hw = strings(ax, geo, 0)
    weight(sc, hang)
    weight(sc, hw, size=(7, 7, 9), colour=(0.25, 0.30, 0.40))
    pts = sc.draw(ax, view)
    frame(ax, pts[pts[:, 2] > -75], view)
    pz = geo["pz"]
    label(ax, (-55, 10, -30), "1  Rig base: its flat plate is clamped to a table\n    edge (2 slots); the finger overhangs the edge",
          off=(40, 110))
    label(ax, (0, -6, 14), "2  Phalanx 1, pinned onto the dummy MCP tab", off=(110, 80))
    label(ax, (0, -6, pz), "3  PIP module under test (TPU)", off=(-40, 120), colour="#1f4e8c")
    label(ax, (0, -6, pz + 18), "4  Phalanx 2", off=(-70, 70))
    label(ax, (0, -3, pz + 40), "5  Load adapter: hook holes at 30 / 37.5 / 44.8 mm,\n    pointer vane over the scale",
          off=(-150, -50))
    label(ax, (-12.5, -50, pz), "6  Protractor 0–115°", off=(-70, 50))
    label(ax, (0, geo["yc"], geo["pulley_z"]), "7  Pulley (623ZZ bearing, M3 bolt)", off=(70, -10))
    label(ax, hang, "tendon weight", off=(60, 0), colour="#c0392b")
    label(ax, hw, "fingertip weight\non the 44.8 mm hole", off=(110, -60), colour="#2c3e50")
    ax.set_title("Single-joint PIP bending rig, joint straight. The finger lies palm side UP and overhangs the table edge;\n"
                 "flexing lifts the adapter against the fingertip weight, and the tendon pulls over the pulley.", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "rig_overview.png", dpi=170)
    plt.close(fig)


def side(parts, geo, deg=60):
    view = (0, 0.01)        # looking along -Y in the picture, i.e. from the finger side of the protractor
    fig = plt.figure(figsize=(11, 7.5))
    ax = fig.add_subplot(111, projection="3d")
    sc = Scene()
    p = {k: v for k, v in parts.items()}
    add_parts(sc, p, deg, geo["pz"], ghost_module=True)
    hang, hw = strings(ax, geo, deg)
    weight(sc, hang)
    weight(sc, hw, size=(7, 7, 9), colour=(0.25, 0.30, 0.40))
    pts = sc.draw(ax, (12, 90))
    pz = geo["pz"]
    # scale numbers and ticks drawn over the engraving so they read in the picture
    for d in range(0, geo["angle_max"] + 1, 10):
        a = math.radians(d)
        r = geo["tick"][1] + 5.0
        w = world(np.array([geo["plate_x"][1] + 0.5, -r * math.sin(a), pz + r * math.cos(a)]))
        ax.text(w[0], w[1] + 12, w[2], f"{d}", fontsize=8, ha="center", va="center", color=NOTE, zorder=12)
    # pivot and angle
    c = world(np.array([0, 0, pz]))
    ax.plot([c[0]], [c[1] + 12], [c[2]], "o", color=NOTE, ms=4, zorder=12)
    arc = [world(np.array([0, -28 * math.sin(math.radians(t)), pz + 28 * math.cos(math.radians(t))]))
           for t in np.linspace(0, deg, 20)]
    arc = np.array(arc)
    ax.plot(arc[:, 0], arc[:, 1] + 12, arc[:, 2], color=NOTE, lw=1.4, zorder=12)
    view2 = (12, 90)
    frame(ax, pts[pts[:, 2] > -75], view2)
    vane = rot_pt((-7, 0, pz + 47.5), deg, pz)
    label(ax, vane, "pointer vane: read the angle here", off=(-60, 45), colour=NOTE, shift=(0, 12, 0))
    label(ax, (0, 0, pz), "nominal PIP pivot\n(centre of the scale)", off=(40, -70), shift=(0, 12, 0))
    label(ax, hw, "fingertip weight", off=(-80, -40), shift=(0, 12, 0))
    label(ax, hang, "tendon weight", off=(70, 0), shift=(0, 12, 0))
    a_mid = math.radians(deg * 0.5)
    label(ax, (0, -28 * math.sin(a_mid), pz + 28 * math.cos(a_mid)), f"joint angle {deg}°", off=(70, 20),
          colour=NOTE, fs=10, shift=(0, 12, 0))
    ax.set_title(f"Seen from the finger side of the protractor, joint at {deg}° (module drawn faint; its bend comes from the test).\n"
                 "Read the angle where the vane crosses the scale; the scale is centred on the nominal PIP pivot.",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "rig_side_60.png", dpi=170)
    plt.close(fig)


def exploded(parts, geo):
    view = (22, 58)
    fig = plt.figure(figsize=(12, 7.2))
    ax = fig.add_subplot(111, projection="3d")
    sc = Scene()
    gap = {"base": (-40, 0, 0), "P1": (0, 0, 0), "module": (22, 0, 0), "P2": (44, 0, 0), "adapter": (70, 0, 0),
           "pulley": (-40, 0, 0)}
    add_parts(sc, parts, 0, geo["pz"], shift=gap)
    pts = sc.draw(ax, view)
    frame(ax, pts, view)
    pz = geo["pz"]
    label(ax, (9, -5, -11), "1  Rig base", off=(40, -70), shift=gap["base"])
    label(ax, (0, -6, 15), "2  Phalanx 1: slide onto the base's\n    dummy MCP tab, 2 pins Ø2", off=(40, 80), shift=gap["P1"])
    label(ax, (0, -6, pz), "3  PIP module: tabs into Phalanx 1\n    and Phalanx 2, 2 pins each end",
          off=(50, -70), colour="#1f4e8c", shift=gap["module"])
    label(ax, (0, -6, pz + 18), "4  Phalanx 2", off=(-30, 60), shift=gap["P2"])
    label(ax, (0, -3, pz + 40), "5  Load adapter: dummy DIP tab into\n    Phalanx 2, 2 pins; tendon anchor",
          off=(-20, -70), shift=gap["adapter"])
    label(ax, (0, geo["yc"], geo["pulley_z"]), "6  Pulley on a 623ZZ bearing,\n    M3 bolt through the clevis",
          off=(70, -40), shift=gap["pulley"])
    ax.set_title("Assembly order (pulled apart along the finger). Thread the tendon through the post, Phalanx 1, the module and\n"
                 "Phalanx 2 before the load adapter goes on; tie it off in the adapter's anchor hole.", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "rig_exploded.png", dpi=170)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts, geo = build()
    overview(parts, geo)
    side(parts, geo, 60)
    exploded(parts, geo)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
