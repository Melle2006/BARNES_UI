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

## Can these designs reach a human PIP range? Not yet

`scripts/a6_rom_check.py` treats the leaf as a large-deflection bending beam. The beam is
fixed at the PP anchor, and its tip slides without friction along the guide as the MP swings
about the PIP axis. It flexes each design from −5° to 110°, the human PIP range, and writes
`A6_pip_rom_check.csv` and `A6_pip_rom_shapes.png`.

The A8 export doesn't include the phalanges, so **the PIP axis position is an assumption**.
It is tried at y = 10, 15, 20 and 24 mm, all at z = 0. The results depend strongly on it.

![Leaf shapes through flexion, axis at y = 15](A6_pip_rom_shapes.png)

What it shows:

1. **The 2.5 mm stroke stops every design at 15–36° flexion.** To reach 110°, the tip has
   to slide 4–16 mm, depending on radius and axis position. Tighter radii need more slide.
   R30–R40 need 9–11 mm with the axis at y = 15.
2. **Flatter leaves cut through the joint during flexion.** From R80 up to flat, the leaf
   comes within 3.5 mm of the axis somewhere between 34° and 78°. In reality it would press
   on the knuckle, and that contact isn't modelled. With the axis at y = 10 or 15, R30 and
   R40 stay clear (R40 only just reaches 3.5 mm at 107°). With the axis further distal, the
   solution stops before 110° (see next point).
3. **The leaf is far too soft.** At 4 × 1 mm, stiffness near neutral is 0.1–0.75 N·mm/rad for
   E = 8–18 MPa. That is about 10–50 times below the A3's 6.1 N·mm/rad. Stiffness grows
   with thickness cubed and strain grows linearly, so a 2 mm leaf is 8 times stiffer and
   strains twice as much. Peak strain at 1 mm is 3–5% with the axis at y = 10–15, and 11–20%
   at y = 20–24.
4. **With the axis near the MP cuff (y = 24), no design reaches 110°.** There is no nearby
   equilibrium past 73–99°, so the leaf would snap through to another shape.

None of this is experimentally validated. The modulus is uncalibrated, and contact and guide
friction are ignored.
