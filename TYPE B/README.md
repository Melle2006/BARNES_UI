# TYPE B: TPU itself as the joint

In every Type B design, the joint is a TPU module printed as a flexure. It
plugs into PLA phalanges, and nothing else forms the joint. This folder holds
five Type B flexure designs, **55 variants** in all. Every variant has its
three joint modules (STEP and STL) and a full finger assembly (`finger_assembly.step`).

![one PIP module from each family](previews/04_flexure_families_PIP.png)

## Folder layout

| Folder | Design | Variants | Details |
|---|---|---|---|
| [`B_lattice/`](B_lattice/) | Bow-tie (re-entrant) lattice, your original design with its errors corrected | 13 | [B_lattice/README.md](B_lattice/README.md) |
| `B_lattice/original_reference/` | Your original script and STEP files, unchanged, for reference only | n/a | [README](B_lattice/original_reference/README.md) |
| [`B3_dual_leaf/`](B3_dual_leaf/) | B3 dual leaf, plus B7 taper variants | 12 | [FLEXURE_FAMILIES.md](FLEXURE_FAMILIES.md#b3-dual-leaf-the-agreed-first-test) |
| [`B6_multi_leaf/`](B6_multi_leaf/) | B6 side-by-side multi-leaf, plus B7 taper variants | 10 | [FLEXURE_FAMILIES.md](FLEXURE_FAMILIES.md#b6-multi-leaf-side-by-side) |
| [`B5_crossed_strip/`](B5_crossed_strip/) | B5 crossed strips (cross-axis pivot) | 12 | [FLEXURE_FAMILIES.md](FLEXURE_FAMILIES.md#b5-crossed-strips-cross-axis-pivot) |
| [`B1_hourglass/`](B1_hourglass/) | B1 elliptical-notch hourglass (control) | 8 | [FLEXURE_FAMILIES.md](FLEXURE_FAMILIES.md#b1-hourglass-control) |
| `common_phalanges/` | The three PLA phalanges, shared by every variant | n/a | |
| `previews/` | Rendered images | n/a | |

Each design folder has a `variants_summary.csv`, with every dimension of
every joint in every variant, and a `verification_report.csv`.

The scripts are:

* `build_finger_type_b.py`: the shared finger and the lattice.
* `build_flexure_families.py`: B1, B3, B5 and B6.
* `verify_type_b.py`: the geometric checks.

## What every variant has in common

Only the TPU between the two collars of each joint changes from variant to
variant. Everything else is identical, so test results compare the flexures
alone:

* **Envelope.** Finger cross-sections are MCP 16 × 14, PIP 14 × 12 and DIP
  12 × 10 mm, tapering to 11 × 9 mm at the tip. Overall length is 95.7 mm.
* **Flex-zone length.** MCP 10.25 mm, PIP 7.55 mm, DIP 7.3 mm.
* **Phalanges.** These are the files in `common_phalanges/`. They have:
  * 1.2 mm socket walls
  * palmar hard-stop nubs
  * DIP coupling-wire bosses
  * a fingertip sensor recess and tendon anchor
* **Joint-module ends.** Each has a 4 mm tab in its socket with 0.3 mm
  clearance, two Ø2 retention pins, and a 0.8 mm collar.
* **MCP flange.** 28 × 14 × 4 mm, with M3 holes at ±11 mm.
* **Channels.** A Ø3 tendon channel and a Ø1.5 sensor channel. The tendon
  moment arms are 3.06 / 1.93 / 1.06 mm (MCP / PIP / DIP). Every flexure
  leaves a clear central corridor so both run through the joint in open air.

Every one of the 55 variants passes all 38 geometric checks in its
`verification_report.csv`.

## FEA selection: the best variant of each design

All variants were simulated at the PIP, attached the way the A3 fit check
attaches its strap. The full method, criteria, stress-strain graphs and
results are in **[analysis/REPORT.md](analysis/REPORT.md)**.

| Design | Selected variant | Usable PIP range | Notes |
|---|---|---|---|
| B5 crossed strip | `B5_t150_a45` | 77.8° | best overall; stiffest in twist |
| B3 dual leaf | `B3_t150_w30` | 76.6° | lowest strain; soft in twist |
| B6 multi-leaf | `B6_n4_t150_taper15` | 72.5° | no advantage over B3 |
| B1 hourglass | `B1_t100_notch100` | 46.0° | strain-limited |
| B-lattice | `B_T090_X3` | 16.2° | struts buckle; not viable as drawn |

## What changes in each design's variants

The thickness values below are the **PIP** values. In the B1, B3, B5 and B6
families, the MCP is 1.27× thicker and the DIP 0.82× thinner, the same ratios
as the original lattice. In B-lattice the scale applies to each joint's own
strut thickness.

### B-lattice: bow-tie lattice (13 variants)

| Property | Levels | What it does |
|---|---|---|
| Strut thickness, as a scale on your original struts | ×0.90, ×1.00, ×1.10, ×1.20 | Bending stiffness goes with t³, so roughly 0.73× to 1.73×. Thicker struts also straighten the dorsal cells. |
| Criss-cross cells per lattice (palmar / dorsal) | 2 / 1, 3 / 2, 4 / 3 | More cells means shorter, more re-entrant cells (palmar about 35–68°, dorsal about 6–38°). |
| `B00_baseline` | Your original counts: MCP 3/2, PIP 2/2, DIP 3/2, at ×1.00 | The corrected version of your design. |

Fixed across all lattice variants:

* the four lattice columns
* the palmar and dorsal band positions
* the bridge thickness
* the 3.8 mm tendon corridor

Baseline strut thickness, palmar / dorsal: MCP 0.70 / 1.40, PIP 0.55 / 1.10,
DIP 0.45 / 0.90 mm.

Naming: `B_T{scale×100}_X{palmar cells}`, e.g. `B_T110_X3`.

### B3: dual leaf (12 variants)

| Property | Levels | What it does |
|---|---|---|
| Leaf thickness (PIP) | 1.0, 1.25, 1.5, 2.0 mm | Stiffness ∝ t³ |
| Leaf width (each leaf) | 2.0, 3.0 mm | Stiffness ∝ width. Wider leaves also add lateral and torsional stability. |
| Taper, B7 (root ÷ middle thickness) | 1.0 (uniform), plus 1.5 and 2.0 at t = 1.0 and 1.5 mm with w = 3.0 mm | Thicker roots lower the peak strain at the clamped ends, but the joint gets stiffer. |

Fixed: two leaves, one each side of the tendon at the outer edge of the joint,
on the centre line, running the full flex length.

Naming: `B3_t{t×100}_w{w×10}`, plus `_taper{r×10}`.

### B6: multi-leaf, side by side (10 variants)

| Property | Levels | What it does |
|---|---|---|
| Number of leaves | 4 (2 per side, each 1.0 mm wide) or 6 (3 per side, each 0.67 mm wide) | Splits the same material into narrower leaves. This changes twisting and sideways stiffness, not bending. |
| Leaf thickness (PIP) | 1.0, 1.25, 1.5, 2.0 mm | Stiffness ∝ t³ |
| Taper, B7 | 1.0, plus 1.5 and 2.0 on `B6_n4_t150` | As for B3 |

Fixed: 2.0 mm of total leaf width per side, with 0.6 mm gaps between leaves.
This gives each variant the same material and estimated bending stiffness as
its `B3_t###_w20` twin, for a fair comparison.

Naming: `B6_n{leaves}_t{t×100}`, plus `_taper{r×10}`.

### B5: crossed strips (12 variants)

| Property | Levels | What it does |
|---|---|---|
| Strip thickness (PIP, measured across the strip) | 1.0, 1.25, 1.5, 2.0 mm | Stiffness ∝ t³ |
| Crossing angle between the strips | 45°, 60°, 75° | A wider angle gives longer strips (PIP 8.2 / 8.7 / 9.5 mm), which bend more easily but are a little less stable under compression. The crossing fixes the centre of rotation at mid-joint. |

Fixed: four lanes across the width (A | B ‖ B | A), so the two strip directions
cross in side view but sit 0.6 mm apart and never fuse. The lanes fill the
available width: about 2.45 mm at the MCP, 1.95 mm at the PIP and 1.3 to
1.45 mm at the DIP. At 90° the strips would run into the collar corners, so
90° wasn't built.

Naming: `B5_t{t×100}_a{angle}`.

### B1: hourglass, the control (8 variants)

| Property | Levels | What it does |
|---|---|---|
| Throat thickness (PIP) | 1.0, 1.25, 1.5, 2.0 mm | Stiffness rises steeply with the throat thickness |
| Notch length | the full flex zone (100 %) or the middle 50 % | A shorter notch concentrates the bending, giving a sharper centre of rotation but higher strain. It is about 2× stiffer. |

Fixed: two webs, each 3.0 mm wide, one each side of the tendon. Each web is
as tall as the collar allows (MCP 10.9, PIP 8.9, DIP 6.9 mm) and has an
elliptical notch cut from both faces.

Naming: `B1_t{t×100}_notch{%}`.

### Estimated stiffness ranges

Simple beam-theory estimates at E = 12 MPa, for ranking only. Per-variant
values are in each folder's CSV and in [FLEXURE_FAMILIES.md](FLEXURE_FAMILIES.md).

| Design | PIP joint, N·mm/rad (softest to stiffest variant) |
|---|---|
| B3 | 0.5 to 6.4 |
| B6 | 0.5 to 4.2 |
| B5 | 0.8 to 7.6 |
| B1 | 2.8 to 29.8 |
| B-lattice | not estimated. The lattice needs FEA. |

## Regenerating

```bash
pip install cadquery
```

```bash
python "TYPE B/build_finger_type_b.py"
```

```bash
python "TYPE B/build_flexure_families.py"
```

```bash
python "TYPE B/verify_type_b.py"
```
