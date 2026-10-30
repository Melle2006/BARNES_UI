# Type B round 2: test plan

**The question this round answers:** does giving the joint something to carry the
tendon's compression (a bearing), or a deeper tendon, or both, let a Type B joint
hold a useful fingertip force without buckling, squashing or twisting? And how
does that compare with the pinned Type A joint?

Everything is tested at the **PIP**, in the single-joint rig (`test_rig/`), with
two exceptions:
* Type A is tested as its own whole finger (§5).
* One finger of the best Type B variant is tested at the end (§6).

Predicted values are in [`predictions.csv`](predictions.csv). They are rough
models at a **provisional 12 MPa modulus**, and every force scales with the
real modulus. The tensile and compression specimens in this batch measure that
modulus (§4.6), so the predictions can be rescaled before comparing.

## 1. Shortlist (print these first)

| # | Variant | Folder | Why it is here |
|---|---|---|---|
| 1 | `B1_t200_notch050` | `../B1_hourglass/` | Round 1's strongest. Its short, thick notch is the only round-1 joint predicted to hold more than 1 N at the hook |
| 2 | `B1_t200_notch050_deep` | `deep_offset/` | Same flexure, deep tendon: tension effect alone |
| 3 | `B3_t200_w30` | `../B3_dual_leaf/` | Round 1's agreed first test, at its stiffest |
| 4 | `B3_t200_w30_deep` | `deep_offset/` | Same, deep tendon |
| 5 | `B5_t200_a45_deep` | `deep_offset/` | Cross-axis pivot (fixed centre) at the deep offset. Its round-1 original is in the second batch |
| 6 | `B4_t100_a60_deep` | `deep_offset/` | Rolling contact. Built deep because as built its lever falls to 0.9 mm by 60° |
| 7 | `B8_y00_r150` | `./` | Knuckle-in-cup bearing, central |
| 8 | `B8_y20_r125` | `./` | Knuckle 2 mm dorsal: longest lever of anything as built |
| 9 | `B8_y20_r125_deep` | `deep_offset/` | Longest lever of all |
| 10 | `B9_n150` | `./` | Compression strut |
| 11 | `B9_n150_deep` | `deep_offset/` | Strut, deep tendon |
| 12 | **Type A index finger** | `reference_parts/type_a_hand_assembly.step` | Baseline: a pinned joint carries the compression in the pin |

**Second batch** (if the shortlist is promising):
* the softest of each family, as built and deep: `B1_t100_notch100`, `B3_t100_w20`, `B5_t100_a75`, `B6_n6_t100`;
* `B6_n4_t200` and its deep copy;
* the two lattices (`B_T090_X3`, `B_T120_X3`) and their deep copies;
* `B4_t080_a60`, `B9_n100` and their deep copies;
* `B8_y00_r150_deep`.

**Deep-offset variants need the deep phalanges**
(`deep_offset/deep_phalanges/`). Round-1 phalanges carry the tendon at the old
depth and will not line up. All other variants use `../common_phalanges/`. The
rig takes both kinds.

### Predictions for the shortlist (PIP, E = 12 MPa)

