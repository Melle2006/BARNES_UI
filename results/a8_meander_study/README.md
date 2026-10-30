# A8 PIP meander study — turns × spine curvature, TPU 90A

What restoring torque the A8 meander strip gives across the PIP joint, how that depends on
the number of turns and on the curvature of the strip's spine, and which combination to
build. Every number here is from nonlinear FEA (CalculiX, `*NLGEOM`, Neo-Hookean) driven
through 0–100° of flexion, with the strip riding over a rigid model of the finger.

33 cases: the three supplied exports, their parametric rebuilds, and 2-, 3- and 4-turn
strips each at nine spine sagittas from 0 to 3.5 mm.

**Nothing here is experimentally validated.** The material is a datasheet modulus, the
joint axis and finger surfaces are inferred from the ring geometry, and no physical
spring has been measured. Use the comparisons; treat the absolute torques as
order-of-magnitude until a tensile test and a bench measurement exist.

---

## Recommendation

**3 turns, spine sagitta ≈ 1.0 mm** (bend radius ≈ 84 mm) — essentially your existing
`A8_PIP_Meander_3turn_2mm` (sagitta 1.14 mm), which lands in the same tie group.

1. **Do not use 2 turns.** Every 2-turn variant *snaps*: torque climbs to about
   0.8 N·mm and then collapses by 30–60 % as the strip is pulled down into the crease
   between the knuckle and the distal link. More arch only postpones it — 75° at 0.75 mm
   sagitta, 91° at 3.5 mm — and never removes it within 0–100°. On a hand that is a
   spring that lets go part-way through every grip. See `fig_torque_angle_2turn.png`.
2. **Every 3-turn variant is smooth and monotonic to 100°** — no snap, no torque drop,
   7–8 % peak strain at 90°. See `fig_torque_angle_3turn.png`.
3. **Within 3 turns, spine curvature is a gentle tuning knob, not a deciding one.**
   Torque per unit strain is the same to within 3 % from 1.0 to 3.5 mm sagitta. Lower
   arch gives more torque at 90° (0.446 vs 0.363 N·mm) and a lower profile; higher arch
   gives slightly more stiffness right at full extension and less strain. 1.0 mm wins
   the tie-break on torque at 15° *and* on profile.
4. **Do not go to 4 turns.** Every 4-turn variant is smooth to 100°, but it gives only
   0.13–0.16 N·mm at 90° — about a third of the 3-turn — and its torque per unit strain
   is 3.3 against 5.3. Its path is 64 mm long against 48, and its true section narrows
   to 0.56 mm at the crossings. More turns make the spring softer and thinner, not
   better; if anything is to change in the count, it is 3 → 2 with the snap designed
   out, not 3 → 4.
5. **Do not go flatter than ≈ 1.0 mm.** Below 0.70 mm sagitta the strip starts inside the
   knuckle; at 0.75 mm it clears by 0.04 mm, which a printed part will not hold. 1.0 mm
   clears by 0.29 mm.
6. **The spring is weak, and the fix is section height, not turns.** At 90° the 3-turn
   strip gives ~0.45 N·mm; the strip itself is only 7–8 % strained, so there is a great
   deal of headroom. Torque scales with the cube of the 1.2 mm section height and strain
   only linearly: **1.8 mm → ≈ 3.4× torque at ≈ 1.5× strain; 2.4 mm → ≈ 8× torque at
   ≈ 2× strain (~17 %)**. Raising height also widens the narrowest wall problem below.
   This scaling is from beam theory, not yet from a run — it is the obvious next case.
7. **Print the narrow crossings deliberately.** The "2 mm" in the file names is measured
   *across the finger*; the strip's true width is 2.0·cos φ, so where the path crosses
   steeply the 3-turn strip is only **0.71 mm** wide — under two 0.4 mm extrusion widths.
   The 2-turn is 0.93 mm, a 4-turn of the same style 0.56 mm. Either print with a
   0.25–0.3 mm nozzle, or redraw the section normal to the path.

---

## The matrices

`matrices.md` has every column; the main ones (TPU 90A, E = 19.3 MPa):

### 2-turn (all snap — none feasible)

