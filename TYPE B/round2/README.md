# Type B round 2: joints that carry the tendon's compression

Round 1 (`../B1_hourglass`, `../B3_dual_leaf`, `../B5_crossed_strip`,
`../B6_multi_leaf`, `../B_lattice`) is unchanged and still to be printed. Round 2
only adds to it, in this folder.

**Why round 2 exists.** The tendon squeezes every joint it crosses. With no pin,
round 1's TPU leaves carry that squeeze, and at the provisional modulus they
buckle at a fraction of the servo's tension
([docs/11](../../docs/11-tendon-routing-type-a-b.md)). Round 2 tries two remedies,
separately and together:

1. A **bearing** that carries the compression, so the TPU only has to spring
   the joint back.
2. A **deeper tendon offset**, so the same fingertip force needs less tension.

The test plan is in [TEST_PLAN.md](TEST_PLAN.md). The rig and specimens are in
[test_rig/](test_rig/).

**Tendon-load FEA of the shortlist** (rows 1-11 of TEST_PLAN): [fea/](fea/README.md). It replaces the hand estimates in predictions.csv where it resolved: plain leaves (B3) buckle at about 10 N, a third of the estimate; B5 t2.0 with the deep tendon carries 30 N; the bearing joints carry load at low strain once seated, but only lower bounds could be resolved.

## The new designs (`./`)

They use the same finger, collars, tabs, sockets and phalanges as round 1 (the
files in `../common_phalanges/`). Only the TPU between the two collars of each
joint is new. Each side of the tendon corridor has two lanes:

* the inner lane holds the bearing;
* the outer lane holds the spring.

Every bearing pair is printed **0.3 mm apart**, so the joint is free as printed.
The first tendon load closes the gap. Dimensions in names are PIP values. MCP and
DIP are graded as in round 1: thicknesses ×1.27 and ×0.82, offsets and radii by
section height.

| Variant | Bearing (inner lane) | Spring (outer lane) | Centre of rotation |
|---|---|---|---|
| `B4_t080_a60`, `B4_t100_a60` | **Rolling contact**: two convex lobes that roll on each other | Crossed strips, fused into an X at mid-joint, 0.8 / 1.0 mm, 60° | Moves palmar by R sin(θ/2) as it rolls |
| `B8_y00_r150` | **Knuckle in a cup** on the neutral axis, knuckle r 1.5 mm, cup wrap about 139° | Thin leaf, 0.75 mm | Fixed, at y = 0 |
| `B8_y20_r125` | Knuckle in a cup **2 mm dorsal** of the axis, r 1.25 mm | Thin leaf, 0.75 mm | Fixed, at y = +2 mm |
| `B9_n100`, `B9_n150` | **Compression strut**: a stocky web on the neutral axis with one 0.8 mm long neck, 1.0 / 1.5 mm thick | Thin leaf, 0.75 mm | Fixed, at the neck |

Three decisions that are not obvious:

* **The rolling radius is small on purpose.** As the lobes roll, the contact
  point moves towards the palm. A palmar tendon's lever about it is roughly
  d − R sin(θ/2). With the as-built tendon offset `d` and a large radius, the
  tendon would start *extending* the joint part-way through flexion. So R is set
  per joint to keep the lever at least 0.3 mm at the target flexion (MCP 90°,
  PIP 100°, DIP 80°). That gives PIP R ≈ 2.1 mm as built, and larger in the
  deep-offset copies. The radius is in `variants_summary.csv`.
* **No palmar pad.** A bearing on the palmar side would put the pivot palmar of
  the tendon, and the tendon would extend the joint. The pad is central or
  dorsal instead. Moving it dorsally (`B8_y20`) lengthens the tendon's lever
  without moving the tendon.
* **The B8 knuckle slides; B4 rolls.** Sliding TPU on TPU has friction, roughly
  μ·N·r of extra torque, which is why the knuckle radius is small. Rolling has
  almost no friction but its pivot moves. Testing both separates the two
  effects.

## Deep tendon offset (`deep_offset/`)

The tendon channel sits at the deepest palmar offset the section allows while
keeping the builder's own 0.8 mm minimum wall everywhere it runs. Those
offsets come out at:

| Joint | As built | Deep | What limits it |
|---|---|---|---|
| MCP | 3.06 mm | **4.40 mm** | TPU collar outline |
| PIP | 1.93 mm | **3.40 mm** | TPU collar outline (the PP socket floor allows 3.43) |
| DIP | 1.06 mm | **2.30 mm** | the coupling-wire boss hole in the DP (keeps 0.5 mm to it) |

These are less than the 4.7 / 3.7 / 2.7 mm in docs/11. Those used the nominal
section height, and the phalanges taper, so the section is thinner at each
socket floor. To build at those values anyway, run
`build_round2.py --deep-offsets 4.7 3.7 2.7`; the wall checks then fail, and
the report shows where.

How it is built:

* The tendon channel is deeper than the TPU tab allows. So inside each socket it
  becomes an open groove in the tab's palmar face, closed by the PLA socket wall
  around the tab. The verification checks that wall (≥ 0.8 mm) in place of the
  tab wall for these variants.
* Inside the DP, the channel ramps back up to the original depth before the
  anchor. The fingertip anchor hole and the sensor-pad recess are where they
  always were.
* The deep phalanges are therefore new parts, the same for every deep variant:
  `deep_offset/deep_phalanges/`. Round-1 phalanges do not fit the deep modules'
  tendon path.

Deep copies:

| Source | Why |
|---|---|
| `B1_t200_notch050` and `B3_t200_w30` | The two round-1 variants docs/11 singled out. `B1_t200_notch050` is also B1's stiffest and `B3_t200_w30` B3's stiffest. |
| `B1_t100_notch100` | B1's softest |
| `B3_t100_w20` | B3's softest |
| `B5_t100_a75`, `B5_t200_a45` | B5's softest and stiffest |
| `B6_n6_t100`, `B6_n4_t200` | B6's softest and stiffest. Ties are broken towards the larger contrast. |
| `B_T090_X3`, `B_T120_X3` | The lattice, bracketed by strut scale. It has no stiffness estimate. |
| `B4_*`, `B8_*`, `B9_*` | Every new design |

## Checks

Every variant here passes all of `../verify_type_b.py`:
* the round-1 checks;
* for deep-offset variants, the PLA wall outside the grooved channel, the TPU
  collar wall round it, and clearance to the coupling-wire boss holes;
* for the bearing designs, that the two bearing surfaces are clear of each
  other as printed.

Results are in `verification_report.csv` here and in `deep_offset/`. Like round
1, these are geometric checks only. How the joints bend, bear and fail is what
the test plan is for.

## Regenerating

```bash
python "TYPE B/round2/build_round2.py"
```

```bash
python "TYPE B/round2/test_rig/build_test_rig.py"
```

```bash
python "TYPE B/round2/predict_round2.py"
```

The round-2 options in `../build_finger_type_b.py` (`tendon_offsets`) and
`../verify_type_b.py` (the deep-tendon and bearing checks) only switch on when
asked for. Round-1 outputs regenerate exactly as committed.