| # | Variant | Tendon lever at 0° / 60° (mm) | Spring k (N·mm/rad) | Tension per N on the 44.8 mm hook, at 0° | What carries the compression | Compression capacity (N of tension) | Hook force at that capacity (N) | Collars meet at |
|---|---|---|---|---|---|---|---|---|
| 1 | B1_t200_notch050 | 1.93 / 3.56 | 29.8 | 23.2 | notch webs (buckling) | 133 | 5.7 | ~67–76° |
| 2 | B1_t200_notch050_deep | 3.40 / 4.83 | 29.8 | 13.2 | notch webs (buckling) | 133 | **10.1** | ~67–76° |
| 3 | B3_t200_w30 | 1.93 / 2.31 | 6.4 | 23.2 | leaves (buckling) | 33 | 1.4 | ~67–76° |
| 4 | B3_t200_w30_deep | 3.40 / 3.59 | 6.4 | 13.2 | leaves (buckling) | 33 | 2.5 | ~67–76° |
| 5 | B5_t200_a45_deep | 3.40 / 4.83 | 7.6 | 13.2 | crossed strips (buckling) | 34 | 2.6 | ~67–76° |
| 6 | B4_t100_a60_deep | 3.40 / 1.38 | 0.9 | 13.2 | rolling lobes (contact) | 19 | 1.2 | ~67–76° |
| 7 | B8_y00_r150 | 1.93 / 3.56 | 0.2 | 23.2 | knuckle (contact) | 28 | 1.2 | ~67–76° |
| 8 | B8_y20_r125 | 3.93 / 5.29 | 0.2 | 11.4 | knuckle (contact) | 23 | 2.1 | ~52° |
| 9 | B8_y20_r125_deep | 5.40 / 6.56 | 0.2 | 8.3 | knuckle (contact) | 23 | 2.8 | ~52° |
| 10 | B9_n150 | 1.93 / 3.56 | 6.7 | 23.2 | strut neck (crushing) | 14 | 0.6 | ~67–76° |
| 11 | B9_n150_deep | 3.40 / 4.83 | 6.7 | 13.2 | strut neck (crushing) | 14 | 1.1 | ~67–76° |
| 12 | Type A index, best existing holes | PIP h = 3.0 mm | cover only | about 15 | the pin | the pin (PLA) | servo-limited, about 4 N at the fingertip ([docs/11](../../docs/11-tendon-routing-type-a-b.md)) | 110° (CAD) |

How to read these predictions:

* **"Compression capacity"** is the tendon tension at which the compression path
  is predicted to give way: Euler buckling for leaves and strips; for the
  bearings and the strut, the tension at which their contact or neck would
  reach about 20 % compressive strain. The capacities are linear in E. A bearing
  is not predicted to be *stronger* than a thick notch (row 1 vs 7–11). What it
  should change is **how** the joint fails: a contact squashes gradually and
  recovers, where a leaf buckles suddenly. The test is to find out whether
  that is so.
* **"Collars meet at"**: the round-1 FEA put the PIP collar contact at about 76°,
  and the simple formula used here gives 67°. Expect the range to stop there
  unless the collars are relieved palmar. B8_y20 meets earlier, about 52°,
  because its pivot is dorsal. That is a trade against its longer lever which
  the test has to settle.
* **B4 as built** (not on the shortlist) has a lever that falls from 1.93 to
  0.86 mm by 60°, because the rolling contact moves palmar. It is in the second
  batch to confirm that.

## 2. Print settings

Every Type B part in this batch, and the specimens, from **the same spool in
the same session**.

* **Material:** the TPU in use (SUNLU TPU 90A per the project notes). **Dry it**
  first: about 50 °C for 4–6 h, or to the maker's instructions. Keep it in a dry
  box while printing. Wet TPU strings, foams, and prints weaker and softer,
  which would land in the results as "the design".
* **Infill 100 %.** Every flexure is thin enough that the slicer would make it
  all perimeters anyway; 100 % stops it leaving voids in the collars, tabs and
  bearings. Use the **same wall count, line width (0.4 mm), layer height
  (0.2 mm), temperatures and speed** for every module, and write them down.
* **Orientation: leaves lengthwise in the XY plane.** Lay each joint module on
  its side, lateral axis vertical. Then every leaf, strip, notch web and bearing
  lane is laid down along its length in the XY plane, and its thickness is in
  the plane too, set by perimeters. Do not print modules standing on a tab end:
  that puts layer lines across every leaf, which is the direction it bends.
  * On its side, the upper lanes bridge between the collars. Use supports
    *under the lanes only* (support blockers elsewhere). Peel them and check that
    no strand is left inside a bearing gap.
  * The 0.3 mm bearing gaps (B4, B8) must be open after printing. Run a 0.25 mm
    feeler gauge or shim through each one. If a gap has fused, the print is a
    reject, not a stiff variant.
* **PLA parts** (phalanges, rig, adapter, pulley): standard settings, at least 3
  perimeters. Print the rig base on its side plate. The protractor is then
  vertical: 4 perimeters, and a brim if it wobbles.
* **Specimens:** print in the same session as the modules.
  * `tensile_1BA_t*_flat`: flat on the bed.
  * `tensile_strip_t*_edge`: standing on the long edge, 6 mm tall. These are laid
    down exactly as a leaf is when its module lies on its side.
  * `compression_d10_h10`: on its flat end.
  * Print at least 3 of each.

