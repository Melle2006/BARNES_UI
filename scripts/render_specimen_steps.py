"""Step-by-step pictures for tests A, B and C in docs/12-tpu-specimen-test-procedure.md.

    python scripts/render_specimen_steps.py

Writes docs/figures/specimen_tests/:
  steps_measure.png      section 1, steps 3-4: measuring each specimen and marking the gauge length
  steps_grips.png        section 2: building and hanging the grips (dog-bone and edge strip)
  steps_tension.png      section 3, steps 1-3: zero, conditioning, load steps and reading L
  steps_compression.png  section 4, steps 1-4: grease, stack and zero, press, measure h
Schematics, not to scale except the specimens themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mp  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from render_specimen_tests import dogbone_outline  # noqa: E402

OUT = REPO / "docs" / "figures" / "specimen_tests"
TPU = (0.33, 0.52, 0.78)
PLA = (0.82, 0.82, 0.84)
WOOD = "#c9a77c"
STEEL = "#8c8c8c"
INK = "#222222"
NOTE = "#b5481d"
GOOD = "#2e7d32"


# ---------------------------------------------------------------- drawing helpers
def panel(ax, title, xlim, ylim):
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=10, fontweight="bold", color=INK, loc="left")


def caption(ax, text, y=0.02):
    ax.text(0.5, y, text, transform=ax.transAxes, ha="center", va="bottom", fontsize=8.5, color=INK,
            wrap=True)


def dogbone_h(x0=0.0, y0=0.0, s=1.0):
    """1BA outline lying along x, centred at (x0, y0)."""
    p = dogbone_outline(s)
    return np.c_[p[:, 1] + x0, p[:, 0] + y0]


def dim(ax, p0, p1, text, off=(0, 0), colour=NOTE, fs=8, ha="center", va="center"):
    ax.annotate("", p0, p1, arrowprops=dict(arrowstyle="<->", color=colour, lw=1.0, shrinkA=0, shrinkB=0))
    mid = ((p0[0] + p1[0]) / 2 + off[0], (p0[1] + p1[1]) / 2 + off[1])
    ax.text(*mid, text, color=colour, fontsize=fs, ha=ha, va=va)


def caliper(ax, xa, xb, y, up=True, reading="", jaw=7.0):
    """Vernier calipers measuring between xa and xb (jaws vertical, beam above or below)."""
    s = 1 if up else -1
    yb = y + s * jaw
    ax.add_patch(mp.Rectangle((xa - 1.2, min(y, yb)), 1.2, jaw, fc=STEEL, ec=INK, lw=0.5))
    ax.add_patch(mp.Rectangle((xb, min(y, yb)), 1.2, jaw, fc=STEEL, ec=INK, lw=0.5))
    ax.add_patch(mp.Rectangle((xa - 4, yb if up else yb - 3), (xb - xa) + 26, 3, fc="#b0b0b0", ec=INK, lw=0.5))
    ax.add_patch(mp.Rectangle((xb + 4, yb + (3.6 if up else -9.6)), 15, 6, fc="#1d2b1d", ec=INK, lw=0.5))
    ax.text(xb + 11.5, yb + (6.6 if up else -6.6), reading, color="#7CFC00", fontsize=6.5, ha="center",
            va="center", family="monospace")


def clamp_plates(ax, x, y, w, h, gap, bolts=2, sand=True):
    """Two grip plates side by side (front view), specimen between them in a `gap`."""
    ax.add_patch(mp.Rectangle((x - gap / 2 - 3, y), 3, h, fc=PLA, ec=INK, lw=0.7))
    ax.add_patch(mp.Rectangle((x + gap / 2, y), 3, h, fc=PLA, ec=INK, lw=0.7))
    if sand:
        for sx in (-1, 1):
            ax.add_patch(mp.Rectangle((x + sx * gap / 2 - (0.6 if sx > 0 else 0), y + 1), 0.6, h - 2,
                                      fc="#d8b46a", ec="none"))
    for k in range(bolts):
        yy = y + h * (k + 1) / (bolts + 1)
        ax.plot([x - gap / 2 - 5, x + gap / 2 + 5], [yy, yy], color="#555555", lw=2.4, solid_capstyle="round")


def bag(ax, x, y, label="", w=16, h=14):
    ax.plot([x, x - w / 2 + 2, None, x, x + w / 2 - 2], [y, y - 5, None, y, y - 5], color=INK, lw=0.8)
    ax.add_patch(mp.FancyBboxPatch((x - w / 2, y - 5 - h), w, h, boxstyle="round,pad=0.5", fc="#e8dcc2",
                                   ec=INK, lw=0.8))
    if label:
        ax.text(x, y - 5 - h / 2, label, ha="center", va="center", fontsize=7.5)


def clock(ax, x, y, r=4, text="30 s"):
    ax.add_patch(mp.Circle((x, y), r, fc="white", ec=INK, lw=0.8))
    ax.plot([x, x], [y, y + r * 0.75], color=INK, lw=1)
    ax.plot([x, x + r * 0.55], [y, y], color=INK, lw=1)
    ax.text(x, y - r - 2, text, ha="center", va="top", fontsize=7.5, color=NOTE)


def ruler(ax, x, y0, y1, w=3):
    ax.add_patch(mp.Rectangle((x, y0), w, y1 - y0, fc="#f2e7a6", ec=INK, lw=0.6))
    for k in range(0, int(y1 - y0) + 1):
        L = 1.6 if k % 10 == 0 else (1.1 if k % 5 == 0 else 0.6)
        ax.plot([x, x + L], [y0 + k, y0 + k], color=INK, lw=0.4)


def hanging_specimen(ax, x, top, length=75.0, kind="dogbone", marks=True, stretch=0.0):
    """A specimen hanging from `top` downwards; returns the y of its bottom end."""
    if kind == "dogbone":
        p = dogbone_outline()
        p[:, 1] *= (1 + stretch)
        p = np.c_[p[:, 0] + x, p[:, 1] + top - length * (1 + stretch) / 2]
        ax.add_patch(mp.Polygon(p, fc=TPU, ec=INK, lw=0.7))
        mid = top - length * (1 + stretch) / 2
        half = 2.5
    else:
        L = 80 * (1 + stretch)
        ax.add_patch(mp.Rectangle((x - 3, top - L), 6, L, fc=TPU, ec=INK, lw=0.7))
        mid = top - L / 2
        half = 3
    if marks:
        for s in (1, -1):
            ym = mid + s * 10 * (1 + stretch)
            ax.plot([x - half - 0.6, x + half + 0.6], [ym, ym], color="k", lw=1.4)
    return top - (length if kind == "dogbone" else 80) * (1 + stretch), mid


# ---------------------------------------------------------------- 1. measuring and marking
def steps_measure():
    fig, axs = plt.subplots(2, 2, figsize=(12, 8.4))
    # 3a: dog-bone
    ax = axs[0, 0]
    panel(ax, "Step 3a: dog-bone, width and thickness at 3 points", (-45, 45), (-28, 30))
    ax.add_patch(mp.Polygon(dogbone_h(0, 6), fc=TPU, ec=INK, lw=0.7))
    for xx in (-10, 0, 10):
        ax.plot([xx, xx], [3.5, 8.5], color=NOTE, lw=1.2)
        ax.plot([xx], [6], "o", color=NOTE, ms=3)
    ax.text(0, 13, "width (≈5 mm) at the 3 red lines,\nall inside the narrow 30 mm part", ha="center",
            fontsize=8, color=NOTE)
    # side view below: thickness
    ax.add_patch(mp.Rectangle((-37.5, -14), 75, 2.0, fc=TPU, ec=INK, lw=0.7))
    for xx in (-10, 0, 10):
        ax.plot([xx], [-13], "o", color=NOTE, ms=3)
    ax.text(0, -8, "side view: thickness at the same 3 points", ha="center", fontsize=8, color=NOTE)
    dim(ax, (40, -14), (40, -12), " t", off=(2.5, 0), ha="left")
    caption(ax, "Close the calipers gently: TPU squashes. Average the 3 widths and the 3 thicknesses;\n"
                "area A = width × thickness.")
    # 3b: strip
    ax = axs[0, 1]
    panel(ax, "Step 3b: edge strip, height and thickness at 3 points", (-45, 45), (-28, 30))
    ax.add_patch(mp.Rectangle((-40, 3), 80, 6, fc=TPU, ec=INK, lw=0.7))
    for xx in (-15, 0, 15):
        ax.plot([xx, xx], [3, 9], color=NOTE, lw=1.2)
    ax.add_patch(mp.Rectangle((-40, 3), 20, 6, fc="none", ec=INK, lw=0.6, hatch="///"))
    ax.add_patch(mp.Rectangle((20, 3), 20, 6, fc="none", ec=INK, lw=0.6, hatch="///"))
    ax.text(-30, 11, "grip zone\n20 mm", ha="center", fontsize=7.5)
    ax.text(30, 11, "grip zone\n20 mm", ha="center", fontsize=7.5)
    ax.text(0, 14, "height (≈6 mm) at the 3 red lines,\nin the middle 40 mm", ha="center", fontsize=8,
            color=NOTE)
    ax.add_patch(mp.Rectangle((-40, -14), 80, 1.0, fc=TPU, ec=INK, lw=0.7))
    for xx in (-15, 0, 15):
        ax.plot([xx], [-13.5], "o", color=NOTE, ms=3)
    ax.text(0, -9, "top view: thickness (1.0 or 2.0 mm) at the same 3 points", ha="center", fontsize=8,
            color=NOTE)
    caption(ax, "Area A = height × thickness. The strip is pulled along its 80 mm length,\n"
                "the same way a joint leaf is stretched.")
    # 3c: cylinder
    ax = axs[1, 0]
    panel(ax, "Step 3c: cylinder, diameter at 3 heights and the height", (-30, 30), (-16, 22))
    ax.add_patch(mp.Rectangle((-5, -2), 10, 10, fc=TPU, ec=INK, lw=0.7))
    for yy in (0, 3, 6):
        ax.plot([-5, 5], [yy, yy], color=NOTE, lw=1.0)
    dim(ax, (-5, 10.5), (5, 10.5), "d at 3 heights (≈10 mm)", off=(0, 2))
    dim(ax, (8, -2), (8, 8), " h₀ (≈10 mm)", off=(1, 0), ha="left")
    caption(ax, "Area A = π d² ÷ 4 with the average d. Note h₀: compression strain is measured from it.")
    # 4: gauge marks
    ax = axs[1, 1]
    panel(ax, "Step 4: mark the gauge length, then measure L₀", (-45, 45), (-28, 30))
    ax.add_patch(mp.Polygon(dogbone_h(0, 4), fc=TPU, ec=INK, lw=0.7))
    for xm in (-10, 10):
        ax.plot([xm, xm], [1, 7], color="k", lw=1.6)
    dim(ax, (-10, 11), (10, 11), "L₀ ≈ 20 mm: measure the real gap to 0.02 mm", off=(0, 3))
    ax.add_patch(mp.Rectangle((-30, -12), 60, 4, fc="#f2e7a6", ec=INK, lw=0.6))
    for k in range(61):
        L = 2 if k % 10 == 0 else (1.4 if k % 5 == 0 else 0.8)
        ax.plot([-30 + k, -30 + k], [-8, -8 - L], color=INK, lw=0.4)
    ax.text(0, -17, "fine permanent marker, thin lines, square across;\ncentred on the narrow part "
                    "(strips: centred on the middle)", ha="center", fontsize=8)
    caption(ax, "These two lines are what you track under load. Thin, sharp lines read best in photos.")
    fig.suptitle("Before testing: measure every specimen and mark the tensile ones (section 1, steps 3 and 4)",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "steps_measure.png", dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- 2. grips
def steps_grips():
    fig, axs = plt.subplots(1, 3, figsize=(13, 6.2))
    # exploded clamp
    ax = axs[0]
    panel(ax, "a. One grip, pulled apart", (-30, 30), (-30, 30))
    xs = [-18, -11, -4, 3, 10]
    names = ["plate\n(PLA or wood,\n~20 × 25 × 3 mm)", "sandpaper", "specimen end", "sandpaper", "plate"]
    cols = [PLA, "#d8b46a", TPU, "#d8b46a", PLA]
    wid = [3, 0.8, 2, 0.8, 3]
    for i, (x, n, c, w) in enumerate(zip(xs, names, cols, wid)):
        ax.add_patch(mp.Rectangle((x, -10), w, 22, fc=c, ec=INK, lw=0.7))
        if i % 2 == 0:
            ax.text(x + w / 2, -13, n, ha="center", va="top", fontsize=7.5)
        else:
            ax.text(x + w / 2, 14, n, ha="center", va="bottom", fontsize=7.5)
    for yy in (-4, 6):
        ax.plot([-24, 18], [yy, yy], color="#555555", lw=2.2, ls="--")
        ax.add_patch(mp.Rectangle((-26, yy - 1.5), 2.5, 3, fc="#555555"))
        ax.add_patch(mp.Rectangle((18, yy - 1.5), 2.5, 3, fc="#777777"))
    ax.text(-26, 21, "2 × M3 bolts + nuts", fontsize=8)
    caption(ax, "Sandpaper (grit side to the specimen) stops the TPU slipping.\n"
                "Tighten firmly but do not crush or cut into it.")
    # dog-bone in grips, front view
    ax = axs[1]
    panel(ax, "b. Dog-bone: grip only the wide ends", (-30, 30), (-48, 50))
    bot, mid = hanging_specimen(ax, 0, 37.5, kind="dogbone")
    clamp_plates(ax, 0, 26, 0, 12, 10)
    clamp_plates(ax, 0, -38, 0, 12, 10)
    ax.plot([0, 0], [38, 48], color=STEEL, lw=3)
    ax.add_patch(mp.Rectangle((-25, 47), 50, 3, fc=WOOD, ec=INK, lw=0.6, hatch="///"))
    ax.plot([0, 0], [-38, -41], color=INK, lw=1)
    ax.text(14, 30, "top grip:\nwide end only", fontsize=7.5)
    ax.text(14, -34, "bottom grip\n+ hook", fontsize=7.5)
    ax.text(10, 0, "narrow part\nhangs free", fontsize=7.5, color=NOTE)
    caption(ax, "The grips must not reach the narrow 30 mm part,\nor the specimen breaks or slips at the grip.")
    # strip in grips
    ax = axs[2]
    panel(ax, "c. Edge strip: grip the outer 20 mm", (-30, 30), (-48, 50))
    hanging_specimen(ax, 0, 40, kind="strip")
    clamp_plates(ax, 0, 21, 0, 19, 6)
    clamp_plates(ax, 0, -40, 0, 19, 6)
    ax.plot([0, 0], [40, 48], color=STEEL, lw=3)
    ax.add_patch(mp.Rectangle((-25, 47), 50, 3, fc=WOOD, ec=INK, lw=0.6, hatch="///"))
    ax.text(10, 30, "top 20 mm\ngripped", fontsize=7.5)
    ax.text(10, -31, "bottom 20 mm\ngripped", fontsize=7.5)
    ax.text(10, 0, "middle 40 mm\nfree, marks here", fontsize=7.5, color=NOTE)
    caption(ax, "Hang it with the 6 mm height facing you, so the marks\nand the ruler are in the same plane for photos.")
    fig.suptitle("Building the grips (section 2): the top grip hangs from a shelf, the bottom grip carries a hook "
                 "for the load bag", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "steps_grips.png", dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- 3. tension steps
def tension_frame(ax, stretch=0.0, bag_label="", with_shelf=True):
    if with_shelf:
        ax.add_patch(mp.Rectangle((-25, 52), 50, 3, fc=WOOD, ec=INK, lw=0.6, hatch="///"))
        ax.plot([0, 0], [41, 52], color=STEEL, lw=3)
    bot, mid = hanging_specimen(ax, 0, 37.5, kind="dogbone", stretch=stretch)
    clamp_plates(ax, 0, 26, 0, 12, 10)
    clamp_plates(ax, 0, bot - 0.5, 0, 12, 10)
    ax.plot([0, 0], [bot - 0.5, bot - 6], color=INK, lw=1)
    bag(ax, 0, bot - 6, bag_label)
    return bot, mid


def steps_tension():
    fig, axs = plt.subplots(1, 4, figsize=(15, 7.4))
    # 1: zero
    ax = axs[0]
    panel(ax, "Step 1: empty bag = zero", (-30, 34), (-98, 58))
    bot, mid = tension_frame(ax, 0.0, "empty\nbag")
    dim(ax, (9, mid - 10), (9, mid + 10), " L₀", off=(1, 0), ha="left")
    caption(ax, "Hang it with only the empty bag (and the bottom grip).\nMeasure L₀ again here: this is the zero point.")
    # 2: conditioning
    ax = axs[1]
    panel(ax, "Step 2: condition it 3 times", (-30, 34), (-98, 58))
    bot, mid = tension_frame(ax, 0.15, "≈15 %\nmass")
    ax.annotate("", (24, 10), (24, -20), arrowprops=dict(arrowstyle="<->", color=NOTE, lw=1.4,
                                                        connectionstyle="arc3,rad=0.5"))
    ax.text(28, -5, "load,\nunload,\n× 3", fontsize=8, color=NOTE, va="center")
    caption(ax, "Load to the mass in the table (≈15 % stretch), take it off,\nrepeat 3 times. Then start the real readings.")
    # 3: load steps
    ax = axs[2]
    panel(ax, "Step 3: add a step, wait 30 s, read L", (-30, 34), (-98, 58))
    bot, mid = tension_frame(ax, 0.06, "+100 g\n(+200 g for\n2.0 mm)")
    dim(ax, (9, mid - 10.6), (9, mid + 10.6), " L", off=(1, 0), ha="left")
    clock(ax, 22, 30)
    caption(ax, "Add one step, wait 30 s, then record the total mass and L.\nKeep going to at least 15 % strain.")
    # 3b: reading L from a photo
    ax = axs[3]
    panel(ax, "Step 3: reading L from a photo", (-24, 26), (-52, 40))
    ax.add_patch(mp.FancyBboxPatch((-20, -30), 40, 62, boxstyle="round,pad=1.2", fc="#2b2b2b", ec=INK))
    ax.add_patch(mp.Rectangle((-17, -26), 34, 54, fc="#f5f5f5", ec="none"))
    ax.add_patch(mp.Rectangle((-3, -26), 6, 54, fc=TPU, ec=INK, lw=0.6))
    for ym in (-10.6, 10.6):
        ax.plot([-3.4, 3.4], [ym, ym], color="k", lw=1.4)
    ruler(ax, 6, -24, 26)
    ax.plot([-3.4, 9], [10.6, 10.6], color=NOTE, lw=0.6, ls=":")
    ax.plot([-3.4, 9], [-10.6, -10.6], color=NOTE, lw=0.6, ls=":")
    ax.text(0, -36, "phone square on, ruler touching the specimen's face;\nread both marks against the ruler "
                    "(or measure in a photo app)", ha="center", fontsize=7.5)
    caption(ax, "Calipers also work: touch the jaw tips to the marks\nwithout squeezing the specimen.", y=-0.02)
    fig.suptitle("Tests A and B, tension (section 3, steps 1–3); dog-bone shown, edge strips are done the same way",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "steps_tension.png", dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- 4. compression steps
def stack(ax, h=10.0, plate_t=3.0, scale_text="0.00 kg", press=False, grease=True):
    ax.add_patch(mp.FancyBboxPatch((-18, -8), 36, 6, boxstyle="round,pad=0.5", fc="#dddddd", ec=INK))
    ax.add_patch(mp.Rectangle((-6, -6.6), 10, 3, fc="#1d2b1d", ec=INK, lw=0.5))
    ax.text(-1, -5.1, scale_text, color="#7CFC00", fontsize=6.5, ha="center", va="center", family="monospace")
    ax.add_patch(mp.Rectangle((-10, -1.5), 20, plate_t, fc="#9aa3ad", ec=INK, lw=0.7))
    y0 = -1.5 + plate_t
    w = 10 * (10 / h) ** 0.5
    ax.add_patch(mp.Rectangle((-w / 2, y0), w, h, fc=TPU, ec=INK, lw=0.7))
    if grease:
        for yy in (y0, y0 + h):
            ax.plot([-w / 2, w / 2], [yy, yy], color="#e0b000", lw=3, solid_capstyle="butt")
    ax.add_patch(mp.Rectangle((-10, y0 + h), 20, plate_t, fc="#9aa3ad", ec=INK, lw=0.7))
    top = y0 + h + plate_t
    if press:
        ax.add_patch(mp.Rectangle((-1.2, top), 2.4, 10, fc="#777777", ec=INK, lw=0.6))
        ax.plot([-6, 6], [top + 10.5, top + 10.5], color="#555555", lw=3)
        ax.annotate("", (0, top + 0.5), (0, top + 8), arrowprops=dict(arrowstyle="-|>", color=NOTE, lw=1.6))
    return y0, top


def steps_compression():
    fig, axs = plt.subplots(1, 4, figsize=(15, 5.6))
    ax = axs[0]
    panel(ax, "Step 1: grease both ends", (-20, 20), (-14, 26))
    ax.add_patch(mp.Rectangle((-5, 2), 10, 10, fc=TPU, ec=INK, lw=0.7))
    for yy in (2, 12):
        ax.plot([-5, 5], [yy, yy], color="#e0b000", lw=4, solid_capstyle="butt")
    ax.text(0, 16, "a thin smear of grease or a\ndrop of oil on each flat end", ha="center", fontsize=8,
            color="#9a7a00")
    caption(ax, "So the ends can spread sideways freely.\nDry ends grip the plates and read too stiff.")
    ax = axs[1]
    panel(ax, "Step 2: stack it, zero the scale", (-20, 20), (-14, 26))
    y0, top = stack(ax, scale_text="0.00 kg")
    ax.text(12, 10, "top plate on,\nthen press\nTARE / zero", fontsize=8, color=NOTE)
    caption(ax, "Scale → flat plate → cylinder → flat plate.\nZero the scale with the top plate resting on it.")
    ax = axs[2]
    panel(ax, "Step 3: press 0.2 mm, wait 30 s", (-20, 20), (-14, 32))
    y0, top = stack(ax, h=9.8, scale_text="1.96 kg", press=True)
    clock(ax, 14, 18)
    ax.text(0, 27, "drill press, C-clamp or a bolt through a plate", fontsize=7.5, ha="center")
    caption(ax, "Press down about 0.2 mm (2 % of 10 mm) and hold it.\nWait 30 s, then read the scale.")
    ax = axs[3]
    panel(ax, "Step 3 (cont.): measure h, read the scale", (-20, 26), (-14, 26))
    y0, top = stack(ax, h=9.8, scale_text="1.96 kg")
    ax.plot([13, 13], [-1.5, top], color=NOTE, lw=1)
    ax.plot([11, 15], [-1.5, -1.5], color=NOTE, lw=1)
    ax.plot([11, 15], [top, top], color=NOTE, lw=1)
    ax.text(16, (top - 1.5) / 2, "calipers across\nboth plates\n− 2 × plate\nthickness\n= h", fontsize=8,
            color=NOTE, va="center")
    caption(ax, "Record the scale reading and h at every step, to about 1.0 mm (10 %).\n"
                "Run each cylinder twice; use the second run.")
    fig.suptitle("Test C, compression (section 4, steps 1–4)", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "steps_compression.png", dpi=160)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    steps_measure()
    steps_grips()
    steps_tension()
    steps_compression()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
