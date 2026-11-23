"""Printable hinge pins for the pinned phalanges (H and K), as a fit-test set.

    python3 scripts/make_hinge_pins.py         # needs trimesh, manifold3d

The phalanges' pin holes are Ø2.05 on paper, but they print with their axis horizontal
(the phalanges stand on end), so they come out undersize and slightly oval. Rather than
guess the printer's error, each pin is made in three shank diameters; use the one that
pushes in by hand and turns. Each pin has

* a head (Ø4.0 × 0.8 mm) that stops it on the outside of the outer plate. The pins sit on
  the joint axis, so the head only turns in place and nothing reaches it;
* a shank exactly as long as the hole: H 2.5 mm (through H1's and H2's 1.2 mm plates and the
  0.2 mm gap, 2.6 mm, stopping 0.1 mm short of the inner face so it never touches the
  module); K 1.8 mm (through K1's plate into K2's blind hole, 1.85 mm deep), with a 0.25 mm
  lead-in chamfer;
* a grip tab joined to the head by a thin neck: hold the tab, push the pin in, then bend
  the tab off. The tab length tells the size: 6 mm = Ø1.60, 8 mm = Ø1.75, 10 mm = Ø1.90.

Pins lie on their side with a 0.15 mm flat on the bed, so the layers run along the pin and
the load shears across them (strong), not between them (weak).

Writes print_ready/plates/hinge_pins_fit_set.stl (6 per size: 4 for two H hinges, 2 for
one K) and print_ready/plates/pinned_phalanges_plate.stl (K1, K2, two H1/H2 sets and the
pin set).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

REPO = Path(__file__).resolve().parents[1]
PH = REPO / "print_ready" / "type_b_phalanges"
OUT = REPO / "print_ready" / "plates"
R = trimesh.transformations.rotation_matrix

SIZES = [(1.60, 6.0), (1.75, 8.0), (1.90, 10.0)]   # shank Ø, tab length (the size code)
SHANK = {"H": 2.5, "K": 1.8}
COUNT = {"H": 4, "K": 2}
HEAD_D, HEAD_T = 4.0, 0.8
NECK = (0.6, 1.0, 0.6)     # length, width, height
TAB_W, TAB_H = 3.0, 1.2
FLAT = 0.15
CHAMFER = 0.25


def U(meshes):
    return trimesh.boolean.union(meshes, engine="manifold")


def pin(d, shank, tab):
    """Along +X: tab | neck | head | shank, lying with its flat on z = 0."""
    r = d / 2
    zc = r - FLAT                                     # axis height
    ax = R(np.pi / 2, [0, 1, 0])

    def cyl(rad, x0, x1):
        c = trimesh.creation.cylinder(radius=rad, height=x1 - x0, sections=64)
        c.apply_transform(ax)
        c.apply_translation([(x0 + x1) / 2, 0, zc])
        return c

    body = cyl(r, 0.0, shank - CHAMFER)
    tip = trimesh.creation.cone(radius=r, height=CHAMFER * 4, sections=64)   # trimmed to a chamfer
    tip.apply_transform(ax)
    tip.apply_translation([shank - CHAMFER, 0, zc])
    tip = trimesh.boolean.intersection([tip, trimesh.creation.box(bounds=[[shank - CHAMFER, -5, -5], [shank, 5, 5]])],
                                       engine="manifold")
    head = cyl(HEAD_D / 2, -HEAD_T, 0.0)
    nl, nw, nh = NECK
    neck = trimesh.creation.box(bounds=[[-HEAD_T - nl - 0.05, -nw / 2, 0], [-HEAD_T + 0.05, nw / 2, nh]])
    x_tab = -HEAD_T - nl
    tabm = trimesh.creation.box(bounds=[[x_tab - tab, -TAB_W / 2, 0], [x_tab, TAB_W / 2, TAB_H]])
    m = U([body, tip, head, neck, tabm])
    m = trimesh.boolean.intersection([m, trimesh.creation.box(bounds=[[-50, -10, 0], [10, 10, 10]])], engine="manifold")
    m.apply_translation(-m.bounds[0])
    return m


def pin_set():
    rows, y = [], 0.0
    for d, tab in SIZES:
        x = 0.0
        for kind in ("H", "K"):
            for _ in range(COUNT[kind]):
                p = pin(d, SHANK[kind], tab)
                p.apply_translation([x, y, 0])
                rows.append((f"{kind} Ø{d:.2f}", p))
                x = p.bounds[1][0] + 3.0
        y += HEAD_D + 3.0
    return rows


def phalanges():
    flip = R(np.pi, [1, 0, 0])
    spec = [("K1_02_Phalanx1_pinned.stl", np.eye(4)), ("H1_02_Phalanx1_pinned.stl", np.eye(4)),
            ("H1_02_Phalanx1_pinned.stl", np.eye(4)), ("K2_04_Phalanx2_pinned.stl", flip),
            ("H2_04_Phalanx2_pinned.stl", flip), ("H2_04_Phalanx2_pinned.stl", flip)]
    out = []
    for i, (f, rot) in enumerate(spec):
        m = trimesh.load(PH / f)
        m.apply_transform(rot)
        m.apply_translation(-m.bounds[0])
        m.apply_translation([(i % 3) * 32.0, (i // 3) * 28.0, 0])
        out.append(m)
    return out


def separated(meshes, gap):
    for i in range(len(meshes)):
        for j in range(i + 1, len(meshes)):
            a, b = meshes[i].bounds, meshes[j].bounds
            if np.maximum(a[0][:2] - b[1][:2], b[0][:2] - a[1][:2]).max() < gap:
                return False
    return True


def centred(meshes):
    t = trimesh.util.concatenate(meshes)
    t.apply_translation([128 - t.bounds[:, 0].mean(), 128 - t.bounds[:, 1].mean(), 0])
    return t


def main():
    pins = [p for _, p in pin_set()]
    assert all(p.is_watertight and p.is_volume for p in pins) and separated(pins, 2.5)
    OUT.mkdir(parents=True, exist_ok=True)
    centred(pins).export(OUT / "hinge_pins_fit_set.stl")
    ph = phalanges()
    shift = -min(p.bounds[0][1] for p in ph) + max(p.bounds[1][1] for p in pins) + 8.0
    allp = ph + [p.copy().apply_translation([0, -shift, 0]) for p in pins]
    assert separated(allp, 2.5)
    plate = centred(allp)
    assert plate.bounds[0][:2].min() > 0 and plate.bounds[1][:2].max() < 256
    plate.export(OUT / "pinned_phalanges_plate.stl")
    p = pin(1.75, SHANK["H"], 8.0)
    print(f"{len(pins)} pins; one H pin Ø1.75: {p.extents.round(2)} mm")
    print(f"plate: {len(allp)} pieces, {plate.extents.round(1)} mm")


if __name__ == "__main__":
    main()
