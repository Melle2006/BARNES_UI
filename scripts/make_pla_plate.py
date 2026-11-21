"""One build plate with every PLA part the Type B bending-rig tests need, in the print orientation.

    python3 scripts/make_pla_plate.py          # needs trimesh, matplotlib

The partner of make_tpu_plate.py. Parts (labelled, from print_ready/): the rig base, load
adapter and pulley, and one set of each kind of phalanges the 12 TPU modules sit between:

* S1, S2  as-built phalanges   for B1-P, B2-P, F-P, G-P
* X1, X2  deep phalanges       for A1-P, A2-P, C-P, E-P
* H1, H2  pinned, plates outside, for H1-P, H2-P
* K1, K2  pinned, inset plates,   for K1-P, K2-P

Phalanx 3 is not used on the rig (the load adapter takes its place). Parts listed in
PRINTED are already printed and left off the plate (as of 2026-11-21 everything but K1, K2).
Writes print_ready/plates/PLA_rig_parts_A1.stl / .3mf / .pdf.
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
PR = REPO / "print_ready"
OUT = PR / "plates"
BED = 256.0
GAP = 12.0
R = trimesh.transformations.rotation_matrix

#: label, file, rotation onto the bed, what it is, used with
PARTS = [
    ("RIG", "rig/RIG_rig_base.stl", R(-np.pi / 2, [1, 0, 0]), "rig base, on its side plate", "every test"),
    ("ADP", "rig/ADP_load_adapter.stl", np.eye(4), "load adapter, on its tab end", "every test"),
    ("PUL", "rig/PUL_pulley.stl", R(-np.pi / 2, [0, 1, 0]), "pulley, flat", "every test"),
    ("S1", "type_b_phalanges/S1_common_phalanges_02_Phalanx1.stl", np.eye(4), "as-built Phalanx 1", "B, F, G"),
    ("S2", "type_b_phalanges/S2_common_phalanges_04_Phalanx2.stl", np.eye(4), "as-built Phalanx 2", "B, F, G"),
    ("X1", "type_b_phalanges/X1_deep_phalanges_02_Phalanx1.stl", np.eye(4), "deep Phalanx 1", "A, C, E"),
    ("X2", "type_b_phalanges/X2_deep_phalanges_04_Phalanx2.stl", np.eye(4), "deep Phalanx 2", "A, C, E"),
    ("H1", "type_b_phalanges/H1_02_Phalanx1_pinned.stl", np.eye(4), "pinned P1, plates outside", "H"),
    ("H2", "type_b_phalanges/H2_04_Phalanx2_pinned.stl", R(np.pi, [1, 0, 0]), "pinned P2, plates outside", "H"),
    ("K1", "type_b_phalanges/K1_02_Phalanx1_pinned.stl", np.eye(4), "pinned P1, inset plates", "K"),
    ("K2", "type_b_phalanges/K2_04_Phalanx2_pinned.stl", R(np.pi, [1, 0, 0]), "pinned P2, inset plates", "K"),
]
#: small parts, in rows to the right of the base
GRID = [["ADP", "PUL", "S1", "S2"], ["X1", "X2", "H1", "H2"], ["K1", "K2"]]
#: already printed (rig and the earlier phalanges): left off the plate; empty this to get the full set
PRINTED = {"RIG", "ADP", "PUL", "S1", "S2", "X1", "X2", "H1", "H2"}
GRID = [[c for c in row if c not in PRINTED] for row in GRID]
GRID = [row for row in GRID if row]

SETTINGS = [
    ("Printer / filament", "Bambu A1, 0.4 mm nozzle, Textured PEI plate; any PLA (Bambu PLA Basic profile), AMS lite is fine"),
    ("Temperatures", "Profile defaults: nozzle 220 °C, Textured PEI bed 55 °C"),
    ("Quality", "Layer 0.2 mm (0.2 mm Standard), default line widths"),
    ("Strength", "4 wall loops; sparse infill 50 % gyroid (the hinge-pin load goes through the plates)"),
    ("Speed", "Profile defaults"),
    ("Support", "On: Tree (auto), On build plate only, threshold 30°. Nothing goes in the pin holes or sockets; "
                "it catches the overhang under the hinge plates' discs (and the rig base's, if on the plate)"),
    ("Bed adhesion", "Brim: Outer brim only, 5 mm: the phalanges stand on their ends (40–60 mm² each, up to 39 mm tall)"),
    ("Why this way up", "Phalanges stand on the end away from the joint, so the sockets and hinge-plate pin holes come out "
                        "round and the plates vertical. K2 is upside down on purpose (its joint end up)"),
    ("On loading", "Open the 3MF (or the STL, answering 'No' to 'load as a single object'); don't auto-arrange or rotate"),
    ("After printing", "Drill pin holes to Ø2.0 if tight; push a pin through each tab hole to check. K2's hinge hole is "
                       "blind on the inside: Ø2 × 1.8 mm pins pushed in from outside through K1's plate, glued at the outer end"),
]


def load(rel, rot):
    m = trimesh.load(PR / rel)
    m.apply_transform(rot)
    m.apply_translation(-m.bounds[0])
    return m


def build():
    info = {p[0]: p for p in PARTS}
    meshes = {p[0]: load(p[1], p[2]) for p in PARTS}
    base = meshes["RIG"] if "RIG" not in PRINTED else None
    cell = np.max([meshes[c].extents for row in GRID for c in row], axis=0)
    ncol = max(len(r) for r in GRID)
    gw = ncol * cell[0] + (ncol - 1) * GAP
    gd = len(GRID) * cell[1] + (len(GRID) - 1) * GAP
    bw = base.extents[0] + GAP if base is not None else 0.0
    x0 = (BED - (bw + gw)) / 2
    placed = []
    if base is not None:
        b = base.copy()
        b.apply_translation([x0, (BED - base.extents[1]) / 2, 0])
        placed.append(("RIG", b))
    gx, gy = x0 + bw, (BED - gd) / 2
    for r, row in enumerate(GRID):
        for k, code in enumerate(row):
            m = meshes[code].copy()
            m.apply_translation([gx + k * (cell[0] + GAP) + (cell[0] - m.extents[0]) / 2,
                                 gy + r * (cell[1] + GAP) + (cell[1] - m.extents[1]) / 2, 0])
            placed.append((code, m))
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            a, c = placed[i][1].bounds, placed[j][1].bounds
            assert np.maximum(a[0][:2] - c[1][:2], c[0][:2] - a[1][:2]).max() >= GAP - 1e-6, (placed[i][0], placed[j][0])
    for code, m in placed:
        assert m.is_watertight and m.bounds[0][2] > -1e-6 and m.bounds[1][:2].max() < BED and m.bounds[0][:2].min() > 0
    return placed, info


def stats(placed):
    out = []
    for code, m in placed:
        n, c, a = m.face_normals, m.triangles_center, m.area_faces
        on_bed = a[(n[:, 2] < -0.99) & (c[:, 2] < 0.01)].sum()
        out.append((code, on_bed, m.extents[2], m.volume))
    return out


def page(placed, info, st):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.suptitle("PLA print plate: the parts still to print for the rig (Bambu A1)", fontsize=13,
                 fontweight="bold", x=0.03, ha="left", y=0.975)
    fig.text(0.03, 0.935, "print_ready/plates/PLA_rig_parts_A1.stl / .3mf  ·  made by scripts/make_pla_plate.py  ·  "
             "partner of TPU_rig_modules_A1 (the 12 TPU modules)", fontsize=8, color="0.3")
    ax = fig.add_axes([0.03, 0.44, 0.44, 0.47])
    ax.add_patch(plt.Rectangle((0, 0), BED, BED, fc="0.96", ec="0.6"))
    allb = np.array([m.bounds for _, m in placed])
    for code, m in placed:
        col = "#7a9a4a" if code in ("RIG", "ADP", "PUL") else "#8a6fb0"
        for t in m.triangles[m.face_normals[:, 2] > 0.05][:, :, :2]:
            ax.fill(t[:, 0], t[:, 1], color=col, lw=0)
        bx = m.bounds
        ax.text((bx[0][0] + bx[1][0]) / 2, bx[1][1] + 1.5, code, ha="center", va="bottom", fontsize=7.5, fontweight="bold")
    pad = 12
    ax.set_xlim(allb[:, 0, 0].min() - pad, allb[:, 1, 0].max() + pad)
    ax.set_ylim(allb[:, 0, 1].min() - pad, allb[:, 1, 1].max() + pad)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=7)
    ax.set_title("Top view, bed coordinates (mm); green: rig parts, purple: phalanges", fontsize=8.5)
    ax3 = fig.add_axes([0.50, 0.44, 0.48, 0.47], projection="3d")
    zmax = allb[:, 1, 2].max()
    for code, m in placed:
        shade = 0.45 + 0.5 * np.clip(m.face_normals @ np.array([0.3, -0.5, 0.8]), 0, 1)
        base = np.array([0.48, 0.60, 0.29]) if code in ("RIG", "ADP", "PUL") else np.array([0.54, 0.44, 0.69])
        ax3.add_collection3d(Poly3DCollection(m.triangles, facecolors=np.clip(base * shade[:, None] + 0.15, 0, 1),
                                              edgecolors="none"))
    xs, ys = (allb[:, 0, 0].min(), allb[:, 1, 0].max()), (allb[:, 0, 1].min(), allb[:, 1, 1].max())
    ax3.set_xlim(*xs); ax3.set_ylim(*ys); ax3.set_zlim(0, zmax)
    ax3.set_box_aspect((xs[1] - xs[0], ys[1] - ys[0], zmax))
    ax3.view_init(elev=30, azim=-60)
    ax3.set_axis_off()
    ax3.set_title("As placed on the bed", fontsize=8.5)

    ax_t = fig.add_axes([0.03, 0.265, 0.94, 0.16])
    ax_t.axis("off")
    rows = [[c, info[c][3], info[c][4], f"{h:.1f}", f"{b:.0f}", f"{v / 1000:.1f}"] for c, b, h, v in st]
    half = (len(rows) + 1) // 2
    hdr = ["Label", "Part, as placed", "Used with", "Height mm", "On bed mm²", "Vol cm³"]
    for i, chunk in enumerate((rows[:half], rows[half:])):
        t = ax_t.table(cellText=chunk, colLabels=hdr, bbox=[i * 0.505, 0, 0.495, 1],
                       colWidths=[0.08, 0.36, 0.16, 0.12, 0.14, 0.11])
        t.auto_set_font_size(False)
        t.set_fontsize(6.8)
        for (r, cc), cell in t.get_celld().items():
            cell.set_edgecolor("0.75")
            if r == 0:
                cell.set_facecolor("#dde6f0")
            elif cc in (1, 2):
                cell._loc = "left"
                cell.get_text().set_ha("left")
    tot = sum(s[3] for s in st) / 1000
    fig.text(0.03, 0.243, f"{len(st)} parts, {tot:.0f} cm³ (about {tot * 1.24 * 0.75:.0f}–{tot * 1.24:.0f} g of PLA at 50 % "
             "infill). Left off as already printed: " + ", ".join(c for c, *_ in PARTS if c in PRINTED) + ". "
             "Phalanx 3 is not needed on the rig.",
             fontsize=7.5)
    ax_s = fig.add_axes([0.03, 0.02, 0.94, 0.215])
    ax_s.axis("off")
    t = ax_s.table(cellText=[[a, b] for a, b in SETTINGS], colLabels=["Bambu Studio setting", "Value"],
                   bbox=[0, 0, 1, 1], colWidths=[0.16, 0.84])
    t.auto_set_font_size(False)
    t.set_fontsize(6.8)
    for (r, cc), cell in t.get_celld().items():
        cell.set_edgecolor("0.75")
        if r == 0:
            cell.set_facecolor("#dde6f0")
        else:
            cell._loc = "left"
            cell.get_text().set_ha("left")
            cell.PAD = 0.01 if cc == 1 else 0.03
            if cc == 0:
                cell.get_text().set_fontweight("bold")
    with PdfPages(OUT / "PLA_rig_parts_A1.pdf") as pdf:
        pdf.savefig(fig)
    fig.savefig(OUT / "PLA_rig_parts_A1.png", dpi=110)
    plt.close(fig)


def main():
    placed, info = build()
    st = stats(placed)
    OUT.mkdir(parents=True, exist_ok=True)
    trimesh.util.concatenate([m for _, m in placed]).export(OUT / "PLA_rig_parts_A1.stl")
    scene = trimesh.Scene()
    for code, m in placed:
        scene.add_geometry(m, node_name=code, geom_name=code)
    scene.export(OUT / "PLA_rig_parts_A1.3mf")
    page(placed, info, st)
    for s in st:
        print("%-4s on bed %6.0f mm²  h %5.1f  vol %6.0f" % s)


if __name__ == "__main__":
    main()
