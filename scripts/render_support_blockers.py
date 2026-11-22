"""Do the TPU modules need a support blocker? (No, with 'On build plate only'.)

    python3 scripts/render_support_blockers.py

Uses the plate from make_tpu_plate.py. A face needs blocking if it faces downward (more than
30° from vertical, so the slicer would support it) and a ray from it along its normal hits
the same part within 0.8 mm: it is the roof of a gap (the B4/B8 bearing gaps, the crossings
of the strips). Support there would fill the gap. But with 'On build plate only' the slicer
only supports faces with a clear vertical path to the bed, and every gap roof has the part
underneath it (checked by a ray straight down), so none gets support and nothing needs
painting. Grey faces do get support. Writes print_ready/plates/support_blockers.png (+ .pdf).
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_tpu_plate as T  # noqa: E402

OUT = T.OUT
LIGHT = np.array([0.35, -0.55, 0.75]) / np.linalg.norm([0.35, -0.55, 0.75])


def gap_faces(m, reach=0.8):
    n, c = m.face_normals, m.triangles_center
    down = np.where((n[:, 2] < -0.5) & (c[:, 2] > 0.05))[0]
    loc, ri, _ = m.ray.intersects_location(c[down] + n[down] * 1e-3, n[down], multiple_hits=False)
    d = np.full(len(down), np.inf)
    d[ri] = np.linalg.norm(loc - c[down][ri], axis=1)
    red, rest = down[d < reach], down[d >= reach]
    return red, to_bed(m, rest)


def to_bed(m, f):
    """Faces with a clear vertical path to the bed: the only ones 'On build plate only' supports."""
    if len(f) == 0:
        return f
    o = m.triangles_center[f] - [0, 0, 1e-3]
    _, ri, _ = m.ray.intersects_location(o, np.tile([0, 0, -1.0], (len(f), 1)), multiple_hits=False)
    ok = np.ones(len(f), bool)
    ok[ri] = False
    return f[ok]


def view(ax, m, red, sup, elev, azim, title, centre=None, half=None):
    """Painter's-algorithm render: faces sorted back to front, red = paint blocker, grey = normal support."""
    e, a = np.radians(elev), np.radians(azim)
    fwd = -np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])   # camera looks along fwd
    right = np.cross(fwd, [0, 0, 1.0])
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0, 0]) if fwd[2] < 0 else np.array([1.0, 0, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    tri = m.triangles
    n = m.face_normals
    vis = n @ fwd < 0                                         # front faces only
    idx = np.where(vis)[0]
    depth = (m.triangles_center[idx] @ fwd)
    idx = idx[np.argsort(-depth)]
    p2 = np.stack([tri[idx] @ right, tri[idx] @ up], axis=-1)
    shade = 0.55 + 0.4 * np.abs(n[idx] @ LIGHT)
    base = np.array([0.36, 0.56, 0.78])
    cols = np.clip(base[None] * shade[:, None] + 0.12, 0, 1)
    isred = np.isin(idx, red)
    issup = np.isin(idx, sup)
    cols[issup] = np.clip(np.array([0.62, 0.62, 0.62])[None] * shade[issup, None] + 0.25, 0, 1)
    cols[isred] = [0.86, 0.12, 0.12]
    ax.add_collection(PolyCollection(p2, facecolors=cols, edgecolors=cols, linewidths=0.2))
    # red faces hidden behind others: outline them on top so their position is always visible
    hid = np.setdiff1d(red, idx[isred])
    if len(hid):
        q = np.stack([tri[hid] @ right, tri[hid] @ up], axis=-1)
        ax.add_collection(PolyCollection(q, facecolors="none", edgecolors=(0.86, 0.12, 0.12, 0.9), linewidths=0.6,
                                         linestyles=(0, (1.5, 1))))
    allp = np.stack([m.vertices @ right, m.vertices @ up], axis=-1)
    if centre is None:
        lo, hi = allp.min(0), allp.max(0)
        centre, half = (lo + hi) / 2, (hi - lo).max() / 2 * 1.08
    ax.set_xlim(centre[0] - half, centre[0] + half)
    ax.set_ylim(centre[1] - half, centre[1] + half)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=8)


def main():
    placed, box = T.build()
    parts = {code: m for code, _, m in placed}
    zones = {}
    for code in ("C-P", "E-P", "F-P"):
        zones[code] = gap_faces(parts[code])
    others = {code: gap_faces(m)[0] for code, m in parts.items() if code not in zones}
    assert all(parts[c].area_faces[f].sum() < 5 for c, f in others.items())
    for code, m in parts.items():                 # the claim on the page: no gap roof can be reached from the bed
        assert len(to_bed(m, gap_faces(m)[0])) == 0, code

    fig = plt.figure(figsize=(11.69, 8.9))
    fig.suptitle("Support blocker: none needed. 'On build plate only' already keeps support out of every gap",
                 fontsize=13,
                 fontweight="bold", x=0.02, ha="left", y=0.985)
    fig.text(0.02, 0.952, "Red: the roofs of the 0.5 mm bearing gaps (support there would fill the gap; dotted = hidden in "
             "that view). Every one has the part directly beneath it, so with 'On build plate only' no support can "
             "reach it.\nGrey: the overhangs that DO get support (a clear vertical path to the bed): tab ends, collar "
             "edges. Blue: no support. Checked on all 12 modules; C, E, F shown because their gaps are the big ones.",
             fontsize=8, color="0.25", va="top")

    # plate overview, top view as in Bambu Studio
    ax0 = fig.add_axes([0.01, 0.63, 0.33, 0.27])
    x0, y0, W, D = box
    for code, _, m in placed:
        tri = m.triangles[m.face_normals[:, 2] > 0.05][:, :, :2]
        hit = code in zones
        ax0.add_collection(PolyCollection(tri, facecolors="#f0b0b0" if hit else "#a9c3df", edgecolors="none"))
        if hit:
            v = m.triangles[zones[code][0]].reshape(-1, 3)
            lo, hi = v.min(0), v.max(0)
            ax0.add_patch(plt.Rectangle(lo[:2] - 0.6, *(hi[:2] - lo[:2] + 1.2), fc="none", ec="#d01818", lw=1.4))
        bx = m.bounds
        ax0.text((bx[0][0] + bx[1][0]) / 2, bx[1][1] + 1.2, code, ha="center", fontsize=7,
                 fontweight="bold", color="#d01818" if hit else "k")
    ax0.set_xlim(x0 - 6, x0 + W + 6)
    ax0.set_ylim(y0 - 8, y0 + D + 8)
    ax0.set_aspect("equal")
    ax0.tick_params(labelsize=6)
    ax0.set_title("Plate, top view: the bearing modules (back row), gaps boxed", fontsize=8.5)
    ax0.text(x0 - 4, y0 - 7, "front of the bed", fontsize=6.5, color="0.4")

    howto = ("What to do in Bambu Studio\n"
             "1. Support: Enable. Type: Normal (auto).\n"
             "   'On build plate only': TICKED. Threshold 30°.\n"
             "   (This is what keeps support out of the gaps:\n"
             "   don't use Tree here, its branches can bend.)\n"
             "2. No support painting, no blocker.\n"
             "3. Slice, open Preview, show 'Support' only.\n"
             "   Support should be only under the tab ends and\n"
             "   collar edges (grey in the pictures).\n"
             "4. Drag the layer slider from 3 to 11 mm and zoom\n"
             "   on C-P, E-P, F-P (back row): no support line\n"
             "   inside the gap (red areas).\n"
             "5. Only if you see one: L (Support painting),\n"
             "   Sphere 1 mm, right mouse = Block, brush that\n"
             "   spot in the gap, slice again.")
    fig.text(0.355, 0.64, howto, fontsize=7.6, family="monospace", va="bottom",
             bbox=dict(fc="#fff8dc", ec="0.7", boxstyle="round,pad=0.5"))
    areas = "\n".join(f"{c}: gap roof {parts[c].area_faces[zones[c][0]].sum():.0f} mm², 0 mm² reachable from the bed"
                      for c in zones)
    fig.text(0.70, 0.88, areas, fontsize=7.6, color="#a01010", va="top")
    fig.text(0.70, 0.80, "Gap roofs at 2.9–11.1 mm above the bed.\nSupported area per module: about 85–110 mm².",
             fontsize=7.6, color="0.3", va="top")

    # per-module views
    views = [(90, -90, "top (Bambu's default)"), (35, -60, "front-left, from above"),
             (-35, -60, "from below the bed"), (-35, 120, "from below, other side")]
    for r, code in enumerate(zones):
        m = parts[code]
        red, sup = zones[code]
        for k, (el, az, t) in enumerate(views):
            ax = fig.add_axes([0.01 + k * 0.245, 0.40 - r * 0.195, 0.235, 0.18])
            view(ax, m, red, sup, el, az, f"{code}: {t}")
    with plt.rc_context():
        fig.savefig(OUT / "support_blockers.png", dpi=130)
        fig.savefig(OUT / "support_blockers.pdf")
    plt.close(fig)
    print("wrote", OUT / "support_blockers.png")


if __name__ == "__main__":
    main()
