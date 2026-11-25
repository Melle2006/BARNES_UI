# Automated test rig (steps 4 and 5)

Changes to the Type B bending rig (`../build_test_rig.py`, procedure in
`docs/12-tpu-specimen-test-procedure.md`, Part 2) that automate step 4 (spring-back) and
step 5 (cycles). Design files supplied by the project team; this page lists them as they are
added.

| File | What it is | Replaces / adds to | Notes |
|---|---|---|---|
| `Base.SLDPRT` | Base for the automated rig | Rig base (`RIG`) | SolidWorks part, 1.5 MB |
| `Crank_New.SLDPRT` | Crank (current version) | new | supersedes `crank.SLDPRT` |
| `Coupler_new.SLDPRT` | Coupler (current version) | new | supersedes `coupler.SLDPRT` |
| `crank.SLDPRT` | Crank (earlier version) | new | kept for the record |
| `coupler.SLDPRT` | Coupler (earlier version) | new | kept for the record |
| `ground_link.SLDPRT` | Ground link of the linkage | new | the fixed link the crank and coupler work against |
| `MG995.SLDPRT` | MG995 servo (model) | new | the drive |
| `MG995_Assembly.SLDASM` | Servo sub-assembly | new | |
| `Fatigue_assembly.SLDASM` | Fatigue (cycling) sub-assembly | new | step 5 |
| `Master_Testrig_Assembly.SLDASM` | Whole test rig | new | top-level assembly |
| `rocker_arm.SLDPRT` | Rocker arm of the linkage | new | the output link (four-bar: ground, crank, coupler, rocker) |
| `S1_common_phalanges_02_Phalanx1.SLDPRT` | Phalanx 1 (as-built), as used in the assembly | S1 | SolidWorks copy of the repo's S1 |
| `S2_common_phalanges_04_Phalanx2.SLDPRT` | Phalanx 2 (as-built), as used in the assembly | S2 | SolidWorks copy of the repo's S2 |
| `s2_phalange.SLDPRT` | Modified Phalanx 2 | S2 | likely the S2 adapted to the linkage (to be confirmed) |
| `pan_head_tapping_screw_am.SLDPRT` | Pan-head tapping screw (hardware model) | — | fastener |
| `Shaft.SLDPRT` | Shaft | new | axle for the linkage (to be confirmed) |
| `slider_hole.SLDPRT` | Slider with a hole | new | guide for the moving end (to be confirmed) |
| `tpu_mimic.SLDPRT` | Stand-in for the TPU joint module | PIP module | CAD placeholder for the module, for fitting the assembly |
| `tpu_mimic_centre.SLDPRT` | Centre part of the TPU stand-in | PIP module | as above |
| `Wire_Boot.SLDPRT` | Wire boot | new | strain relief / guide for the tendon or a lead (to be confirmed) |
| _(STL exports to come)_ | | | |

The parts point to an MG995 servo driving a four-bar linkage (ground link, crank, coupler, rocker arm) that
cycles the finger for the fatigue test (step 5) and the spring-back test (step 4); details to be
confirmed. Open `Master_Testrig_Assembly.SLDASM` in SolidWorks with all the parts in this folder. The parts are SolidWorks files (SolidWorks 2015+ format), which
can't be opened outside SolidWorks; STEP or STL exports of each would let them be checked against
the rest of the rig and shown here.

## How it changes the procedure

_To be written once all files are in: what moves the tendon, how the angle and cycle count
are recorded, and what stays manual (steps 1–3)._

## Status

* Files: being added.
* Report: to be added to the test report when the rig results are written up.