| Sagitta (mm) | Bend R (mm) | k0 (N·mm/rad) | T15 | T30 | T60 (N·mm) | Snaps at | ε60 (%) | Knuckle clearance (mm) | Top height (mm) |
|---|---|---|---|---|---|---|---|---|---|
| 0.00 | ∞ | — | — | — | — | starts 0.70 mm *inside* knuckle | — | −0.70 | 4.70 |
| 0.50 | 167 | — | — | — | — | starts 0.20 mm inside knuckle | — | −0.20 | 4.72 |
| 0.75 (≈ export) | 112 | 0.51 | 0.130 | 0.254 | 0.593 | **75°** | 7.3 | 0.04 | 4.86 |
| 1.00 | 84 | 0.39 | 0.125 | 0.245 | 0.579 | **76°** | 7.1 | 0.29 | 5.06 |
| 1.50 | 57 | 0.42 | 0.115 | 0.235 | 0.544 | **77°** | 6.6 | 0.79 | 5.51 |
| 2.00 | 43 | 0.45 | 0.098 | 0.224 | 0.503 | **80°** | 6.2 | 1.29 | 5.98 |
| 2.50 | 35 | 0.46 | 0.089 | 0.209 | 0.459 | **85°** | 5.7 | 1.79 | 6.46 |
| 3.00 | 29 | 0.47 | 0.091 | 0.190 | 0.420 | **86°** | 5.4 | 2.29 | 6.95 |
| 3.50 | 26 | 0.47 | 0.092 | 0.166 | 0.384 | **91°** | 5.2 | 2.79 | 7.44 |

### 3-turn (all smooth to 100°)

| Sagitta (mm) | Bend R (mm) | k0 (N·mm/rad) | T15 | T30 | T60 | T90 (N·mm) | Energy 0–90° (mJ) | ε90 (%) | T90/ε90 | Knuckle clearance (mm) | Top height (mm) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.00 | ∞ | — | — | — | — | — | — | — | — | −0.70 (inside) | 4.70 |
| 0.50 | 167 | — | — | — | — | — | — | — | — | −0.20 (inside) | 4.72 |
| 0.75 | 112 | 0.24 | 0.058 | 0.117 | 0.266 | 0.441 | 0.313 | 8.4 | 5.24 | 0.04 ✗ | 4.86 |
| **1.00 ★** | **84** | **0.18** | **0.055** | **0.112** | **0.260** | **0.446** | **0.308** | **8.4** | **5.29** | **0.29** | **5.06** |
| 1.50 | 57 | 0.20 | 0.046 | 0.102 | 0.249 | 0.433 | 0.293 | 8.1 | 5.34 | 0.79 | 5.51 |
| 2.00 | 43 | 0.22 | 0.044 | 0.092 | 0.236 | 0.420 | 0.278 | 7.9 | 5.33 | 1.29 | 5.98 |
| 2.50 | 35 | 0.24 | 0.048 | 0.084 | 0.219 | 0.403 | 0.262 | 7.5 | 5.36 | 1.79 | 6.46 |
| 3.00 | 29 | 0.26 | 0.052 | 0.075 | 0.203 | 0.384 | 0.246 | 7.2 | 5.32 | 2.29 | 6.95 |
| 3.50 | 26 | 0.27 | 0.054 | 0.070 | 0.186 | 0.363 | 0.230 | 6.9 | 5.29 | 2.79 | 7.44 |

### 4-turn (all smooth to 100°, but a third of the torque)

