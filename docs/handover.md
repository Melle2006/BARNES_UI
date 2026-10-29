# Where things stand

A working handover: what changed, what is unfinished, what is waiting on a decision, and
what you need on a second machine to pick any of it up. Written 29 October 2026 on
branch `workflow-redesign`.

Read [manual/running-a-simulation.md](manual/running-a-simulation.md) first if you want
the application itself. This file is the state *around* it.

---

## 1. What changed

Two commits, both on `workflow-redesign`, both pushed to `origin`.

### `8e687f0` — nonlinear FEA could not be run from the GUI at all

Every FEA submission failed instantly, on any geometry, with

    signal only works in main thread of the main interpreter

`gmsh.initialize()` installs its own SIGINT handler and CPython refuses to set a signal
handler from any thread but the main one. The GUI meshes in a worker thread, so the call
could never succeed there. Fixed in [`core/fea/meshing.py`](../src/barnes_ui/core/fea/meshing.py)
by passing `interruptible=False`, with a `TypeError` fallback for Gmsh older than 4.11.

Two things about this are worth carrying forward:

- **It looked like a geometry problem.** The reduced-order model never touches Gmsh, so
  it kept working while only the FEA failed. A failure that reproduces on every part is
  structural, not a bad part.
- **Every existing mesh test passed while the application could not mesh**, because they
  all call `generate_mesh` from the main thread, where the signal call is legal. The new
  `test_meshing_works_off_the_main_thread` meshes inside a `threading.Thread`. The reason
  nobody noticed is in `results/`: **every real analysis on this project was run from
  `scripts/`**, which execute on the main thread. The GUI path was never the path used.

### `7eac683` — the recorded run

[manual/running-a-simulation.md](manual/running-a-simulation.md) plus 14 screenshots in
`manual/images/`. A record of one sitting, not a description of intended behaviour.

---

## 2. Confirmed: the GUI reproduces the scripted answer exactly

**A GUI FEA run on the real A3 twin strap**, 29 Oct 17:52–18:58 local, to check that the
`8e687f0` fix holds on real geometry rather than only on a generated meander.

**It reproduces the scripted result to every digit reported.**

| | GUI run | Scripted (`results/a3_mesh_study/mesh_2.json`) |
|---|---|---|
| Rotational stiffness | **6.10327 N·mm/rad** | **6.10327 N·mm/rad** |
| Reaction moment at 2.00 deg | 0.2130442 N·mm | 0.2130442 N·mm |
| Mesh | 32965 C3D10, 61021 nodes | 32965 C3D10, 61021 nodes |
| Increments | 48 | 48 |
| Cutbacks | 285 | 285 |
| Converged | yes | yes |
| Wall clock | 3934 s | 2778 s |

Identical element and node counts mean Gmsh was handed the same geometry with the same
settings and produced the same mesh; identical increments and cutbacks mean CalculiX walked
the same path through it. The only difference is wall clock, and that is the machine being
busy rather than anything about the solve.

The run is archived at `%LOCALAPPDATA%\Temp\barnes_ui_runs\c284be4e014d` with its
`input.inp`, `results.dat`, `results.sta`, `solver.log` and a `manifest.json`. Note that
temp directories do not survive indefinitely — copy it somewhere permanent if the evidence
matters.

One thing the manifest records that the panel does not surface: the mesh quality block
reports **2079 poor elements** and a **maximum edge ratio of 1100**, on a mesh that
nonetheless converged and matched. Worth knowing before pushing the element size down
further.

### Reproducing it

Parameters, taken from `scripts/a3_joint_stiffness.py` so the comparison is like for like:

| Parameter | Value | Constant |
|---|---|---|
| Thinnest feature | 1.000 mm | `SMALLEST_FEATURE_MM` |
| Elements across it | 2, so 0.5 mm | the converged mesh from the study |
| Element type | C3D10, second order | default |
| Prescribed rotation | 2.00 deg | `rotation_deg` |
| Attachment depth | 3.20 mm | `COLLAR_DEPTH_MM` |
| Axis passes through | 6.090, 44.935, 5.440 mm | `AXIS_POINT_MM` |
| Modulus | 12.0 MPa provisional | default |

