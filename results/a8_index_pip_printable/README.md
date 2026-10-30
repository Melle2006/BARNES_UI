# Printable A8 strip on the index-finger PIP

Second A8 study. It follows [../a8_meander_study](../a8_meander_study/README.md), which used
the original 2 mm drawn-across section on a finger inferred from the A8 rings. Here:

- **the finger is the real index PIP**, measured from `Assem3_A3_0.8_PIP_FitCheck.STEP`
  (pin, collar positions, and the two R 5.195 cams the strip rides over); and
- **the section is printable with a 0.4 mm nozzle**: drawn square to the path at a
  constant true width (1.2 mm = three lines).

Full write-up with figures: [../a8_report/index.html](../a8_report/index.html). The
same report is published at https://claude.ai/artifact/HXHxAYnaUUnXDVkwYDcvFH (private
to the owner until shared).

## Selected design

**2 turns, true width 1.2 mm, height 2.4 mm, lobe amplitude 4.4 mm, spine sagitta 2.75 mm
(bend radius 39.6 mm), ends at the A3 collar positions (y = 24.0 and 53.0 mm).**

| | |
|---|---|
| Restoring torque at 30 / 60 / 90 / 100° | 0.81 / 2.02 / 3.24 / 3.50 N·mm |
| Initial stiffness | 1.14 N·mm/rad |
| Peak strain at 90° (away from the tied ends) | 16.5 % (26 % at the collar junction; fillet it) |
| Clearance to the real Index_PP / Index_MP at rest | 1.06 / 0.39 mm |
| Volume | 118.2 mm³ |

Model files in [model/](model/):

- `A8_PIP_2turn_printable_w1.2_h2.4_s2.75_Assem3_frame.step` — drops into the hand
  assembly where the A3 strap sits.
- `A8_PIP_2turn_printable_w1.2_h2.4_s2.75_IndexPP_frame.step` — in the Index_PP
  part's own coordinates.

## Findings

1. On the real joint the 2-turn strip does **not** snap. The snap found in the first
   study came from the crease in the guessed finger.
2. Strain, not stiffness, limits the design: wrapping R 5.2 cams costs about h/2R of
   bending strain by itself.
3. Height raises torque roughly twice for 1.2 → 1.8 mm, with only a small strain
   increase. Width does not come free: 2.4 mm-wide strips reach 24–25 % strain, a
   2.0 mm-wide 3-turn reaches 45 %.
4. 2 turns beats 3 at every height. At h 2.4 and s 3.5: 3.03 N·mm at 15.1 % for 2 turns,
   against 1.96 N·mm at 20.3 % for 3 turns.
5. The best curvature is the flattest arch that clears the real middle phalanx. At
   2.5 mm sagitta the clearance is 0.17 mm (rejected); 2.75 mm gives 0.39 mm. Use 3.0 mm
   (R 36.5 mm, −3 % torque, 0.60 mm clearance) if prints come out proud.

## Selection rules

From `scripts/a8_printable_report.py`:

- feasible only if it clears the real phalanx solids by at least 0.25 mm
  (`cad_clearance.json`), shows no torque drop anywhere in 0–100°, and stays at or
  below 20 % strain at 90°;
- the most torque at 90° wins;
- within 3 % of the best, the lower profile wins.

## Files

| File | What |
|---|---|
| `matrices.md`, `matrix_*.csv` | One table per turns/width/height group, rows by sagitta |
| `ranking.csv` | Every case, verdict and reason |
| `cad_clearance.json` | Minimum distance from each design to the real Index_PP and Index_MP |
| `cases/*.json` | Per case: full torque–angle curve, per-increment strain, clearance, convergence |
| `fig_*.png` | Torque–angle curves, torque against strain, height trade-off, plan views, fit render |
| `model/` | The selected strip as STEP |

## Not run

- **1.6 mm-wide 2-turn at 2.5 mm sagitta:** it touches the middle phalanx at rest.
- **3.2 mm-wide 2-turn:** stopped, because the 2.4 mm one was already over the strain
  limit.
- **3-turn at 0.8 mm width, and 3-turn at h 2.4 with s 2.5–3.0:** skipped, as the
  trends showed they could not win.

## Reproduce

```bash
python scripts/a8_meander_study.py --finger index_pip --groups printable,printable_wide,printable_2t --out results/a8_index_pip_printable
python scripts/a8_printable_report.py --study results/a8_index_pip_printable
```

The `cad_clearance.json` check needs the hand assembly STEP. It is not committed, because
it is the user's full hand CAD.
