# A6: sliding-end leaf spring

A pre-curved leaf is fused to the proximal-phalanx (PP) cuff. Its free end slides in a guide
on the middle-phalanx (MP) cuff. When the joint flexes, the guide turns with the MP, which
forces the leaf to change its end angle. The leaf bends, stores energy and pushes the joint
back toward neutral. The end can slide, so the leaf is not stretched axially as well.

Each design has the same collars as `A8_PIP_Meander_3turn_2mm` and uses the same axes: Y runs
from PP to MP, +Z is dorsal, and the MP collar starts at y = 28.86. Only the leaf radius
changes between designs. The files are regenerated with `scripts/make_a6_designs.py`.

![Mid-plane sections](A6_side_sections.png)

| File | Leaf R (mm) | Free arc (mm) | Anchor angle | Guide angle | Arc turns through | Leaf top above PP cuff (mm) |
|---|---|---|---|---|---|---|
| `A6_PIP_SlidingLeaf_R30`   | 30   | 23.47 | +23.3° | −21.6° | 44.8° | 5.40 |
| `A6_PIP_SlidingLeaf_R40`   | 40   | 23.07 | +17.0° | −16.0° | 33.1° | 4.21 |
| `A6_PIP_SlidingLeaf_R60`   | 60   | 22.81 | +11.0° | −10.8° | 21.8° | 3.09 |
| `A6_PIP_SlidingLeaf_R80`   | 80   | 22.73 |  +8.0° |  −8.3° | 16.3° | 2.55 |
| `A6_PIP_SlidingLeaf_R120`  | 120  | 22.66 |  +5.0° |  −5.8° | 10.8° | 2.01 |
| `A6_PIP_SlidingLeaf_R200`  | 200  | 22.63 |  +2.6° |  −3.8° |  6.5° | 1.59 |
| `A6_PIP_SlidingLeaf_flat`  | flat | 22.61 |  −0.9° |  −0.9° |  0.0° | 1.14 |

The same figures, plus body volumes and a check that the bodies do not overlap, are in
`A6_variants.csv`. The overlap is 0 mm³ for every design.

## Geometry

| Feature | Value |
|---|---|
| PP cuff | 13.8 × 9.4 mm outside, corner R 3.55, 1.2 wall, 3 mm long (copied from A8) |
| MP cuff | 10.1 × 6.2 mm outside, corner R 2.10, 1.2 wall, 3 mm long (copied from A8) |
| Leaf | 4.0 mm wide × 1.0 mm thick, fused to a wedge anchor on the PP cuff top |
| Guide | 1.5 mm neck, then a pocket holding a 6.0 × 1.2 mm T-head on the leaf tip |
| Travel | 2.5 mm toward the PP (flexion) before the head reaches the neck, and 1.5 mm distally |
| Sliding clearance | 0.25 mm per side on every face, so both bodies can be printed in place |

**The anchor and the guide follow the arc's tangents, so they are not level.** A circular arc
cannot leave both ends horizontally. A level slot would therefore preload the leaf before
the joint moves. Tilting the anchor and guide to match the arc means every design is
unstressed at neutral. A tighter radius therefore needs a steeper guide, raised on a saddle to
clear the MP cuff, and that is why the R30 design stands taller.

## Files

* `*.STEP` is a two-body part: PP cuff + anchor + leaf, and MP cuff + guide. It opens in
  SolidWorks. A native `.SLDPRT` cannot be written outside SolidWorks.
* `*.STL` contains both bodies, for slicing.

## Not checked yet

* Stiffness, restoring torque and peak strain. No FEA has been run. The table above is
  geometry only.
* Whether 2.5 mm of slide covers the flexion range. That depends on where the real joint axis
  sits, which these files do not include.
* Print-in-place in TPU with a 0.25 mm gap. The head may fuse in its pocket. If it does,
  increase `CLEARANCE` in the script.
