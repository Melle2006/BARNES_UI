# Type B design parameters per joint (exact, from the CAD builder)

Made by `scripts/typeb_parameter_table.py`, which calls the flexure builder in
`TYPE B/build_flexure_families.py` for every variant at the MCP, PIP and DIP and records what it
builds. Every value of every variant and joint is in `results/typeB_parameter_ranges.csv` (138 rows).

## Fixed by the finger (not optimisation variables unless the phalanges are redesigned)

| | MCP | PIP | DIP |
|---|---|---|---|
| Module cross-section (w × h) | 16.0 × 14.0 mm | 14.0 × 12.0 mm | 12.0 × 10.0 mm |
| Flex-zone length | 10.25 mm | 7.55 mm | 7.30 mm |
| Thickness grade (× the PIP value) | 1.2727 | 1.0000 | 0.8182 |

Build rules: narrowest printable leaf or lane 0.6 mm; gap between lanes 0.6 mm; flexure kept
0.3 mm inside the collar outline.

## What was swept (discrete levels; the steps are not even)

Thickness is set at the PIP; the MCP and DIP values are the PIP value × the grade above.

### B5 crossed strip

| Parameter | PIP | MCP | DIP |
|---|---|---|---|
| Strip thickness t (mm) | 1.00, 1.25, 1.50, 2.00 | 1.273, 1.591, 1.909, 2.545 | 0.818, 1.023, 1.227, 1.636 |
| Crossing angle (°) | 45, 60, 75 | 45, 60, 75 | 45, 60, 75 |
| Strip width w (mm), set by the space left | 1.95 (all angles) | 2.45 (45°, 60°), 2.42 (75°) | 1.45 (45°), 1.405 (60°), 1.295 (75°) |
| Strip length (mm) = flex length ÷ cos(angle/2) | 8.172 / 8.718 / 9.517 | 11.095 / 11.836 / 12.920 | 7.901 / 8.429 / 9.201 |

Geometric limit: thickness does not run out of room before 4 mm at 45° and 60°, or 3.05 mm at
75° (PIP value). In practice strain, not space, limits thickness.

### B5i inset crossed strip (pinned hybrid K)

| Parameter | PIP | MCP | DIP |
|---|---|---|---|
| Strip thickness t (mm) | 1.50, 1.75, 2.00, 2.25 | 1.909, 2.227, 2.545, 2.864 | 1.227, 1.432, 1.636, 1.841 |
| Crossing angle (°) | 45 | 45 | 45 |
| Strip width w (mm) | 0.90 | 0.90 | 0.90 |
| Strip length (mm) | 8.172 | 11.095 | 7.901 |
| Collar half-width (mm) | 4.6 | | |

### B3 dual leaf

| Parameter | PIP | MCP | DIP |
|---|---|---|---|
| Leaf thickness t (mm) | 1.00, 1.25, 1.50, 2.00 | 1.273, 1.591, 1.909, 2.545 | 0.818, 1.023, 1.227, 1.636 |
| Leaf width w (mm) | 2.0, 3.0 | 2.0, 3.0 | 2.0, 3.0 |
| Taper (root ÷ middle thickness) | 1.0, 1.5, 2.0 | same | same |
| Leaves per side | 1 (2 in all) | | |

### B6 multi-leaf

| Parameter | PIP | MCP | DIP |
|---|---|---|---|
| Leaf thickness t (mm) | 1.00, 1.25, 1.50, 2.00 | 1.273, 1.591, 1.909, 2.545 | 0.818, 1.023, 1.227, 1.636 |
| Leaves (total) | 4, 6 | 4, 6 | 4, 6 |
| Leaf width w (mm), 2.0 mm per side shared | 1.000 (4 leaves), 0.667 (6 leaves) | same | same |
| Taper | 1.0, 1.5, 2.0 | same | same |

### B1 hourglass

| Parameter | PIP | MCP | DIP |
|---|---|---|---|
| Throat thickness (mm) | 1.00, 1.25, 1.50, 2.00 | 1.273, 1.591, 1.909, 2.545 | 0.818, 1.023, 1.227, 1.636 |
| Web width (mm) | 3.0 | 3.0 | 3.0 |
| Notch length (mm) (full / half) | 7.55 / 3.775 | 10.25 / 5.125 | 7.30 / 3.65 |
| Web height (mm) | 8.907 | 10.907 | 6.907 |

(B4 rolling contact, B8 knuckle and the B-lattice are built by the round-2 and lattice scripts,
not this table: see `TYPE B/round2/build_round2.py`.)

## Suggested ranges for an ANSYS optimisation of B5 (PIP; scale t by the grade for MCP/DIP)

These are a choice, not a sweep that was run; the reasons are given.

| Parameter | Min | Max | Step | Why these limits |
|---|---|---|---|---|
| Strip thickness t | 1.00 mm | 2.25 mm | 0.25 mm | below 1.0 too weak against the tendon (buckles); above about 2.25 the strain passes 20 % before 60° |
| Strip width w | 0.90 mm | 1.95 mm | 0.15 mm | 0.9 = the inset version; 1.95 = all the room there is at the PIP (MCP 2.45, DIP 1.45) |
| Crossing angle | 40° | 75° | 5° | 45° won; 75° is the last angle that builds at t ≥ 2.0 |
| Flex length | 7.55 mm | 7.55 mm | fixed | set by the phalanges |
