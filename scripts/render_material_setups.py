"""Diagrams and animations of the material test rigs as built (from the setup video).

    python scripts/render_material_setups.py

Writes docs/report/figures/material/:
  tension_rig_asbuilt.png, compression_rig_asbuilt.png     still diagrams
  tension_rig.gif, compression_rig.gif                     animations
  tension_strip.png, compression_strip.png                 three animation frames side by side (for the PDF)

Tension: a long aluminium extrusion held in a bench vice overhangs the bench edge; a C-clamp
at its far end grips the top of the specimen; a steel angle bracket clamped to the lower end
is the bottom grip and the weight hanger. (An earlier version used a wooden arm with a bolt.)
Compression: an aluminium extrusion lever hinged on a steel bracket on a stack of wooden
blocks; its far end turns down into a leg that stands on a kitchen scale; the cylinder sits
on the lever next to the hinge, under the nose of a bench press. Schematic, not to scale.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mp  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "report" / "figures" / "material"
ALU = "#c4cad2"
ALU_D = "#8f99a6"
WOOD = "#c9a77c"
STEEL = "#4a4f57"
TPU = "#5585c8"
NOTE = "#b5481d"
INK = "#222222"


# ---------------------------------------------------------------- tension
def tension(ax, p=0.0, labels=True):
    """p: 0 = empty hanger, 1 = full load (specimen stretched about 15 %)."""
    ax.add_patch(mp.Rectangle((-60, -4), 70, 4, fc=WOOD, ec=INK, lw=0.7, hatch="///"))       # bench top
    for x in (-55, 2):
        ax.add_patch(mp.Rectangle((x, -60), 4, 56, fc=WOOD, ec=INK, lw=0.6))                  # legs
    ax.add_patch(mp.Rectangle((-30, 0), 16, 10, fc="#3a5fa8", ec=INK, lw=0.7))                # vice body
    ax.add_patch(mp.Rectangle((-34, 3), 4, 4, fc="#3a5fa8", ec=INK, lw=0.6))
    ax.plot([-44, -34], [5, 5], color=STEEL, lw=2)                                            # vice handle
    ax.add_patch(mp.Rectangle((-40, 6), 100, 3.5, fc=ALU, ec=INK, lw=0.7))                    # extrusion
    for x in np.arange(-38, 60, 6):
        ax.plot([x, x + 3], [7.75, 7.75], color=ALU_D, lw=0.6)
    # C-clamp at the far end
    ax.add_patch(mp.Rectangle((50, 1), 2.5, 13, fc="#c0392b", ec=INK, lw=0.6))
    ax.add_patch(mp.Rectangle((50, 13), 9, 2.2, fc="#c0392b", ec=INK, lw=0.6))
    ax.plot([57, 57], [9.5, 2], color=STEEL, lw=1.6)
    # specimen
    L0, Lb = 40.0, 40.0 * (1 + 0.15 * p)
    top = 3
    ax.add_patch(mp.Rectangle((55.5, top - Lb), 3, Lb, fc=TPU, ec=INK, lw=0.6))
    mid = top - Lb / 2
    for s in (1, -1):
        ax.plot([55, 59], [mid + s * 8 * (1 + 0.15 * p)] * 2, color="k", lw=1.3)
    bot = top - Lb
    # angle bracket bottom grip + hanger
    ax.add_patch(mp.Rectangle((54, bot - 1), 6, 7, fc=STEEL, ec=INK, lw=0.6))
    ax.add_patch(mp.Rectangle((54, bot - 2), 14, 2, fc=STEEL, ec=INK, lw=0.6))
    ax.plot([64, 64], [bot - 2, bot - 8], color=INK, lw=0.8)
    nw = int(round(p * 5))
    for i in range(max(1, nw)):
        ax.add_patch(mp.Rectangle((60, bot - 11 - i * 3.2), 8, 3, fc="#777777" if i < nw else "#e8dcc2", ec=INK, lw=0.5))
    # ruler and phone
    ax.add_patch(mp.Rectangle((63, mid - 15), 2.5, 30, fc="#f2e7a6", ec=INK, lw=0.5))
    ax.add_patch(mp.FancyBboxPatch((96, mid - 6), 6, 11, boxstyle="round,pad=0.4", fc="#333333", ec=INK))
    ax.plot([99, 99], [mid - 6.5, -60], color="#555555", lw=1.2)
    if labels:
        t = dict(fontsize=7.5, color=INK)
        ax.text(-40, 15, "bench vice", **t)
        ax.text(0, 13, "aluminium extrusion, overhanging the bench", **t)
        ax.text(60, 17, "C-clamp: top grip", **t)
        ax.text(53.5, mid, "marks\n~20 mm", fontsize=7.5, color=NOTE, ha="right", va="center")
        ax.text(70, bot - 1, "steel angle bracket:\nbottom grip + hanger", **t)
        ax.text(70, bot - 14, f"weights: {nw * 100} g added" if p else "empty hanger (zero)", fontsize=7.5, color=NOTE)
        ax.text(92, mid + 9, "phone + ruler\n(read the marks)", **t)
    ax.set_xlim(-62, 118)
    ax.set_ylim(-62, 22)
    ax.set_aspect("equal")
    ax.axis("off")


# ---------------------------------------------------------------- compression
def compression(ax, p=0.0, labels=True):
    """p: 0 = press just touching, 1 = about 1 mm (10 %) compression, exaggerated."""
    ax.add_patch(mp.Rectangle((-10, -4), 140, 4, fc=WOOD, ec=INK, lw=0.7, hatch="///"))       # bench
    # wooden block stack with the hinge bracket (right)
    ax.add_patch(mp.Rectangle((84, 0), 34, 14, fc=WOOD, ec=INK, lw=0.6))
    ax.add_patch(mp.Rectangle((86, 14), 30, 12, fc=WOOD, ec=INK, lw=0.6))
    for x in range(89, 114, 5):
        ax.add_patch(mp.Circle((x, 20), 0.9, fc="#7a5b3a", ec="none"))
    ax.add_patch(mp.Rectangle((96, 26), 5, 9, fc=STEEL, ec=INK, lw=0.6))                      # hinge bracket
    pivot = (98.5, 32.5)
    ax.add_patch(mp.Circle(pivot, 1.1, fc="white", ec=INK, lw=0.8))
    # kitchen scale (left)
    ax.add_patch(mp.FancyBboxPatch((0, 0), 26, 4, boxstyle="round,pad=0.5", fc="#dddddd", ec=INK))
    reading = 960 * p
    ax.add_patch(mp.Rectangle((4, 0.8), 13, 2.4, fc="#1d2b1d", ec=INK, lw=0.4))
    ax.text(10.5, 2.0, f"{reading:6.1f} g", color="#7CFC00", fontsize=6, ha="center", va="center", family="monospace")
    # lever: horizontal extrusion from the hinge to x = 13, then a leg down to the scale
    tilt = -0.25 * p                                                                           # degrees, exaggerated
    th = np.radians(tilt)

    def rot(x, y):
        dx, dy = x - pivot[0], y - pivot[1]
        return (pivot[0] + dx * np.cos(th) - dy * np.sin(th), pivot[1] + dx * np.sin(th) + dy * np.cos(th))
    beam = [rot(*q) for q in ((10, 31), (98.5, 31), (98.5, 34.5), (10, 34.5))]
    ax.add_patch(mp.Polygon(beam, fc=ALU, ec=INK, lw=0.7))
    leg = [rot(*q) for q in ((10, 4.5), (14, 4.5), (14, 34.5), (10, 34.5))]
    ax.add_patch(mp.Polygon(leg, fc=ALU, ec=INK, lw=0.7))
    ax.add_patch(mp.Rectangle((8, 4), 8, 1.2, fc=STEEL, ec=INK, lw=0.5))                      # foot on the scale
    # cylinder next to the hinge, under the press nose
    cx = 92.0
    h0 = 6.0
    h = h0 * (1 - 0.10 * p)
    w = 6.0 * (1 + 0.05 * p)
    base = rot(cx, 34.5)[1]
    ax.add_patch(mp.Rectangle((cx - w / 2, base), w, h, fc=TPU, ec=INK, lw=0.6))
    # press: column and head above
    top = base + h
    ax.add_patch(mp.Rectangle((cx - 2.5, top), 5, 4, fc="#999999", ec=INK, lw=0.6))           # nose
    ax.add_patch(mp.FancyBboxPatch((cx - 9, top + 4), 18, 22, boxstyle="round,pad=1.5", fc="#b9bec4", ec=INK, lw=0.7))
    ax.plot([cx + 9, cx + 24], [top + 18, top + 26 - 6 * p], color=STEEL, lw=2.2)              # handle
    ax.annotate("", (cx, top + 0.3), (cx, top + 9), arrowprops=dict(arrowstyle="-|>", color=NOTE, lw=1.6))
    # dimensions a and b
    if labels:
        for x in (pivot[0], cx, 12):
            ax.plot([x, x], [-5, -14], color=INK, lw=0.5, ls=":")
        ax.annotate("", (pivot[0], -8), (cx, -8), arrowprops=dict(arrowstyle="<->", color=INK, lw=0.7))
        ax.text(cx - 1.5, -8, "a", fontsize=8, ha="right", va="center")
        ax.annotate("", (pivot[0], -12.5), (12, -12.5), arrowprops=dict(arrowstyle="<->", color=INK, lw=0.7))
        ax.text(55, -11.3, "b ≈ 30 a (hinge to the leg)", fontsize=8, ha="center")
        t = dict(fontsize=7.5, color=INK)
        ax.text(100, 37, "hinge (steel bracket)", **t)
        ax.text(87, 9, "wooden blocks", **t)
        ax.text(30, 37, "aluminium extrusion lever", **t)
        ax.text(16, 10, "leg on the scale", **t)
        ax.text(cx - 11, base + 1, "cylinder", fontsize=7.5, color="#1f4e8c", ha="right")
        ax.text(cx - 11, top + 20, "bench press", fontsize=7.5, color=INK, ha="right")
        ax.text(0, -19, f"Force on the cylinder = 30 × scale reading.   Compression shown: {p * 10:.0f} % (exaggerated)",
                fontsize=7.5, color=NOTE)
    ax.set_xlim(-12, 132)
    ax.set_ylim(-22, 76)
    ax.set_aspect("equal")
    ax.axis("off")


# ---------------------------------------------------------------- output
def still(fn, path, title, size):
    fig, ax = plt.subplots(figsize=size)
    fn(ax, 0.6)
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def frames(fn, n, size):
    out = []
    for i in range(n):
        p = (np.sin(np.pi * (i / (n - 1) - 0.5)) + 1) / 2 if n > 1 else 0
        fig, ax = plt.subplots(figsize=size)
        fn(ax, p)
        fig.tight_layout()
        fig.canvas.draw()
        im = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert("RGB")
        out.append(im)
        plt.close(fig)
    return out


def gif(fn, path, size, n=16):
    fr = frames(fn, n, size)
    seq = fr + fr[::-1]
    seq[0].save(path, save_all=True, append_images=seq[1:], duration=120, loop=0, optimize=True)


def strip(fn, path, size, title):
    fr = [frames(lambda ax, p, q=q: fn(ax, q, labels=False), 1, size)[0] for q in (0.0, 0.5, 1.0)]
    w, h = fr[0].size
    c = Image.new("RGB", (w * 3, h + 40), "white")
    for i, im in enumerate(fr):
        c.paste(im, (i * w, 40))
    from PIL import ImageDraw
    d = ImageDraw.Draw(c)
    d.text((10, 10), title, fill=(30, 30, 30))
    c.save(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    still(tension, OUT / "tension_rig_asbuilt.png", "Tension rig as built (tests A and B)", (9, 4.6))
    still(compression, OUT / "compression_rig_asbuilt.png", "Compression rig as built: lever onto a kitchen scale (test C)", (9, 4.8))
    gif(tension, OUT / "tension_rig.gif", (7, 3.6))
    gif(compression, OUT / "compression_rig.gif", (7, 3.7))
    strip(tension, OUT / "tension_strip.png", (5, 2.6), "Tension: empty hanger -> half load -> full load (about 15 % strain)")
    strip(compression, OUT / "compression_strip.png", (5, 2.7), "Compression: press touching -> 5 % -> 10 % (exaggerated)")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
