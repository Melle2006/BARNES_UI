# Required Inputs

What the project needs from the user, in the order it becomes blocking. Items marked
**blocking** stop a phase from being completed; items marked *helpful* improve quality but have a
documented default.

---

## Needed now, for Phase 1

### 1. A8 flexure, as STEP — **blocking for the Phase 1 demonstration**

From SolidWorks: `File → Save As → STEP AP214 (*.step)`.

Why STEP and not the native part file: there is no reliable open-source reader for `.SLDPRT`
with parametric history. See [01-feasibility-assessment.md §4](01-feasibility-assessment.md).

Useful to send the same part in two or three meander configurations — for instance the versions
with different turn counts that have already been explored — because comparing them is one of the
first things the tool should be able to do.

### 2. The SolidWorks mass-properties figures for that part — **blocking for acceptance**

`Tools → Evaluate → Mass Properties`, screenshot or copy out:
- Volume
- Surface area
- Bounding box dimensions
- Density and mass, if set

This is the reference the import is validated against. Phase 1 acceptance criterion 1 is that the
computed volume agrees with SolidWorks to better than 0.1 %, and that cannot be checked without
the SolidWorks number. It is the single cheapest piece of verification in the whole project.

### 3. Units confirmation — *helpful*

Confirmation that the models are authored in millimetres. STEP declares this in its header so it
will be read automatically, but knowing the expected answer makes a mismatch obvious.

---

## Needed for Phase 2

### 4. A3 collar/cover geometry, as STEP — *helpful*

To confirm that the application treats A3 and A8 as distinct design elements with different
functions, rather than assuming they are interchangeable variants.

### 5. Which dimensions are verified and which were estimated — **blocking for trust**

Specifically needed: which of the currently used figures came from CAD measurement and which came
from screenshots. The known context includes a 1.2 mm extrusion depth and a single parallel strap
in the latest simplified configuration, and the note that some dimensions were estimated from
screenshots.

The application will treat every screenshot-derived figure as unverified until it has been
replaced by a measurement from the imported model. A list of which ones those are lets Phase 1
produce a direct before/after table.

### 6. Intended joint motion range — **blocking for Phase 2 torque-angle output**

For each joint of interest (PIP first):
- Neutral/rest angle
- Maximum flexion
- Maximum extension
- Which direction is positive

A torque–angle curve cannot be produced without knowing the angular range to produce it over.
Default if unspecified: PIP 0° to 100° flexion, which is approximately the anatomical range —
usable as a placeholder, and overridable in the UI, but it is a placeholder.

### 7. TPU material data — **blocking for any quantitative force prediction**

This is the most important item in this document.

**Minimum useful:** a uniaxial tensile test, as engineering stress vs engineering strain, on a
specimen printed with the **same filament, printer, nozzle temperature, layer height,
orientation and infill** as the real flexure, taken to at least the maximum strain the flexure
will experience. CSV of two columns is enough.

**Better:** three specimens for repeatability; plus a specimen printed at 90° to the first
orientation, to quantify how anisotropic the printed material is.

**Needed for any statement about hysteresis or rate effects:** cyclic loading at two or three
crosshead speeds spanning the range of real finger motion.

**Acceptable interim:** the filament manufacturer's datasheet. This is weaker than it looks — it
describes injection-moulded or extruded bulk material, not your printed part, and the difference
is usually significant. It will be accepted and labelled as datasheet-derived.

**Not acceptable:** deriving hyperelastic coefficients from the "95A" hardness label. Shore
hardness to modulus correlations carry large scatter and give a small-strain modulus, which is
not what a hyperelastic fit requires. The application will not do this. Without data it runs in
provisional mode and every force it reports is marked unvalidated.

Until item 7 arrives, Phases 1 and 2 still deliver real value — geometry, dimensions, relative
comparisons between designs — because relative ranking of variants is much less sensitive to the
absolute material parameters than absolute force prediction is.

---

## Needed for Phase 4

### 8. Prosthetic hand assembly, as a STEP assembly — **blocking**

