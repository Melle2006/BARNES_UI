"""Engrave an ID onto every part selected for printing, and write the mapping.

    python scripts/label_print_parts.py          # needs cadquery

Writes labelled STL + STEP files to print_ready/ and the code -> part mapping to
print_ready/LABELS.md and print_ready/labels.csv. The source CAD is not touched.

Where the labels go, and why there
----------------------------------
* **Type B joint modules (TPU).** On the end face of the proximal tab, either side
  of the tendon and sensor channels. Everything else on a module is either flexing
  (leaves, strips, bearings), crowded (the tab's top and bottom faces carry the
  retention-pin holes and the sensor channel), or rounded (the tab's sides are
  mostly corner radius). The end face sits in the PLA socket, so the label is read
  with the module out of the finger. The design letter (and copy number) is on one
  side of the channels and the joint letter on the other. The MCP module also has
  a label on the top edge of its flange, which stays visible in the hand.
* **PLA phalanges.** On the side face, in the solid middle between the two sockets.
* **Tensile specimens.** On one grip end, outside the gauge length.

Every label is engraved (cut), never raised, so no fit or contact face changes.
Each one is checked: a slab of the label's shape, ``wall`` mm thick, directly
beneath the engraving must lie wholly inside material, so the label never breaks
into a channel, pin hole or socket.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import cadquery as cq

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "print_ready"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TB = REPO / "TYPE B"

#: Type B designs. Letters skip D, M and P so a design never reads as a joint.
DESIGNS = [
    ("A", "B5_t200_a45_deep", TB / "round2/deep_offset/B5_t200_a45_deep",
     "B5 crossed strip t2.0 / 45°, deep tendon", 2),
    ("B", "B5_t150_a45", TB / "B5_crossed_strip/B5_t150_a45",
     "B5 crossed strip t1.5 / 45°, as built", 2),
    ("C", "B4_t100_a60_deep", TB / "round2/deep_offset/B4_t100_a60_deep",
     "B4 rolling contact t1.0 / 60°, deep tendon", 1),
    ("E", "B8_y20_r125_deep", TB / "round2/deep_offset/B8_y20_r125_deep",
     "B8 knuckle 2 mm dorsal, r1.25, deep tendon", 1),
    ("F", "B8_y00_r150", TB / "round2/B8_y00_r150",
     "B8 knuckle central, r1.5, as built", 1),
    ("G", "B3_t150_w30", TB / "B3_dual_leaf/B3_t150_w30",
     "B3 dual leaf t1.5 / w3.0, as built (optional control)", 1),
]
#: joint letter, file, end carrying the label and its tab (w, h, corner r), and the
#: tab at the other end, which carries the copy number when there is more than one
JOINTS = [
    ("M", "01_MCP_module_with_flange", "distal", (11.0, 9.0, 3.54), None),
    ("P", "03_PIP_module", "proximal", (11.0, 9.0, 3.54), (9.0, 7.0, 2.7)),
    ("D", "05_DIP_module", "proximal", (9.0, 7.0, 2.7), None),
]
JOINT_NAME = {"M": "MCP", "P": "PIP", "D": "DIP"}
PHALANGES = [
    ("S", TB / "common_phalanges", "Type B phalanges, standard (as-built) tendon"),
    ("X", TB / "round2/deep_offset/deep_phalanges", "Type B phalanges, deep tendon"),
]
PHALANX_FILES = [("1", "02_Phalanx1"), ("2", "04_Phalanx2"), ("3", "06_Phalanx3")]
RIG = TB / "round2/test_rig"
SPECIMENS = [
    ("F1", "tensile_1BA_t1.0_flat", "Tensile dog-bone 1BA, 1.0 mm, printed flat"),
    ("F2", "tensile_1BA_t2.0_flat", "Tensile dog-bone 1BA, 2.0 mm, printed flat"),
    ("E1", "tensile_strip_t1.0_edge", "Tensile strip 1.0 mm, printed on edge"),
    ("E2", "tensile_strip_t2.0_edge", "Tensile strip 2.0 mm, printed on edge"),
]
SPECIMEN_COPIES = 3

DEPTH_TPU = 0.4
DEPTH_PLA = 0.6
DEPTH_SPECIMEN = 0.3


# ---------------------------------------------------------------------------
# text geometry
# ---------------------------------------------------------------------------
def _glyph_box(txt):
    """Width, height and centre offset of txt at fontsize 1, on XY."""
    bb = cq.Workplane("XY").text(txt, 1.0, 1.0, combine=False, fontPath=FONT,
                                 halign="center", valign="center").val().BoundingBox()
    return bb.xlen, bb.ylen, (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2


def fit_size(txt, max_w, max_h):
    w, h, _, _ = _glyph_box(txt)
    return min(max_w / w, max_h / h)


def text_prism(txt, size, centre, normal, xdir, z0, z1):
    """Text prism between z0 and z1 along ``normal`` (negative = into the part),
    centred on ``centre`` in the face, reading upright from outside."""
    _, _, cx, cy = _glyph_box(txt)
    n, x = cq.Vector(*normal).normalized(), cq.Vector(*xdir).normalized()
    y = n.cross(x)
    origin = cq.Vector(*centre) - x * (cx * size) - y * (cy * size) + n * z1
    plane = cq.Plane(origin=origin, xDir=x, normal=n)
    return cq.Workplane(plane).text(txt, size, z0 - z1, combine=False, fontPath=FONT,
                                    halign="center", valign="center").val()


class Labeller:
    def __init__(self, solid):
        self.solid = solid
        self.cuts = []
        self.checks = []

    def add(self, txt, size, centre, normal, xdir, depth, wall):
        self.cuts.append(text_prism(txt, size, centre, normal, xdir, -depth, 0.6))
        slab = text_prism(txt, size, centre, normal, xdir, -depth - wall, -depth)
        inside = slab.intersect(self.solid).Volume() / slab.Volume()
        self.checks.append((txt, round(size * _glyph_box(txt)[1], 2), wall, inside))
        if inside < 0.97:
            raise ValueError(f"label {txt!r}: only {100 * inside:.0f} % of the {wall} mm "
                             "beneath it is material; it would break into a cavity")

    def result(self):
        out = self.solid
        for c in self.cuts:
            out = out.cut(c)
        solids = out.Solids()
        assert len(solids) == 1, f"labelling split the part into {len(solids)} solids"
        return solids[0]


def load(path):
    return cq.importers.importStep(str(path)).val()


def save(shape, stem, sub):
    d = OUT / sub
    d.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(cq.Workplane().add(shape), str(d / f"{stem}.step"))
    cq.exporters.export(cq.Workplane().add(shape), str(d / f"{stem}.stl"),
                        tolerance=0.01, angularTolerance=0.1)
    return f"print_ready/{sub}/{stem}.stl"


# ---------------------------------------------------------------------------
# where the text goes on a tab end face
# ---------------------------------------------------------------------------
X_IN = 1.9          # clear of the Ø3 tendon channel at x = 0
EDGE = 0.35         # margin to the tab's outline


def _half_width(w, h, r, y):
    yc = h / 2 - r
    if abs(y) <= yc:
        return w / 2
    return (w / 2 - r) + math.sqrt(max(r * r - (abs(y) - yc) ** 2, 0.0))


def tab_zone(tab, glyphs):
    """Glyph size and zone (width, half-height) beside the channels that fits every
    one of ``glyphs`` (each set on its own, one per side)."""
    w, h, r = tab
    best = None
    for i in range(1, 80):
        y_lim = (h / 2 - EDGE) * i / 80
        width = _half_width(w, h, r, y_lim) - EDGE - X_IN
        if width <= 0:
            continue
        size = min(fit_size(g, width, 2 * y_lim) for g in glyphs)
        if best is None or size > best[0]:
            best = (size, width)
    return best


def _end_face(bb, end):
    """z of the end face, its outward normal, and the x direction that reads upright
    (dorsal, +Y, up) from outside."""
    if end == "proximal":
        return bb.zmin, (0, 0, -1), (-1, 0, 0)
    return bb.zmax, (0, 0, 1), (1, 0, 0)


def label_module(path, design, joint, end, tab, other_tab, copy):
    solid = load(path)
    bb = solid.BoundingBox()
    lab = Labeller(solid)
    # design letter on the reader's left of the channels, joint letter on the right
    size, width = tab_zone(tab, [design, joint])
    z, normal, xdir = _end_face(bb, end)
    s = 1 if end == "proximal" else -1          # reader's left is +x on the proximal face
    x = X_IN + width / 2
    lab.add(design, size, (s * x, 0.0, z), normal, xdir, DEPTH_TPU, 0.5)
    lab.add(joint, size, (-s * x, 0.0, z), normal, xdir, DEPTH_TPU, 0.5)
    if copy:
        other = "distal" if end == "proximal" else "proximal"
        csize, cwidth = tab_zone(other_tab, [str(copy)])
        z2, n2, x2 = _end_face(bb, other)
        s2 = 1 if other == "proximal" else -1
        lab.add(str(copy), csize, (s2 * (X_IN + cwidth / 2), 0.0, z2), n2, x2, DEPTH_TPU, 0.5)
    if joint == "M":
        # flange top edge (y = bb.ymax, below z = 0), read from the back of the hand
        code = f"{design}{copy or ''}-M"
        fsz = fit_size(code, 20.0, 2.6)
        lab.add(code, fsz, (0.0, bb.ymax, -2.0), (0, 1, 0), (-1, 0, 0), DEPTH_TPU, 0.8)
    return lab.result(), lab.checks


def label_phalanx(path, code):
    solid = load(path)
    bb = solid.BoundingBox()
    planes = sorted(f.Center().z for f in solid.Faces()
                    if f.geomType() == "PLANE" and abs(f.normalAt().z) > 0.99
                    and 0.5 < f.Center().z < bb.zmax - 0.5 and f.Area() > 30)
    z_lo = planes[0]                                     # proximal socket floor
    # distal socket floor; the fingertip phalanx has no distal socket
    z_hi = planes[-1] if len(planes) > 1 else bb.zmax - 1.5
    # Mid-length first; if something inside (the fingertip's tendon anchor hole)
    # is too close, try smaller text and other stations along the solid middle.
    for scale in (1.0, 0.8, 0.65):
        for frac in (0.5, 0.35, 0.65, 0.25, 0.75):
            zc = z_lo + frac * (z_hi - z_lo)
            room = 2 * min(zc - z_lo, z_hi - zc) - 1.0
            if room <= 2:
                continue
            x_s = _surface_x(solid, zc)
            lab = Labeller(solid)
            try:
                lab.add(code, scale * fit_size(code, room, 4.0), (x_s, 0.0, zc), (1, 0, 0), (0, 0, -1),
                        DEPTH_PLA, 0.8)
            except ValueError:
                continue
            return lab.result(), lab.checks
    raise ValueError(f"no clear place for {code} on {path.name}")


def _surface_x(solid, z):
    """Smallest x of the +X side surface over |y| < 2 at height z (the shallowest
    point, so the label depth is at least DEPTH_PLA everywhere)."""
    xs = []
    for y in (-2.0, -1.0, 0.0, 1.0, 2.0):
        for dz in (-3.0, 0.0, 3.0):
            pts = _ray_hits(solid, (30, y, z + dz), (-1, 0, 0))
            if pts:
                xs.append(max(pts))
    return min(xs)


def _ray_hits(solid, origin, direction):
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    hit = IntCurvesFace_ShapeIntersector()
    hit.Load(solid.wrapped, 1e-6)
    hit.Perform(gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), 0.0, 100.0)
    return [hit.Pnt(i).X() for i in range(1, hit.NbPnt() + 1)]


def label_specimen(path, code):
    solid = load(path)
    bb = solid.BoundingBox()
    lab = Labeller(solid)
    if "flat" in path.name:
        # top face of one grip end: grips are 10 wide, beyond |x| = 28
        size = fit_size(code, 8.0, 3.2)
        lab.add(code, size, (bb.xmax - 4.8, 0.0, bb.zmax), (0, 0, 1), (1, 0, 0), DEPTH_SPECIMEN, 0.4)
    else:
        # side face of one grip (the end 20 mm)
        size = fit_size(code, 14.0, 3.2)
        lab.add(code, size, (bb.xmax - 10.0, bb.ymax, (bb.zmin + bb.zmax) / 2), (0, 1, 0),
                (-1, 0, 0), DEPTH_SPECIMEN, 0.4)
    return lab.result(), lab.checks


def write_markdown(rows, checks):
    small = {c[0]: c[2] for c in checks}
    for c in checks:
        small[c[0]] = min(small[c[0]], c[2])
    L = ["# Print labels: what each engraved code means", "",
         "Generated by `scripts/label_print_parts.py`; the files here are the selected print files with an "
         "ID engraved (cut 0.4 mm into TPU, 0.6 mm into PLA, 0.3 mm into the specimens). Nothing else about "
         "the parts changed: labels are only on faces that sit in a socket, on the MCP flange edge, on the "
         "phalanx side and on specimen grips, and each was checked to leave at least 0.5 mm (TPU tabs), "
         "0.8 mm (PLA, MCP flange) or 0.4 mm (specimens) of material behind it.", "",
         "![label preview](label_preview.png)", "",
         "## How to read a Type B module", "",
         "Look at the **end face of the proximal tab** (the end that goes into the proximal phalanx; for the "
         "MCP module, the distal tab's end face, and the flange's top edge). With the back of the finger up, "
         "the **design letter** is on the left of the channels and the **joint letter** on the right.", "",
         "| Design letter | Design | Folder |", "|---|---|---|"]
    for letter, name, folder, desc, n in DESIGNS:
        L.append(f"| **{letter}** | {desc} | `{folder.relative_to(REPO)}` |")
    L += ["", "| Joint letter | Joint |", "|---|---|", "| **M** | MCP (module with flange) |",
          "| **P** | PIP (the module the rig tests) |", "| **D** | DIP |", "",
          "Letters D, M and P are never used for a design, so a design letter never reads as a joint. "
          "Where two copies are printed (the A and B PIP modules), the **copy number** is engraved on the "
          "other (distal) tab's end face.", "",
          "## Every labelled part", "",
          "| Code | Engraved | Part | Material | Label on | Smallest letter (mm) | File |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| **{r['code']}** | {r['reads']} | {r['part']} | {r['material']} | {r['label_on']} | "
                 f"{small.get(r['code'], 0):.1f} | [{Path(r['file']).name}]({Path(r['file']).relative_to('print_ready')}) |")
    L += ["", "## Not labelled", "",
          "* **Compression cylinders Ø10 × 10**: an engraving would spoil a loading face or change the "
          "section. Mark them with a pen.",
          "* **Rig parts (PLA)**: one of each, nothing to confuse.",
          "* **Type A springs (A8 with collars, A6)**: being re-fitted to the iteration 3 hand; they get "
          "labels when the new versions are generated.", "",
          "## Printing the labels", "",
          "The module labels are on a face that stands vertical when the module prints on its side, so the "
          "letters print as grooves in a wall: they come out cleanly at 0.4 mm line width and 0.2 mm layers. "
          "The DIP module letters are the smallest (about 2.1 mm tall); if they print soft, the design "
          "letter is still readable and the joint is obvious from the module's size."]
    (OUT / "LABELS.md").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------------------
def main():
    rows, checks = [], []
    for letter, name, folder, desc, pip_copies in DESIGNS:
        for j, fname, end, tab, other_tab in JOINTS:
            copies = range(1, pip_copies + 1) if (j == "P" and pip_copies > 1) else [None]
            for cp in copies:
                shape, ch = label_module(folder / f"{fname}.step", letter, j, end, tab, other_tab, cp)
                code = f"{letter}{cp or ''}-{j}"
                stem = f"{code}_{name}_{JOINT_NAME[j]}"
                path = save(shape, stem, "type_b_modules")
                where = ("proximal tab end face" if end == "proximal" else "distal tab end face") + \
                        (f"; copy number {cp} on the distal tab end face" if cp else "") + \
                        (f"; '{code}' on the flange top edge" if j == "M" else "")
                rows.append(dict(code=code, reads=f"{letter}  {j}" + (f"  (other end: {cp})" if cp else ""),
                                 part=f"{desc}: {JOINT_NAME[j]} module" + (f", copy {cp}" if cp else ""),
                                 material="TPU", label_on=where, file=path))
                checks += [(code,) + c for c in ch]
                print("ok", code)
    for code, folder, desc in PHALANGES:
        for n, fname in PHALANX_FILES:
            shape, ch = label_phalanx(folder / f"{fname}.step", f"{code}{n}")
            stem = f"{code}{n}_{folder.name}_{fname}"
            path = save(shape, stem, "type_b_phalanges")
            rows.append(dict(code=f"{code}{n}", reads=f"{code}{n}", part=f"{desc}: Phalanx {n}",
                             material="PLA", label_on="side face (+X), mid-length", file=path))
            checks += [(f"{code}{n}",) + c for c in ch]
            print("ok", code, n)
    for code, fname, desc in SPECIMENS:
        for cp in range(1, SPECIMEN_COPIES + 1):
            c = f"{code}-{cp}"
            shape, ch = label_specimen(RIG / f"{fname}.step", c)
            path = save(shape, f"{c}_{fname}", "specimens")
            rows.append(dict(code=c, reads=c, part=f"{desc}, copy {cp}", material="TPU",
                             label_on="one grip end", file=path))
            checks += [(c,) + x for x in ch]
            print("ok", c)

    with open(OUT / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(OUT / "label_checks.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "glyphs", "glyph_height_mm", "wall_checked_mm", "fraction_of_wall_in_material"])
        w.writerows([(a, b, c, d, round(e, 4)) for a, b, c, d, e in checks])
    write_markdown(rows, checks)
    print(len(rows), "parts;", len(checks), "labels; smallest glyph",
          min(c[2] for c in checks), "mm")


if __name__ == "__main__":
    main()