### Check every part before testing

* **Calipers:** measure every leaf, strip or neck thickness at 3 points along
  it, and its width. Measure each bearing gap with feeler gauges. Record them
  against the nominal values in `variants_summary.csv`.
  * Stiffness goes as thickness cubed: a 1.0 mm leaf printed at 1.1 mm is 33 %
    stiffer.
  * Analyse with the **measured** thickness. A part more than ±10 % off nominal
    is reprinted, not tested.
* **Weigh** each module (0.01 g scale). Weight divided by nominal volume ×
  density shows under-extrusion and voids.
* **Look** for gaps between perimeters, stringing inside the corridor, and
  bearing gaps that have closed.

## 3. The rig (`test_rig/`)

* **Setup.**
  * Clamp `rig_base` to a table edge by its side plate. The finger, the pulley
    and both weight strings then hang clear of the table.
  * Pin Phalanx 1 onto the post's dummy tab with two Ø2 pins. Plug the PIP
    module into Phalanx 1, and Phalanx 2 onto the module, all with the module's
    own pins. Plug `load_adapter` into Phalanx 2's distal socket.
  * The finger lies **palmar side up**, so flexion lifts the arm.
* **Tendon.** Use a braided line (e.g. 0.5–0.8 mm Dyneema/PE fishing line), the
  same line for every test.
  * Tie it through the adapter's Ø2 anchor hole. Run it back through Phalanx 2,
    the module and Phalanx 1, out of the back of the post, over the pulley (on a
    623ZZ bearing and an M3 bolt), and down to a weight hanger.
  * **Tension = total hanging mass × 9.81.** Record the hanger's own mass.
* **Fingertip force.** Hang a known weight from the arm's hook.
  * The three holes are 30, 37.5 and 44.8 mm from the nominal PIP pivot; 44.8 mm
    is the Type B finger's fingertip.
  * The torque the joint must hold is W·r·cos θ, where θ is how far the arm is
    raised.
* **Angle.** Read the vane's centre line against the scale (5° ticks, numbered
  every 10°), from the finger side.
  * The scale is centred on the nominal pivot. Where the pivot moves (B4, and the
    bending joints by 1–2 mm) the reading is good to about ±2°.
  * For better than that, photograph square-on and measure the arm's angle.
* **Calibrate pulley friction once.** Hang equal masses on both ends of a line
  over the pulley. Add mass to one side until it moves, and record that as a
  percentage. Correct the tensions by it (or ignore it if it is under 2 %).
* **Zero.** With no tendon tension and no hook weight, record the resting angle
  (self-weight and print set).

## 4. What to measure

For every shortlisted variant, at the PIP, at least **two printed copies**. Do
the steps in this order: they go from gentle to destructive.

1. **Tension against angle, nothing in the finger** (the free closing curve).
   * Add tension in small steps (about 0.2 N, then 0.5 N past 2 N), letting it
     settle 10 s at each, and record the angle.
   * Go up to the collar contact or a hard stop, then come back down in the same
     steps and record again. The difference is hysteresis.
   * Compare with `tension_unloaded_*` in predictions.csv. The slope near 0°
     gives k ÷ lever.
2. **Fingertip force held.** Hang W on the 44.8 mm hook. Raise the tension until
   the arm lifts off its rest, then until it reaches 30° and then 60°, and record
   the tension at each.
   * Repeat for W = 0.5, 1, 2, 3, 5 N, stopping when step 3's limit is reached.
   * Holding force at a tension T is the largest W the joint holds at 30°.
     Compare with `tension_per_N_hook_*` and `hook_N_at_capacity`.
3. **Where it gives way: buckling, squashing or twisting.**
   * With the arm held at 30° (a hook weight, or a stop clamped under it), raise
     the tension in steps until one of these happens:
     * **buckles:** the angle jumps, or a leaf visibly bows sideways;
     * **squashes:** the gap between the collars closes by more than 0.5 mm, or a
       bearing visibly flattens;
     * **twists:** the distal part rotates about the finger's axis by more than
       about 3°, or moves sideways;
     * **tendon cuts or pulls through**, or a part cracks.
   * Record the tension, which mode, and photograph it. The collar gap is
     measured with feeler gauges or calipers across the palmar side.
   * Release, wait 1 min and record the angle. Compare the tension with
     `compression_capacity_N`.