To redo it from scratch: load `reference_parts/A3_PIP_twin_strap_1.0mm.step`, go to
`Analyse ▸ Nonlinear FEA`, set the six values above, press **Run FEA**. The axis is the
only field that is not already correct by default, and it matters — the panel warns that a
run at the wrong axis height converges perfectly while reporting a different stiffness.

Budget about an hour. The reduced-order model on the same part takes seconds and lands
within 9–20 %, which is what it is for.

---

## 3. Open, waiting on a decision: choosing a TPU grade in the UI

Requested: select between TPU grades in the interface. Nothing has been built, because
what a grade should *carry* is a real decision and one of the three answers is something
the codebase refuses to do.

The material group in [`gui/panels/flexure_panel.py`](../src/barnes_ui/gui/panels/flexure_panel.py)
is currently one modulus spin box defaulting to 12.0 MPa. `settings()` returns
`youngs_modulus`, and `main_window` feeds it to `provisional_tpu()` for both the
reduced-order model and the FEA. A selector has to thread a grade through that same path.

| Option | What happens | Status |
|---|---|---|
| **Label + calibration slot** | The grade is recorded on the model, named in every caveat and export, and each grade gets a slot for a tensile fit. Until data exists the modulus stays a stated input and results stay `UNVALIDATED_ASSUMPTION`. Picking 90A changes labelling and provenance, not stiffness. | Recommended. Invents nothing |
| **Real fitted models per grade** | Supply stress–strain points per grade and selecting a grade loads a fitted model through the existing `fit_uniaxial` path. | Blocked on data |
| **Hardness → modulus correlation** | Each grade sets a number automatically. | **Refuse.** The README, risk register and `core/material/models.py` all reject it: the correlations carry large scatter and give a small-strain modulus, which is not what a hyperelastic fit needs |

### What is needed to calibrate a grade

Per grade, a CSV of two columns:

| Column | Quantity | Units |
|---|---|---|
| 1 | Engineering strain, ΔL/L₀ | dimensionless, **not** percent |
| 2 | Engineering stress, F/A₀ | MPa |

`HyperelasticModel.fit_uniaxial` requires only equal lengths, strain > −1, and at least
as many points as the model has parameters (1 Neo-Hookean, 2 Mooney-Rivlin, 4 two-term
Ogden). Give it a few dozen. It records the fitted strain range so
`is_within_calibration` can flag extrapolation later.

Measurement notes that matter more than the fit:

- **A₀ from a micrometer on the printed specimen**, not the CAD dimension.
- **Strain from an extensometer or DIC, never crosshead displacement** — crosshead
  includes machine compliance and grip slip and overstates strain badly on soft TPU.
- Specimen printed with the **same spool, printer, nozzle temperature, layer height,
  orientation and infill** as the flexure, and ideally **at the flexure's 1.0 mm
  thickness**, because layer count through thickness changes the material.
- Also needed per grade: **density in g/cm³**, for gravity body loads
  ([`core/fea/loads.py`](../src/barnes_ui/core/fea/loads.py) converts to t/mm³).
- Worth knowing before spending effort: peak bending strain is **1.481 % at 90°** on the
  meander and ~1.2 % at 95° on the A3 strap. That is near-linear territory, so an
  accurately measured initial modulus over 0–15 % strain is worth more than a full
  large-strain characterisation.

A manufacturer datasheet is accepted and permanently tagged `datasheet_derived` — bulk
moulded material, not a printed part. Better than provisional, well short of a fit.

### The filament, and what its datasheet settled

The filament in use is **SUNLU TPU 90A, 1.75 mm**. Every reference in this project was
updated from 95A to 90A accordingly; the arguments were always grade-agnostic, so only the
grade named changed.

Its published data yields **one usable figure: density 1.23 g/cm³**, for gravity body
loads via `density_from_g_per_cm3(1.23)`. It supplies **no modulus and no stress–strain
curve**, and its mechanical rows contradict the manufacturer's own store listing — 10 ± 5 %
elongation against ≥1000 % for the same filament. Item 7 of
[06-required-inputs.md](06-required-inputs.md) records the full table and why it cannot be
used. **The tensile test is still blocking**; the datasheet did not change that.

---

## 4. Numbers established, and one correction