| Sagitta (mm) | Bend R (mm) | k0 (N·mm/rad) | T15 | T30 | T60 | T90 (N·mm) | Energy 0–90° (mJ) | ε90 (%) | T90/ε90 | Knuckle clearance (mm) | Top height (mm) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.00 | ∞ | — | — | — | — | — | — | — | — | −0.70 (inside) | 4.70 |
| 0.50 | 167 | — | — | — | — | — | — | — | — | −0.20 (inside) | 4.72 |
| 0.75 | 112 | 0.089 | 0.022 | 0.046 | 0.102 | 0.160 | 0.118 | 5.0 | 3.23 | 0.04 ✗ | 4.86 |
| 1.00 | 84 | 0.061 | 0.021 | 0.044 | 0.100 | 0.159 | 0.116 | 4.7 | 3.34 | 0.29 | 5.06 |
| 1.50 | 57 | 0.068 | 0.017 | 0.040 | 0.095 | 0.154 | 0.110 | 4.6 | 3.33 | 0.79 | 5.51 |
| 2.00 | 43 | 0.075 | 0.014 | 0.036 | 0.091 | 0.150 | 0.104 | 4.6 | 3.28 | 1.29 | 5.98 |
| 2.50 | 35 | 0.080 | 0.016 | 0.032 | 0.085 | 0.145 | 0.098 | 4.3 | 3.34 | 1.79 | 6.46 |
| 3.00 | 29 | 0.085 | 0.017 | 0.028 | 0.079 | 0.139 | 0.092 | 4.0 | 3.43 | 2.29 | 6.95 |
| 3.50 | 26 | 0.089 | 0.018 | 0.024 | 0.073 | 0.132 | 0.086 | 4.0 | 3.30 | 2.79 | 7.44 |

The 4-turn plan is a pure sine of amplitude 4.0 mm (seven lobes) — there is no 4-turn
export, so this is an extrapolation of the family at the same lateral envelope.

### Supplied exports, and the check that the parametric rebuilds are faithful

| Part | Sagitta (mm) | T60 export / rebuild (N·mm) | T90 export / rebuild (N·mm) | Difference at 90° |
|---|---|---|---|---|
| A8_PIP_Meander_2turn_2mm | 0.75 | 0.587 / 0.592 | snaps at 75° | — |
| A8_PIP_Meander_3turn_2mm | 1.14 | 0.255 / 0.257 | 0.438 / 0.436 | 0.4 % |
| A8_PIP_Meander_3turn_2mm_2 | 2.17 | 0.228 / 0.230 | 0.409 / 0.414 | 1.3 % |

The sweep variants are rebuilt from parameters, so the sweep is only as good as the
rebuild. The rebuilds match the exports' geometry to 0.03 mm and their torque to 1.3 %.

---

## What the three supplied parts actually are

Measured from the STEP files (`input_step/`, SHA-256 below), not from the names:

- **Two rings and a strip.** The rings are 1.2 mm-wall collars round flat links: the
  proximal opening is 11.4 × 7.0 mm, the distal 7.7 × 3.8 mm. The strip's ends sit flush
  on the ring tops (z = 4.70 and 3.10 mm), 3.00 and 28.81 mm along the finger.
- **The strip never doubles back.** It is a snake whose lateral position is a smooth
  function of position along the finger: 3 lateral lobes for "2-turn", 5 for "3-turn"
  (so a "4-turn" has 7).
- **Its section is drawn across the finger, not across the strip.** Every cut across the
  finger is a 2.000 × 1.200 mm rectangle. The true strip width is 2.0·cos φ: 0.93 mm
  (2-turn) and 0.71 mm (3-turn) at the steepest crossing, mean 1.43 and 1.22 mm.
- **The spine is a circular arc**, fitted to 0.015 mm (0.093 mm for the v2 part):
  sagitta 0.75, 1.14 and 2.17 mm, bend radius 112, 74 and 40 mm.
- **Both 3-turn parts share one plan path** to 0.02 mm; they differ only in the spine.
- **Volume is 61.94 mm³ for all three** (2.0 × 1.2 × span) by slice integration.
  OpenCASCADE's own volume of the exported strips reads 60.5, 66.8 and 51.3 mm³ and is
  wrong — its surface integration over these B-spline solids is not reliable.

## How the analysis is set up

- **Material: TPU 90A**, Neo-Hookean, E = 19.3 MPa (Jabil TPU 90A datasheet, 2800 psi,
  ASTM D638), ν = 0.49. Polymaker PolyFlex TPU90's 100 % modulus implies about 12 MPa.
  Torques scale close to linearly with E at these strains, so a different filament
  rescales every torque by the same factor and does not reorder anything.
- **Joint axis**: parallel to X through the ring centreline (z = 0), midway between the
  ring faces (y = 15.905 mm). STEP carries no mates, so this is an assumption — the
  largest one after the material.
