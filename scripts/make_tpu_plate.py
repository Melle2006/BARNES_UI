"""One build plate with every TPU part the Type B rig tests need, in the print orientation.

    python3 scripts/make_tpu_plate.py          # needs trimesh, matplotlib

Takes the 12 labelled PIP modules from print_ready/type_b_modules/ (A1-P ... K2-P), lays each
one on its side (lateral axis vertical, so every strip and leaf lies in XY, as the print
report says), packs them in a 4 × 3 grid centred on a Bambu A1 bed (256 × 256 mm), and writes:

* print_ready/plates/TPU_rig_modules_A1.stl   one file, all 12 parts placed
* print_ready/plates/TPU_rig_modules_A1.3mf   the same, one named object per module
* print_ready/plates/TPU_rig_modules_A1.pdf   one page: plate map, view, slicer settings
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "print_ready" / "type_b_modules"
OUT = REPO / "print_ready" / "plates"
BED = 256.0
GAP = 10.0

#: rows by rig priority (front row = priority 1)
GRID = [["H1-P", "H2-P", "K1-P", "K2-P"],
        ["A1-P", "A2-P", "B1-P", "B2-P"],
        ["C-P", "E-P", "F-P", "G-P"]]
NAMES = {"A": "B5 t2.0 deep", "B": "B5 t1.5 as built", "C": "B4 rolling, deep", "E": "B8 knuckle dorsal, deep",
         "F": "B8 knuckle central", "G": "B3 dual leaf (optional)", "H": "pinned B5, outside", "K": "inset pinned B5"}
GAPPED = {"C-P", "E-P", "F-P"}       # 0.5 mm bearing gap: no support inside it

SETTINGS = [
    ("Printer / plate", "Bambu A1, 0.4 mm nozzle, Textured PEI plate; TPU from the external spool holder (not the AMS lite)"),
    ("Filament", "SUNLU TPU 90A, dried 50 °C 4–6 h. Start from Generic TPU, save as 'SUNLU TPU 90A – BARNES'"),
    ("Temperatures", "Nozzle 225 °C (first layer 230 °C); Textured PEI bed 45 °C (first layer 50 °C)"),
    ("Max volumetric speed", "2.5 mm³/s (Filament tab); retraction 0.6 mm at 25 mm/s (Setting Overrides)"),
    ("Quality", "Layer 0.2 mm; line widths default 0.42 mm; wall generator Arachne; elephant foot 0.15 mm"),
    ("Strength", "4 wall loops; sparse infill 100 % rectilinear; top/bottom shells default"),
    ("Speed", "First layer 15, outer wall 20, inner wall 25, infill 25, top/gap 20 mm/s; "
              "accel. 1000 (normal), 300 first layer, 500 outer wall, 3000 travel"),
    ("Cooling", "Part fan 50–100 %"),
    ("Support", "On: Normal (auto), On build plate only, threshold 30°, top Z distance 0.2 mm, interface 2 layers. "
                "(under the tab ends and collar edges). No blocker needed: every gap roof has the part beneath it, "
                "so 'build plate only' keeps support out of the gaps (support_blockers.png)"),
    ("Bed adhesion", "Brim: Outer brim only, 5 mm (each part stands 13 mm tall on its collar's side face, about 12 mm², "
                     "plus its supports). Clean PEI; glue stick only if TPU bonds too hard to release"),
    ("Why this way up", "On its side the strips' thickness is set by the walls (accurate) not by 0.2 mm layer steps, "
                        "and the 0.5 mm bearing gaps are vertical walls that need no support. Do not lay them flat"),
    ("On loading", "Open the 3MF (or the STL, answering 'No' to 'load as a single object') and do not auto-arrange or "
                   "rotate: the parts are already on their side, labels readable on the tab ends"),
    ("After printing", "Measure each strip/leaf at 3 points; 0.25 mm feeler gauge through the C, E, F gaps; "
                       "the label is engraved on each module's proximal tab end"),
]


def load(code):
    path = next(SRC.glob(f"{code}_*_PIP.stl"))
    m = trimesh.load(path)
    # lay it on its side: lateral axis (X) -> vertical (Z), the -X side on the bed
    m.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [0, 1, 0]))
    m.apply_translation(-m.bounds[0])
    return m, path.name


def build():
    parts = {}
    for row in GRID:
        for code in row:
            parts[code] = load(code)
    ext = np.max([m.extents for m, _ in parts.values()], axis=0)
    ncol, nrow = len(GRID[0]), len(GRID)
    W = ncol * ext[0] + (ncol - 1) * GAP
    D = nrow * ext[1] + (nrow - 1) * GAP
    x0, y0 = (BED - W) / 2, (BED - D) / 2
    placed = []
    for r, row in enumerate(GRID):
        for k, code in enumerate(row):
            m, src = parts[code]
            m = m.copy()
            cx = x0 + k * (ext[0] + GAP) + (ext[0] - m.extents[0]) / 2
            cy = y0 + r * (ext[1] + GAP) + (ext[1] - m.extents[1]) / 2
            m.apply_translation([cx, cy, 0])
            placed.append((code, src, m))
    return placed, (x0, y0, W, D)


def check(placed):
    out = []
    for code, _, m in placed:
        n, c, a = m.face_normals, m.triangles_center, m.area_faces
        on_bed = a[(n[:, 2] < -0.99) & (c[:, 2] < 0.01)].sum()
        over = a[(n[:, 2] < -np.cos(np.radians(60))) & (c[:, 2] > 0.05)].sum()  # overhang beyond 30° from vertical
        assert m.is_watertight and m.bounds[0][2] > -1e-6
        out.append((code, on_bed, over, m.extents[2], m.volume))
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            a, b = placed[i][2].bounds, placed[j][2].bounds
            sep = np.maximum(a[0][:2] - b[1][:2], b[0][:2] - a[1][:2]).max()
            assert sep >= GAP - 1e-6, (placed[i][0], placed[j][0])
    return out


def export(placed):
    OUT.mkdir(parents=True, exist_ok=True)
    trimesh.util.concatenate([m for _, _, m in placed]).export(OUT / "TPU_rig_modules_A1.stl")
    scene = trimesh.Scene()
    for code, _, m in placed:
        scene.add_geometry(m, node_name=code, geom_name=code)
    scene.export(OUT / "TPU_rig_modules_A1.3mf")


def page(placed, stats, box):
    x0, y0, W, D = box
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.suptitle("TPU print plate: the 12 Type B PIP modules for the bending rig (Bambu A1)", fontsize=13,
                 fontweight="bold", x=0.03, ha="left", y=0.975)
    fig.text(0.03, 0.935, "print_ready/plates/TPU_rig_modules_A1.stl / .3mf  ·  made by scripts/make_tpu_plate.py  ·  "
             "every module on its side (lateral axis vertical), strips and leaves in XY, never on a tab end",
             fontsize=8, color="0.3")

    # plate map (top view)
    ax = fig.add_axes([0.03, 0.47, 0.44, 0.44])
    ax.add_patch(plt.Rectangle((0, 0), BED, BED, fc="0.96", ec="0.6"))
    for code, _, m in placed:
        tri = m.triangles[m.face_normals[:, 2] > 0.05][:, :, :2]
        for t in tri:
            ax.fill(t[:, 0], t[:, 1], color="#4a7fb5" if code not in GAPPED else "#b5704a", lw=0)
        bx = m.bounds
        ax.text((bx[0][0] + bx[1][0]) / 2, bx[1][1] + 1.5, code, ha="center", va="bottom", fontsize=7.5,
                fontweight="bold")
    pad = 14
    ax.set_xlim(x0 - pad, x0 + W + pad)
    ax.set_ylim(y0 - pad, y0 + D + pad)
    ax.set_aspect("equal")
    ax.set_title(f"Top view, bed coordinates (mm); group {W:.0f} × {D:.0f} mm centred on the 256 mm bed",
                 fontsize=8.5)
    ax.tick_params(labelsize=7)
    ax.text(x0 - pad + 2, y0 - pad + 2, "front of the bed", fontsize=7, color="0.4")
    ax.text(x0 + W + pad - 2, y0 - pad + 2, "orange: 0.5 mm bearing gap (stays clear)", fontsize=7,
            color="#b5704a", ha="right")

    # 3D view
    ax3 = fig.add_axes([0.50, 0.47, 0.48, 0.44], projection="3d")
    for code, _, m in placed:
        n = m.face_normals
        shade = 0.45 + 0.5 * np.clip(n @ np.array([0.3, -0.5, 0.8]) / 1.0, 0, 1)
        base = np.array([0.29, 0.50, 0.71]) if code not in GAPPED else np.array([0.71, 0.44, 0.29])
        cols = np.clip(base[None, :] * shade[:, None] + 0.15, 0, 1)
        ax3.add_collection3d(Poly3DCollection(m.triangles, facecolors=cols, edgecolors="none"))
    ax3.set_xlim(x0, x0 + W)
    ax3.set_ylim(y0, y0 + D)
    ax3.set_zlim(0, 25)
    ax3.set_box_aspect((W, D, 25))
    ax3.view_init(elev=32, azim=-62)
    ax3.set_axis_off()
    ax3.set_title("As placed on the bed (same grid as the map)", fontsize=8.5)

    # parts list
    ax_t = fig.add_axes([0.03, 0.295, 0.94, 0.15])
    ax_t.axis("off")
    rows = []
    for code, on_bed, over, h, vol in stats:
        rows.append([code, NAMES[code[0]], f"{h:.1f}", f"{on_bed:.0f}", f"{over:.0f}", f"{vol / 1000:.2f}",
                     "0.5 mm gap" if code in GAPPED else ""])
    half = (len(rows) + 1) // 2
    hdr = ["Label", "Design", "Height mm", "On bed mm²", "Needs support mm²", "Vol cm³", ""]
    for i, chunk in enumerate((rows[:half], rows[half:])):
        t = ax_t.table(cellText=chunk, colLabels=hdr, bbox=[i * 0.505, 0, 0.495, 1],
                       colWidths=[0.09, 0.30, 0.11, 0.12, 0.16, 0.10, 0.12])
        t.auto_set_font_size(False)
        t.set_fontsize(6.8)
        for (r, cc), cell in t.get_celld().items():
            cell.set_edgecolor("0.75")
            if r == 0:
                cell.set_facecolor("#dde6f0")
            if cc == 1 and r > 0:
                cell._loc = "left"
                cell.get_text().set_ha("left")
    total = sum(s[4] for s in stats) / 1000
    fig.text(0.03, 0.272, f"12 parts, {total:.1f} cm³ of TPU (about {total * 1.21:.0f} g at 1.21 g/cm³). "
             "Front row first in priority (H, K), then A, B, then the bearings C, E, F and the optional G.",
             fontsize=7.5)

    # settings
    ax_s = fig.add_axes([0.03, 0.02, 0.94, 0.245])
    ax_s.axis("off")
    t = ax_s.table(cellText=[[a, b] for a, b in SETTINGS], colLabels=["Bambu Studio setting", "Value"],
                   bbox=[0, 0, 1, 1], colWidths=[0.16, 0.84], cellLoc="left")
    t.auto_set_font_size(False)
    t.set_fontsize(6.8)
    for (r, cc), cell in t.get_celld().items():
        cell.set_edgecolor("0.75")
        if r == 0:
            cell.set_facecolor("#dde6f0")
        if r > 0:
            cell._loc = "left"
            cell.get_text().set_ha("left")
            cell.PAD = 0.01 if cc == 1 else 0.03
        if cc == 0 and r > 0:
            cell.get_text().set_fontweight("bold")
    with PdfPages(OUT / "TPU_rig_modules_A1.pdf") as pdf:
        pdf.savefig(fig)
    fig.savefig(OUT / "TPU_rig_modules_A1.png", dpi=110)
    plt.close(fig)


def main():
    placed, box = build()
    stats = check(placed)
    export(placed)
    page(placed, stats, box)
    for s in stats:
        print("%-5s on bed %5.1f mm²  support %5.1f mm²  h %.1f  vol %.0f" % s)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
