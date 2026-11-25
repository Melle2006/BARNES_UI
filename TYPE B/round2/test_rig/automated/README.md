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
| _(STL exports to come)_ | | | |

The parts point to an MG995 servo driving a four-bar linkage (ground link, crank, coupler) that
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
