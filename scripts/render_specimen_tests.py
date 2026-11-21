"""Figures for docs/12-tpu-specimen-test-procedure.md.

    python scripts/render_specimen_tests.py

Writes docs/figures/specimen_tests/:
  print_orientation.png  the three specimen types as they sit on the print bed (labelled files)
  tension_setup.png      hanging-weight tension test, side view, with the gauge marks
  compression_setup.png  cylinder pressed on a kitchen scale
  worked_example.png     stress-strain points and the 2-10 % slope (an illustration at 12 MPa)
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mp  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "figures" / "specimen_tests"
SPEC = REPO / "print_ready" / "specimens"
RIG = REPO / "TYPE B" / "round2" / "test_rig"
TPU = (0.33, 0.52, 0.78)
PLA = (0.80, 0.80, 0.82)
INK = "#222222"
NOTE = "#b5481d"


# ---------------------------------------------------------------- 1. print orientation
def shaded(ax, mesh, colour, light=(0.4, -0.6, 0.9)):
    tris = mesh.vertices[mesh.faces]
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    L = np.asarray(light) / np.linalg.norm(light)
    s = 0.35 + 0.65 * np.abs(n @ L)
    col = np.clip(np.array(colour)[None, :] * s[:, None] + 0.12 * s[:, None], 0, 1)
    ax.add_collection3d(Poly3DCollection(tris, facecolors=col, edgecolors="none"))


def bed(ax, x0, x1, y0, y1, step=5.0):
    xs = np.arange(math.floor(x0 / step) * step, x1 + 1e-6, step)
    ys = np.arange(math.floor(y0 / step) * step, y1 + 1e-6, step)
    for x in xs:
        ax.plot([x, x], [y0, y1], [0, 0], color="#9a9a9a", lw=0.4)
    for y in ys:
        ax.plot([x0, x1], [y, y], [0, 0], color="#9a9a9a", lw=0.4)


def on_bed(mesh):
    m = mesh.copy()
    b = m.bounds
    m.apply_translation([-(b[0][0] + b[1][0]) / 2, -(b[0][1] + b[1][1]) / 2, -b[0][2]])
    return m


def print_orientation():
    cases = [
        (SPEC / "F1-1_tensile_1BA_t1.0_flat.stl", "Dog-bones F1 / F2: FLAT",
         "75 × 10 mm, 1.0 or 2.0 mm thick\nlabel on top of one wide end\nno brim, no supports", (35, -60)),
        (SPEC / "E1-1_tensile_strip_t1.0_edge.stl", "Edge strips E1 / E2: ON THEIR EDGE",
         "80 long, 6 mm TALL, 1.0 or 2.0 mm thick\n(thin side down, like the joint leaves)\n5 mm outer brim", (30, -55)),
        (RIG / "compression_d10_h10.stl", "Cylinders C1–C3: ON A FLAT END",
         "Ø10 × 10 mm\nno brim, no supports\nwrite C1, C2, C3 on them after", (28, -50)),
    ]
    fig = plt.figure(figsize=(13, 4.6))
    for i, (path, title, note, view) in enumerate(cases):
        ax = fig.add_subplot(1, 3, i + 1, projection="3d")
        m = on_bed(trimesh.load(path, force="mesh"))
        b = m.bounds
        half = max(b[1][0] - b[0][0], b[1][1] - b[0][1]) / 2 + 6
        bed(ax, -half, half, -half, half)
        if "edge" in path.name:      # the brim
            bw = 5.0
            x0, x1, y0, y1 = b[0][0] - bw, b[1][0] + bw, b[0][1] - bw, b[1][1] + bw
            brim = mp.Polygon([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            ax.add_collection3d(Poly3DCollection([[(x0, y0, 0.01), (x1, y0, 0.01), (x1, y1, 0.01), (x0, y1, 0.01)]],
                                                 facecolors=[(0.33, 0.52, 0.78, 0.25)], edgecolors=[TPU]))
            del brim
        shaded(ax, m, TPU)
        top = max(b[1][2], 8)
        ax.set_xlim(-half, half)
        ax.set_ylim(-half, half)
        ax.set_zlim(0, 2 * half * 0.35)
        ax.set_box_aspect((1, 1, 0.35))
        ax.view_init(*view)
        ax.set_axis_off()
        ax.set_title(title, fontsize=11, fontweight="bold", color=INK)
        ax.text2D(0.5, -0.02, note, transform=ax.transAxes, ha="center", va="top", fontsize=9, color=INK)
        del top
    fig.suptitle("How each specimen sits on the print bed (same spool, same session and presets as the joints; 3 of each)",
                 fontsize=11)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.2, wspace=0.02)
    fig.savefig(OUT / "print_orientation.png", dpi=170)
    plt.close(fig)


# ---------------------------------------------------------------- 2. tension set-up
def dogbone_outline(scale=1.0):
    """1BA outline in (across, along): 75 long, 10 wide ends, 5 wide x 30 parallel, R30."""
    L, b2, b1, l1, r = 75.0, 10.0, 5.0, 30.0, 30.0
    dx = math.sqrt(r * r - (r - (b2 - b1) / 2) ** 2)
    left = [(-L / 2, b2 / 2), (-l1 / 2 - dx, b2 / 2)]
    for i in range(1, 16):
        x = -l1 / 2 - dx + dx * i / 15
        left.append((x, b1 / 2 + r - math.sqrt(max(r * r - (x + l1 / 2) ** 2, 0.0))))
    upper = left + [(-x, y) for x, y in reversed(left)]
    poly = upper + [(x, -y) for x, y in reversed(upper)]
    return np.array([(y * scale, x * scale) for x, y in poly])     # vertical: along -> y


def arrow_dim(ax, x, y0, y1, text, side=1):
    ax.annotate("", (x, y0), (x, y1), arrowprops=dict(arrowstyle="<->", color=NOTE, lw=1.2))
    ax.text(x + side * 2, (y0 + y1) / 2, text, color=NOTE, fontsize=9, va="center",
            ha="left" if side > 0 else "right")


def callout(ax, n, xy, text, xytext):
    ax.annotate(f"{n}  {text}", xy, xytext, fontsize=9, color=INK, va="center",
                arrowprops=dict(arrowstyle="-", color="#777777", lw=0.8),
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#bbbbbb", lw=0.6))


def tension_setup():
    fig, ax = plt.subplots(figsize=(9.5, 8.4))
    # shelf
    ax.add_patch(mp.Rectangle((-40, 62), 80, 6, fc="#c9a77c", ec=INK, lw=0.8, hatch="///"))
    ax.text(-38, 70, "shelf / table edge (rigid)", fontsize=8.5, color=INK)
    # specimen (centre at y = 0, grip ends from 27.5 to 37.5 mm)
    pts = dogbone_outline()
    ax.add_patch(mp.Polygon(pts, fc=TPU, ec=INK, lw=0.8))
    # top clamp: two plates + bolts, holding the top 12 mm
    ax.add_patch(mp.Rectangle((-8.6, 26.5), 3.0, 12, fc=PLA, ec=INK, lw=0.8))
    ax.add_patch(mp.Rectangle((5.6, 26.5), 3.0, 12, fc=PLA, ec=INK, lw=0.8))
    ax.add_patch(mp.Rectangle((-1.2, 38.5), 2.4, 23.5, fc="#888888", ec=INK, lw=0.6))     # hanger
    for yb in (29.5, 35.5):
        ax.plot([-11, 11], [yb, yb], color="#555555", lw=2.2)
    # bottom clamp
    ax.add_patch(mp.Rectangle((-8.6, -38.5), 3.0, 12, fc=PLA, ec=INK, lw=0.8))
    ax.add_patch(mp.Rectangle((5.6, -38.5), 3.0, 12, fc=PLA, ec=INK, lw=0.8))
    for yb in (-29.5, -35.5):
        ax.plot([-11, 11], [yb, yb], color="#555555", lw=2.2)
    # hook, string, bag of weights
    ax.plot([0, 0], [-38.5, -46], color=INK, lw=1.2)
    ax.add_patch(mp.Arc((0, -48), 4, 4, theta1=180, theta2=360 + 90, color=INK, lw=1.2))
    ax.plot([-1.5, -9, None, 1.5, 9], [-49.5, -56, None, -49.5, -56], color=INK, lw=0.8)
    ax.add_patch(mp.FancyBboxPatch((-11, -72), 22, 16, boxstyle="round,pad=0.6", fc="#e8dcc2", ec=INK, lw=0.8))
    ax.text(0, -64, "weights\n(weighed on a\nkitchen scale)", ha="center", va="center", fontsize=8)
    # gauge marks
    for ym in (10, -10):
        ax.plot([-3.2, 3.2], [ym, ym], color="k", lw=1.6)
    arrow_dim(ax, 6.5, -10, 10, "L₀ ≈ 20 mm\n(measure it)", side=1)
    # ruler and phone
    ax.add_patch(mp.Rectangle((-17, -22), 3, 44, fc="#f2e7a6", ec=INK, lw=0.6))
    for k in range(0, 45, 2):
        ax.plot([-17, -16 + (0.8 if k % 10 else 1.6)], [-22 + k, -22 + k], color=INK, lw=0.5)
    ax.text(-15.5, 23.5, "ruler, same\nplane", fontsize=7.5, ha="center")
    ax.add_patch(mp.FancyBboxPatch((-36, -4), 6, 11, boxstyle="round,pad=0.4", fc="#333333", ec=INK))
    ax.add_patch(mp.Circle((-30.5, 1.5), 1.0, fc="#88aadd", ec="white", lw=0.6))
    ax.plot([-33, -33], [-4.5, -40], color="#555555", lw=1.5)
    ax.plot([-38, -28], [-40, -40], color="#555555", lw=1.5)
    ax.text(-33, -43, "phone on a stand,\nsquare to the specimen", fontsize=7.5, ha="center", va="top")
    # callouts
    callout(ax, "1", (8.6, 32), "Top clamp: 2 plates + 2 bolts, sandpaper inside;\n    grip only the wide end", (16, 50))
    callout(ax, "2", (3, 10), "Two thin marker lines ~20 mm apart,\n    centred on the narrow part", (16, 22))
    callout(ax, "3", (2, -13), "Narrow part: measure width and\n    thickness at 3 points", (16, -10))
    callout(ax, "4", (8.6, -32), "Bottom clamp with a hook", (16, -30))
    callout(ax, "5", (11, -64), "Add load in steps (100 g for 1.0 mm,\n    200 g for 2.0 mm); wait 30 s; photograph\n    or measure the mark gap L", (16, -55))
    ax.text(16, -78, "First: stretch to ~15 % and back 3 times (conditioning).\n"
            "Strain = (L − L₀) / L₀     Stress = mass × 9.81 / area",
            fontsize=9, color=NOTE, va="top")
    ax.set_xlim(-42, 62)
    ax.set_ylim(-86, 74)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Tests A and B: tension with hanging weights (dog-bone shown; edge strips are hung the same way,\n"
                 "gripped by their outer 20 mm)", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(OUT / "tension_setup.png", dpi=170)
    plt.close(fig)


# ---------------------------------------------------------------- 3. compression set-up
def compression_setup():
    fig, ax = plt.subplots(figsize=(9.5, 7.2))
    # bench
    ax.add_patch(mp.Rectangle((-45, -6), 90, 4, fc="#c9a77c", ec=INK, lw=0.8, hatch="///"))
    # scale
    ax.add_patch(mp.FancyBboxPatch((-22, -2), 44, 7, boxstyle="round,pad=0.5", fc="#dddddd", ec=INK))
    ax.add_patch(mp.Rectangle((-8, 0.3), 9, 3, fc="#1d2b1d", ec=INK, lw=0.5))
    ax.text(-3.5, 1.8, "12.34 kg", color="#7CFC00", fontsize=7, ha="center", va="center", family="monospace")
    # bottom plate, cylinder, top plate
    ax.add_patch(mp.Rectangle((-12, 6), 24, 3, fc="#9aa3ad", ec=INK, lw=0.8))
    ax.add_patch(mp.Rectangle((-5, 9), 10, 10, fc=TPU, ec=INK, lw=0.8))
    for yy in (9, 19):
        ax.plot([-5, 5], [yy, yy], color="#e0b000", lw=3, solid_capstyle="butt")
    ax.add_patch(mp.Rectangle((-12, 19), 24, 3, fc="#9aa3ad", ec=INK, lw=0.8))
    # C-clamp / press screw
    ax.add_patch(mp.Rectangle((-1.2, 22), 2.4, 14, fc="#777777", ec=INK, lw=0.6))
    ax.plot([-7, 7], [37, 37], color="#555555", lw=3)
    ax.annotate("", (0, 23), (0, 33), arrowprops=dict(arrowstyle="-|>", color=NOTE, lw=1.8))
    ax.text(9, 37, "press down slowly and hold:\ndrill press, C-clamp over the bench edge,\nor a bolt through a plate", fontsize=8.5, va="center")
    # caliper across plates
    ax.plot([17, 17], [6, 22], color=NOTE, lw=1)
    ax.plot([14, 20], [6, 6], color=NOTE, lw=1)
    ax.plot([14, 20], [22, 22], color=NOTE, lw=1)
    ax.text(21, 14, "calipers across both plates,\nminus the plates' thickness\n= cylinder height h", color=NOTE, fontsize=8.5,
            va="center")
    callout(ax, "1", (-5, 9.2), "Grease or oil on both flat ends", (-44, 14))
    callout(ax, "2", (-12, 20.5), "Rigid flat plates top and bottom", (-44, 24))
    callout(ax, "3", (-12, 2), "Scale to ~20 kg; zero it with\n    the top plate on", (-44, 3))
    ax.text(-44, -10, "Press in steps of 0.2 mm (2 % of the height) to about 1 mm (10 %); wait 30 s per step.\n"
            "Run each cylinder twice and use the second run.   Strain = (h₀ − h) / h₀   Stress = kg × 9.81 / (π d² / 4)",
            fontsize=9, color=NOTE, va="top")
    ax.set_xlim(-46, 52)
    ax.set_ylim(-18, 42)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Test C: compression of the Ø10 × 10 mm cylinder on a kitchen scale", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(OUT / "compression_setup.png", dpi=170)
    plt.close(fig)


# ---------------------------------------------------------------- 4. worked example
def worked_example():
    E = 12.0
    # neo-Hookean, uniaxial: engineering stress = (E/3) (lam - 1/lam^2); the FEA's material
    lam = np.linspace(1, 1.2, 200)
    sig = E / 3 * (lam - lam ** -2)
    A = 5.0                                   # 1.0 mm dog-bone, 100 g steps
    masses = np.arange(0, 1.1, 0.1)
    s_pts = masses * 9.81 / A
    eps_pts = np.interp(s_pts, sig, lam - 1)
    rng = np.random.default_rng(3)
    eps_meas = eps_pts + rng.normal(0, 0.0008, len(eps_pts)) * (eps_pts > 0)
    win = (eps_meas >= 0.02) & (eps_meas <= 0.10)
    lm = 1 + eps_meas[win]
    Ei = 3 * s_pts[win] / (lm - lm ** -2)
    E_fit = Ei.mean()
    slope = np.polyfit(eps_meas[win], s_pts[win], 1)[0]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.8), gridspec_kw=dict(width_ratios=[1.5, 1]))
    a0 = ax[0]
    a0.axvspan(2, 10, color="#2a7ab9", alpha=0.08)
    a0.plot(eps_meas * 100, s_pts, "o", color=INK, ms=5, label="one reading per load step (100 g)")
    a0.plot((lam - 1) * 100, E_fit / 3 * (lam - lam ** -2), "-", color=NOTE, lw=1.4,
            label=f"TPU curve with the fitted E = {E_fit:.1f} MPa")
    a0.text(6, 0.12, "use the rows from\n2 % to 10 % strain", ha="center", color="#2a7ab9", fontsize=9)
    a0.set(xlabel="strain ε (%)  = (L − L₀) / L₀ × 100", ylabel="stress σ (MPa)  = mass × 9.81 / area",
           xlim=(0, 16), ylim=(0, 2.1))
    a0.grid(alpha=0.3)
    a0.legend(fontsize=8.5, loc="upper left", frameon=False)
    a0.set_title("Readings: illustration for a 1.0 mm dog-bone (5 mm²) at 12 MPa", fontsize=9.5)
    a1 = ax[1]
    a1.plot(eps_meas[win] * 100, Ei, "s", color=INK, ms=5, label="E for each row in the window")
    a1.axhline(E_fit, color=NOTE, lw=1.4, label=f"average = E = {E_fit:.1f} MPa")
    a1.axhline(slope, color="#999999", lw=1, ls=":", label=f"plain SLOPE = {slope:.1f} MPa (≈10 % low)")
    a1.set(xlabel="strain ε (%)", ylabel="E for the row (MPa)", xlim=(0, 12), ylim=(8, 14))
    a1.grid(alpha=0.3)
    a1.legend(fontsize=8.5, loc="lower left", frameon=False)
    a1.set_title("Per row:  E = 3σ ÷ ( (1+ε) − 1/(1+ε)² )", fontsize=9.5)
    fig.suptitle("Working out E (your readings replace the dots). TPU's curve bends over, so a straight-line SLOPE reads "
                 "about 10 % low; the per-row formula gives the E the analyses use.", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "worked_example.png", dpi=170)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print_orientation()
    tension_setup()
    compression_setup()
    worked_example()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