- **Finger**: three rigid surfaces the strip can rest on, positioned from the rings —
  the proximal link top (z = 3.4 mm, fixed), a knuckle of radius 3.4 mm about the joint
  axis (fixed), and the distal link top (z = 1.8 mm, rotating with the distal ring).
  Frictionless surface-to-surface contact against the strip's underside.
- **Boundary conditions**: proximal end cap held; distal end cap tied to a rigid body
  rotating about the joint axis by −100° about +X (distal ring towards the palm), with
  the other two rotations held — the joint is a hinge.
- **Mesh**: 10-node tetrahedra, 0.35 mm (two across the narrowest 3-turn wall), 0.28 mm
  for the 4-turn. Rigid surfaces 0.6 mm.
- **Peak strain** is the largest principal engineering strain, from CalculiX's
  Green-Lagrange output, at corner nodes more than 1 mm from either end cap (the tied
  caps are a singularity). "ε at clamp" is the unrestricted maximum.
- **Selection rules** are in the docstring of `scripts/a8_meander_report.py`: clear the
  knuckle by ≥ 0.25 mm at rest, no torque drop anywhere in 0–100°, ε90 ≤ 20 %; score
  T90/ε90; scores within 3 % are tied and broken by T15, then profile.

## Things that went wrong on the way, and are worth knowing

Each was a converged-looking run or a plausible number that was wrong. They are in the
commit history in full.

1. **No finger under the strip** — torque rose to 25°, fell, and the strip passed
   straight through the joint by 45°. The strip only works as a spring because something
   holds it up.
2. **Knuckle alone** — the 2-turn strip slid off the knuckle's far side at 69° and torque
   collapsed from 0.67 to 0.05 N·mm. The distal link was missing.
3. **Rigid body free to rotate about Y and Z** — the increment collapsed to 0.01°. A hinge
   holds them; so must the model.
4. **Node-to-surface contact on quadratic tets** chattered between 0 and 25 contact
   elements per iteration and stalled; surface-to-surface ran straight through.
5. **A softened contact penalty** let the strip push through the knuckle shell. The
   standard 10·E/h is used, and penetration is recorded on every run.

## Files

| File | What |
|---|---|
| `matrices.md` | All matrices, every column, selected design starred |
| `matrix_{2,3,4}turn.csv` | Same, one row per sagitta |
| `ranking.csv` | Every case, feasibility verdict and reason, score |
| `exports_vs_replicas.csv` | Supplied parts against their parametric rebuilds |
| `fig_torque_angle_*.png` | Torque–angle curves per group, and for the exports |
| `fig_design_space.png` | T90, ε90 and the score against sagitta, all turn counts; values read after a snap are hollow |
| `cases/*.json` | One record per case: full torque–angle curve, per-increment strain, clearance, spread, convergence, mesh |
| `input_step/` | The three supplied STEP exports |

Input SHA-256:

```
c8a008cae3285cd9f7706a4b11194134b8698da2f72fb1298e62ea729f6ef875  A8_PIP_Meander_2turn_2mm.STEP
0a8eb415ec479976a84f27403451e77767734bd0b4f3b256ae3a74b7f61a51ab  A8_PIP_Meander_3turn_2mm.STEP
747637e6cb72d6dc950c048c1f1d4c2e2016e82b88c8ef96333120f16b0afd8d  A8_PIP_Meander_3turn_2mm_2.STEP
```

## Reproduce

```bash
python scripts/a8_meander_study.py --steps-dir results/a8_meander_study/input_step --out results/a8_meander_study
python scripts/a8_meander_report.py --study results/a8_meander_study
```

The study resumes: a case whose record exists is skipped, so several copies can be run
at once on a multi-core machine. Solver: CalculiX 2.21 (Ubuntu `calculix-ccx`), single
threaded; about 35 minutes a case for 2 and 3 turns, 1.5–2 hours for 4.

## Open

- A run at 1.8 and 2.4 mm section height, to replace the beam-theory scaling in the
  recommendation with an FEA number.
- The real PIP axis and finger profile from the hand CAD, and the torque the hand needs
  — then "enough spring" can be judged, not only ranked.
- A tensile test of the printed filament, and a bench torque–angle measurement of one
  printed strip. Until then nothing here is validated.