`File → Save As → STEP AP214`, with **"Save all components as a single file"** selected so that
placement is preserved. Exporting components individually loses the assembly transforms and makes
the file close to useless for this purpose.

### 9. Joint definitions — **blocking**

STEP does not carry SolidWorks mates, so the kinematics cannot be recovered from the file. For
each joint to be analysed:
- Which component is proximal, which is distal
- Where the axis is and which way it points
- The motion limits
- Any mechanical stops

The application will offer cylindrical faces as candidate axes, but the choice must be confirmed.

### 10. Attachment method — **blocking for adaptation**

How the flexure is actually fixed to the phalanges: bonded, clamped, pinned, press-fit,
printed-in-place. This determines the boundary condition in the FEA and the attachment geometry
the template generates, and the two must match or the stiffness will be wrong.

Also needed: required clearances, mounting hole sizes if any, and the minimum manufacturable
feature size for the printer in use.

---

## Needed for Phase 7

### 11. Measured torque–angle data — *highest value item in the project*

A physical measurement of restoring torque against joint angle for a real printed flexure in a
real joint. Even a crude rig — a known mass on a known lever arm, angle from a photograph —
produces something enormously more valuable than another simulation.

This is what moves results from `FEA_RESULT` to `EXPERIMENTALLY_VALIDATED`, and it is the only
thing that can. Until a prediction has been checked against a measurement at least once, the
tool's absolute numbers remain unverified no matter how converged they are.

### 12. Target requirements — *helpful*

What the flexure is actually required to do: target restoring torque at a given angle, required
range of motion, maximum acceptable strain, fatigue life expectations. Optimisation needs an
objective, and these are it.

---

## Summary

| # | Item | Phase | Status | What is blocked now that all seven phases are built |
|---|---|---|---|---|
| 1 | A8 flexure STEP | 1 | **Blocking** | Phase 1 criterion 1 against a real export; the A8 meander family's template fidelity |
| 2 | SolidWorks mass properties | 1 | **Blocking** | Phase 1 criterion 1 and Phase 4 criterion 1 — the only untested link in the import chain |
| 3 | Units confirmation | 1 | Helpful | — |
| 4 | A3 collar STEP | 2 | **Supplied** | Nothing. Phases 2 and 3 were measured on it |
| 5 | Verified vs estimated dimension list | 2 | **Blocking for trust** | Whether any A8 dimension in this repository is a measurement |
| 6 | Joint motion ranges | 2 | **Blocking** (default available) | The angular range a joint spring has to be fitted over |
| 7 | TPU tensile test data | 2 | **Blocking for absolute forces** | Every absolute torque. Ranking and selection are **not** blocked — see R2 |
| 8 | Hand assembly STEP | 4 | **Blocking** | The assembly importer has no real file to run against, so it is not exposed in the GUI |
| 9 | Joint axes and limits | 4 | **Blocking** | A whole-hand chain. One joint works without it |
| 10 | Attachment method and clearances | 4 | **Blocking** | Whether an interference sweep is checking the right clearances |
| 11 | Measured torque–angle data | 7 | **Blocking — the last one** | Phase 7 criterion 5. Nothing in this project is experimentally validated and nothing can be until this exists |
| 12 | Design targets | 7 | Helpful | Objective weights that mean something |

### Where this stands now

Every phase is built. What is missing is not code; it is the four inputs that decide
whether the code is describing the right part.

Items 1, 2 and 5 are a few minutes of work in SolidWorks and would close the last
untested link in the CAD import chain — the reader is verified against a generated
assembly to 1e-5 mm, which proves the reader and nothing about how SolidWorks writes
placements.

Item 7 sets the accuracy ceiling for absolute forces and nothing else. Phase 7
measured that the design ranking does not move across an 8 to 18 MPa modulus range,
so screening and selection work today.

Item 11 is the only one that can produce an `EXPERIMENTALLY_VALIDATED` value. The
gate that would accept it is built and tested; it has nothing to accept.