4. **Spring-back.**
   * Hold at 60° (or the maximum reached) under tension for 60 s, release
     completely, and record the angle at 1 s, 10 s, 60 s and 10 min.
   * Repeat after the 1,000-cycle mark in step 5.
5. **Cycles to failure.** Only on the copy that has not been taken to its limit
   in step 3.
   * Cycle 0 → 60° (or 80 % of the range) by hand or with the servo and the
     firmware ramp, with a hook weight at 50 % of the step-2 holding force at 30°.
   * Every 100 cycles, check the free angle and the tension to reach 30°.
   * Stop at a visible crack, a 20 % change in the tension to reach 30°, a 5°
     change in the free angle, or 10,000 cycles. Record which.
6. **Material** (specimens):
   * Tensile: pull each dog-bone and strip with hanging weights in steps, and
     measure the gauge length (marks 20 mm apart) with calipers or a
     photograph. Take E from 2–10 % strain, then go to break.
   * Compression: load the Ø10 × 10 cylinder in steps. E is the slope from 2–10 %
     strain. The bearings depend on this number.
   * Rescale predictions.csv by E_measured ÷ 12 MPa before comparing.

## 5. Type A baseline

The Type A index finger as assembled, guides on the existing holes chosen in
[docs/11](../../docs/11-tendon-routing-type-a-b.md), with screws standing proud:

| Joint | Proximal hole | Distal hole | Offset |
|---|---|---|---|
| MCP | MC 10.35 | PP 15.25 | 6.5 mm |
| PIP | PP 8.81 | MP 13.31 | 3.0 mm |
| DIP | MP 13.22 | DP 12.03 | 0.5 mm |

Measure steps 1–5 on the whole finger: free closing, fingertip force held,
spring-back and cycles. Step 3 (giving way) on Type A is the pin, the PLA or
the cover, so record which. It gives the Type B results a joint that is known
not to buckle to be judged against. If a single-joint comparison is wanted,
measure the PIP on its own by holding the MCP and DIP with tape.

## 6. Whole-finger confirmation

The best Type B variant from steps 1–5: print the full finger, with its deep
phalanges if it is a deep variant. Repeat steps 1, 2 and 4 with the servo at
the real horn radius. The real finger flexes three joints from one tendon, so
check the closing order as well (which joint moves first).

## 7. Results template

One row per printed copy per step. Copy the table into a sheet. Use measured
dimensions in the analysis, not nominal.

| Date | Variant | Copy | Leaf/strip/neck t measured (mm, 3 points) | Bearing gap (mm) | Mass (g) | Step | Hook r (mm) | Hook W (N) | Tension T (N) | Angle θ (°) | Collar gap palmar (mm) | Mode (buckle / squash / twist / cut / crack / none) | Cycles | Free angle after (°) | Photo | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | 1 free close | — | 0 | | | | | — | | | |
| | | | | | | 2 hold | 44.8 | | | | | | — | | | |
| | | | | | | 3 limit | 44.8 | | | 30 | | | — | | | |
| | | | | | | 4 spring-back | — | 0 | 0 | | | | — | 1 s / 10 s / 60 s / 10 min | | |
| | | | | | | 5 cycles | 44.8 | | | 0–60 | | | | | | |

Summary per variant, once all copies are done:

| Variant | E measured (MPa) | k measured / predicted | Hook N at 30° for T = 10 N, measured / predicted | Limit tension measured / predicted | Failure mode | Range reached (°) | Spring-back after 10 min (°) | Cycles | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

## 8. What would count as success

A Type B variant that, at the measured modulus:
* holds **at least 2 N at the 44.8 mm hook** at 30°;
* fails by gradual squash rather than sudden buckling or twist;
* returns to within 5° of its free angle after 10 min;
* survives 1,000 cycles.

If none does, the bearing has to be rigid. That is round 3: a PLA insert, or a
dual-material print of the bearing lane, using the same layouts.