| | A3 twin strap (real CAD) | Generated meander |
|---|---|---|
| FEA stiffness | **6.10336 N·mm/rad** | 0.811602 N·mm/rad |
| Reduced-order | 6.65 – 7.34 (clamp band) | 0.0279319 N·mm/rad |
| ROM / FEA ratio | **1.09 – 1.20** | 0.0344 |
| Mesh convergence | 0.94 % between 1.0 and 0.5 mm | none run |

**The correction:** during this session I reported a 29× ROM-versus-FEA gap and implied
it was a general problem. It is **specific to the generated meander run**. On the real
part the reduced-order model is within 9–20 %, which is respectable for a screening tool.
The likely cause of the meander figure is the joint axis used there — the midpoint of two
surface picks, roughly 2 mm off the part centre in X — and the panel warns that a run at
the wrong axis converges perfectly while reporting a different stiffness. The manual's
section 5 still frames this as a general gap and **should be corrected**; see next steps.

Also carried forward from the committed mesh study: both A3 solves logged **~280 cutbacks
across ~49 increments**, and the script's own note says a cutback count far above the
increment count has previously been the only visible symptom of a badly posed boundary
condition. That sits on the converged, committed 6.103 figure and deserves a look before
the number is quoted anywhere load-bearing.

---

## 5. Second machine: what you need

```bash
git clone https://github.com/Melle2006/BARNES_UI.git
cd BARNES_UI && git checkout workflow-redesign
python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.lock.txt
.venv/Scripts/python.exe -m pip install -e .
```

Launch:

```bash
.venv/Scripts/python.exe -m barnes_ui
```

Two things are **not** in the repository and have to be dealt with separately:

1. **CalculiX.** A separate native binary — see
   [08-calculix-installation.md](08-calculix-installation.md). On the original machine it
   lives at `%LOCALAPPDATA%\Programs\CalculiX\calculix_2.23_4win\ccx_static.exe`. The
   FEA panel's `Look again` button re-probes after an install. Without it the FEA is
   unavailable and the reduced-order model is **not** substituted for it.
2. **Material data.** Item 7 of [06-required-inputs.md](06-required-inputs.md) is still
   open. Nothing in this project is experimentally validated.

The geometry *is* all here. `reference_parts/` holds
`meander_2turn/3turn/3turn_wide/5turn.step`, `pip_joint_assembly.step` and
`A3_PIP_twin_strap_1.0mm.step` — the last being the real part every committed result in
`results/` was measured on, so the clone above is enough to reproduce 6.103 N·mm/rad
without copying anything by hand. The parametric meander needs no file at all:
`Design ▸ Build and display` generates it.

Note that **this GitHub repository is public**, so the A3 strap is published with it.
That was a deliberate decision taken to make the work portable; it is recorded here
because git history keeps the file even if it is later deleted from the tree, so undoing
it means rewriting history, not just removing the file.

---

## 6. Driving the GUI, if you automate it

Two things that cost time here:

- **The window must genuinely have input focus.** `SetForegroundWindow` is not enough:
  tab clicks and workspace-button clicks are silently swallowed while another application
  holds keyboard focus, while *wheel* events still arrive, so the panel scrolls and looks
  responsive. Click the title bar once first.
- **Do not wheel-scroll with the pointer over a field.** The parameter fields are spin
  boxes and a wheel event over one edits it. During this session that silently moved the
  attachment depth, the prescribed rotation and the axis X coordinate. Scroll with the
  pointer over the **label column on the far left**, and re-read the inputs before every
  submission.

---

## 7. Next steps, in the order worth doing them

1. **Correct the manual's 29× framing** in section 5 of
   [manual/running-a-simulation.md](manual/running-a-simulation.md), noting the real part
   sits at 9–20 % and that the meander figure is probably an axis-placement artefact.
2. **Re-run the meander with a properly centred axis** to test that explanation. Cheap —
   that solve took about two minutes.
3. **Decide the TPU grade question** in section 3 and build the selector.
4. **Investigate the 285 cutbacks**, now confirmed identical in the GUI and the script, so
   they are a property of the model rather than of either runner. Worth resolving before
   6.103 is quoted externally.
5. **Get the tensile data.** Everything quantitative is blocked behind it, and until it
   arrives only the ranking between designs is sound.
