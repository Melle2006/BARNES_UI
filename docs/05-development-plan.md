# Development Plan

Seven phases. Each has acceptance criteria that are **testable statements**, not descriptions of
intent — a phase is complete when someone else can run the stated check and see it pass, not when
the code "looks done".

Phases are sequential because each depends on the previous one being trustworthy. Resist the urge
to start Phase 5 (the visually impressive one) before Phase 3 has established whether the numbers
mean anything.

---

## Phase 1 — CAD import and inspection

**Goal:** open real CAD files and measure them correctly.

**Deliverables**
- Application launches on Windows from `python -m barnes_ui`.
- Import STEP, IGES, BREP, STL, DXF.
- Interactive 3D viewport: rotate, zoom, pan, fit, standard views, section plane.
- Solid tree with per-solid visibility.
- Per-solid properties: bounding box, volume, surface area, centre of mass, inertia, topology
  counts, validity.
- Unit detection from the STEP header; explicit confirmation prompt for unitless formats.
- Geometry validity report including disconnected solids and failed `BRepCheck_Analyzer` checks.
- Point-to-point measurement in the viewport.
- Save and reopen a project.
- Every displayed value carries its unit and its provenance tag.

**Acceptance criteria**
1. A STEP file exported from SolidWorks imports, displays, and reports a volume agreeing with
   SolidWorks' mass-properties dialog to **better than 0.1 %**.
2. The unit declared in the STEP header is detected and shown; changing it rescales every
   reported dimension consistently.
3. An STL import displays, is marked `is_exact = False`, and prompts for units before any
   dimension is treated as authoritative.
4. A multi-solid STEP assembly lists each component separately with individually correct volumes.
5. A deliberately corrupted STEP file produces a clear error naming the problem, not a traceback.
6. `pytest` passes with no display attached.
7. `tests/test_architecture.py` confirms `core` imports no GUI library.

**Demonstration:** import the A8 flexure, read its true bounding box, volume and extrusion depth,
and compare against the screenshot-derived estimates currently in use.

---

## Phase 2 — Flexure geometry and reduced-order mechanics — **COMPLETE**

**Measured results**, recorded against the criteria below. Reference part:
`A3_PIP_twin_strap_1.0mm.step` — twin arched straps between two PIP collars.

| Check | Result |
|---|---|
| Straight fixed-fixed member, pure imposed rotation vs 4EI/L | **9 ppm** (1.333321 vs 1.333333) |
| Section I extracted from CAD vs b·h³/12 | **0.166667 vs 0.1666667 mm⁴**, 6 significant figures |
| Depth-cubed scaling (depth ×2) | **exactly 8.000** |
| Two parallel members vs one | **exactly 2.000** |
| Castigliano vs independent frame-FE, like-for-like | **0.057 %** |
| Normal-section area along a constant-section strap | **constant to 0.0014 %** |

**Extracted geometry** (all `GEOMETRIC_MEASUREMENT`): strap section 2.000 × 1.000 mm,
area 2.00000 mm², I 0.166667 mm⁴, arc length 28.3813 mm, chord 27.8017 mm,
arc/chord 1.02084, members 5.700 mm apart. Collar walls 1.200 mm.

**Reduced-order result** with the provisional 12 MPa placeholder: 7.558 N·mm/rad at
neutral, 11.87 N·mm at 90°, peak bending strain 42 %. Tagged
`UNVALIDATED_ASSUMPTION` throughout, because the material is not calibrated.

**Three findings worth carrying forward.** Sections must be cut normal to the local
tangent rather than to a global axis: axis-normal cuts inflated the strap depth by up
to 5.2 % near the collars, which is about 16 % in stiffness. The axial flexibility term
matters — omitting it overstated stiffness by 13 %, because a shallow arch resists end
displacement largely by stretching; shear accounts for a further 1.7 %. And a
near-constant section profile must not be plotted on an auto-scaled axis, which
magnified 0.0014 % numerical variation into an alarming sawtooth.

**The 42 % peak strain is the headline caveat.** It is far outside small-strain
validity, so the linear model is being driven well beyond its range and the absolute
torque must not be trusted. Quantifying that error is Phase 3 criterion 7.

### Original specification

**Goal:** turn the solid into a mechanical model, with every assumption on screen.

**Deliverables**
- Centreline extraction for meander flexures, with an interactive correction workflow for
  ambiguous cases.
- Width profile `w(s)` and thickness profile `t(s)` along the arc length.
- Arc length, bend radii, minimum feature size, detected sharp internal corners.
- Meander turn count and span where reliably identifiable.
- Material module: Neo-Hookean, Mooney-Rivlin, Ogden; parameter entry from datasheet or fitted
  from uploaded uniaxial test data; recorded validity strain range.
- Clearly separated **provisional mode** when no calibrated data exists.
- Reduced-order curved-beam model integrating `I(s) = t(s)·w(s)³/12` along the centreline.
- Force–displacement and torque–angle curves, tangent and secant stiffness.
- An assumptions panel listing every simplification in force for the displayed result.

**Acceptance criteria**
1. For a straight constant-section beam, the reduced-order model matches the Euler–Bernoulli
   closed-form tip stiffness to **better than 1 %**.
2. For a quarter-circle curved beam, it matches the Castigliano closed-form result to
   **better than 2 %**.
3. Centreline arc length for a generated reference meander of known dimensions is recovered to
   **better than 0.5 %**.
4. Doubling the width increases bending stiffness by a factor of **8.0 ± 0.1**, confirming the
   cubic dependence is implemented correctly.
5. With no calibrated material, every output is visibly marked provisional, and that mark
   survives CSV export.
6. The assumptions panel is non-empty for every result and names the small-strain and
   slender-beam assumptions explicitly.

**Demonstration:** torque–angle curve for the A8 flexure over the PIP range, with the assumptions
list beside it and a statement that the error against FEA is not yet known.

---

## Phase 3 — Nonlinear FEA — **7 of 8 CRITERIA MET, VERIFIED AGAINST A REAL SOLVER**

CalculiX 2.23 is now installed and every benchmark below has been run through it. See
[08-calculix-installation.md](08-calculix-installation.md) for what was installed, why,
and what checking it revealed.

| # | Criterion | Status |
|---|---|---|
| 1 | Cantilever vs analytical, < 2 % | **MET — 0.75 % in CalculiX** (0.503757 N vs 0.500000 N); 0.7 % in the independent backend |
| 2 | Hyperelastic uniaxial vs Neo-Hookean closed form, < 1 % | **MET — worst 0.094 %** across stretches to λ = 2.0, in CalculiX with `*NLGEOM` |
| 3 | Mesh convergence, < 2 % between two finest | **MET — 0.012 %**, monotonic over four refinements |
| 4 | Reaction = applied load, < 0.5 % | **MET — 0.0000 %** |
| 5 | Non-converged run reports failure, no result shown | **MET** — `tagged_moment` raises rather than returning a caveated number |
| 6 | CalculiX absent → FEA disabled, no fallback | **MET** — tested against the machine's actual state |
| 7 | Reduced-order vs FEA discrepancy on the real flexure | **IN PROGRESS** — the A3 part meshes (32,965 C3D10) and solves; the comparison figure is not yet recorded |
| 8 | CalculiX viscoelasticity resolved | **MET — resolved: not available.** See [03-solver-comparison.md](03-solver-comparison.md) |

**Criterion 8, settled.** CalculiX has **no** viscoelastic material capability. There is
no `*VISCOELASTIC` keyword; `*VISCO` is a step card for viscoplastic analysis, not a
material; `*CREEP` is irreversible overstress creep requiring `*ELASTIC`; and no
`*HYPERELASTIC` model carries time or rate dependence. A `umat` is the only route and
is not documented as supported. This was the project's one openly unverified claim and
it is now closed against the manual.

**The cantilever benchmark.** Verified with an independently implemented solver
(`scikit-fem`) on the same Gmsh mesh, because unit errors and boundary-condition
mistakes are likelier than solver errors. Tip deflection converged to 19.904 mm against
a beam-theory 20.039 mm. The remaining 0.5 % is physics, not error: a fully clamped end
face restrains the Poisson contraction that beam theory allows freely, so a 3D model is
legitimately stiffer.

**Three bugs found during verification**, each by measurement rather than review:

- The verification backend was handed all 4658 mesh nodes while only the 2610 corner
  nodes appeared in the connectivity. `scikit-fem` silently renumbered the unreferenced
  ones away, producing 5490 unconnected degrees of freedom and an exactly singular
  stiffness matrix. The symptom pointed at the boundary conditions; the cause was the
  node array.
- The first attempt mapped vector-P2 degrees of freedom by assuming the first
  `3 × n_points` were corner nodes in mesh order. They are not.
- Nodal lumping of the end load was replaced by a consistently integrated facet
  traction, so the applied resultant is mesh-independent.

**Four defects that only a real solver could expose.** The deck generator passed every
structural test and was still wrong in four ways, each found by submitting to `ccx`:

- The runner invoked `ccx jobname` instead of `ccx -i jobname`. Without the flag
  CalculiX prints its usage banner and **exits 0 without solving** — a successful-looking
  run with no results.
- Gmsh and CalculiX order C3D10 mid-side nodes differently at positions 8 and 9. Every
  element failed with `*ERROR in e_c3d: nonpositive jacobian` despite positive corner
  volumes; a 10-node tet's Jacobian depends on all ten nodes.
- The log parser matched bare `error`, which is how CalculiX's linear solver prints its
  convergence *residuals*. A perfectly healthy run was declared non-converged.
- A `*RIGID BODY` whose member node set was never written produced a **converged null
  solve**: one `*WARNING`, then every displacement and reaction exactly zero, reported as
  CONVERGED. `FeaResult.is_null_solution` now catches this.

The last one is worth dwelling on: convergence was genuinely true and the result was
meaningless. It is the cleanest example this project has produced of why convergence is
a numerical property and not a statement about whether a question was asked.

**Mesh sizing on a part with interior thin features.** The default element size derives
from the bounding box's smallest extent. For the A3 twin strap that is 10.95 mm, giving
5.48 mm elements, while the actual strap is 1.0 mm thick and the collar wall 1.2 mm —
both interior. CalculiX rejected that mesh outright. The thinnest feature must be passed
explicitly for such a part, which is what `generate_mesh`'s `smallest_dimension`
argument is for.

### Original specification

**Goal:** a verified high-fidelity result, and the first honest measure of how wrong Phase 2 is.

**Deliverables**
- Gmsh meshing from the BREP solid, second-order tets, user-controlled refinement.
- Mesh display and quality metrics.
- CalculiX deck generation: `*NLGEOM`, `*HYPERELASTIC`, boundary conditions, prescribed rotation.
- Solver execution as a cancellable background task with live log streaming.
- Result parsing: displacement, stress, strain, reaction force and moment.
- Deformed-shape and field visualisation.
- Torque–angle curve from a sequence of prescribed rotations.
- Mesh-convergence study tooling.
- Convergence diagnostics surfaced in the UI: increments, cutbacks, residuals, warnings.
- Side-by-side comparison of reduced-order and FEA curves with the gap quantified.
- Full run archive as specified in the solver document.

**Acceptance criteria**
1. A cantilever under small load matches the analytical tip deflection to **better than 2 %**,
   confirming units, boundary conditions and the deck generator are correct.
2. A hyperelastic uniaxial tension test on a single element reproduces the analytical
   Neo-Hookean stress–stretch relation to **better than 1 %**.
3. A mesh-convergence study on the real flexure shows reaction moment changing by **less than
   2 %** between the two finest meshes, and the result reports which mesh was used.
4. Reaction moment at the fixed support equals the applied moment to **better than 0.5 %**
   (global equilibrium check).
5. A non-converged run is reported as failed. **No result is displayed.** Verified by a test
   that deliberately forces divergence.
6. With CalculiX absent, FEA features are disabled with an installation message, and the
   application does not fall back to the reduced-order model.
7. The reduced-order versus FEA discrepancy for the A8 flexure is **measured and recorded** —
   whatever its value. A large discrepancy is a valid, useful outcome.
8. CalculiX's viscoelastic capability is checked against the manual and the finding recorded in
   `03-solver-comparison.md`, replacing the current "unverified" note.

**Demonstration:** both curves on one plot, discrepancy stated as a percentage, mesh-convergence
table alongside.

---

## Phase 4 — Assembly import and flexure integration

**Goal:** attach a parametric flexure to a real joint without distorting it.

**Deliverables**
- STEP assembly import preserving component placement.
- Component tree with visibility, selection, naming.
- Joint definition UI: pick proximal and distal components, define axis, set motion limits.
  Cylindrical faces offered as candidate axes; never auto-accepted.
- Parametric flexure template (A8 meander family) regenerated from parameters.
- Attachment region selection on both components.
- Adaptation: span, length, turn count, width, thickness, position, orientation.
- Before/after comparison listing exactly which parameters changed.
- Interference checking across the motion range.
- Safety checks: minimum feature size, excessive required strain, new stress concentrations,
  self-intersection.
- Export of the modified assembly plus its analysis configuration.

**Acceptance criteria**
1. A STEP assembly imports with component placement matching SolidWorks to **better than 0.01 mm**
   on a spot-checked reference point.
2. A flexure regenerated at its original parameters reproduces the original volume to **better
   than 0.5 %** — proving the template matches the real design before it is used to make changes.
3. Adapting to a new attachment span changes only the intended parameters; thickness is
   preserved exactly unless explicitly varied.
4. Interference between the adapted flexure and a phalanx is detected at a known-bad
   configuration.
5. A flexure with a feature below the manufacturable minimum is **flagged and not auto-approved**.
6. Every adaptation produces a parameter-change report.

**Demonstration:** A8 flexure adapted onto a PIP joint, interference clean across the full range,
parameter diff shown.

---

## Phase 5 — Whole-hand kinematics and reduced-order coupling

**Goal:** see the hand move, with restoring torque that comes from Phase 3.

**Deliverables**
- Forward kinematics for defined joints.
- Joint angle sliders and time-based motion profiles.
- Animated playback.
- Reduced-order joint springs fitted to Phase 3 torque–angle curves.
- Plots: angle vs time, restoring torque vs angle, flexure strain vs angle.
- Design comparison on one set of axes.
- **Mode 1 / Mode 2 separation visibly enforced in the UI.**

**Acceptance criteria**
1. Kinematic preview is labelled as such and displays no force or torque values.
2. A fitted joint spring reproduces its source FEA torque–angle data to **better than 1 %** over
   the fitted range, and refuses to extrapolate beyond it without a visible warning.
3. Motion through a full range completes without interference, or reports where it occurs.
4. Two flexure designs are compared on one plot with their provenance tags shown.
5. Every Mode 2 result displays the reduced-order caveats: no contact-state change, no loading
   history, quasi-static.

**Demonstration:** PIP joint driven through its range; flexure bends; restoring torque plotted
against angle, traceable to the FEA run that produced it.

---

## Phase 6 — Advanced coupled simulation

**Goal:** establish how much further the physics can honestly be pushed.

This phase is explicitly **investigative, with a permitted negative outcome**. "We tried
self-contact in CalculiX, it would not converge reliably, here is the evidence" is a successful
result for this phase.

**Deliverables** — each contingent on the preceding investigation succeeding
- Flexure-to-phalanx contact with friction.
- Self-contact of the flexure.
- Mechanical stops and joint limits in the structural model.
- Gravity and tendon loading.
- Viscoelastic material behaviour, **only if** Phase 3 confirmed solver support **and** rate-
  dependent test data exists.
- A documented statement of which effects are modelled and which are omitted.

**Acceptance criteria**
1. Each capability is **either** demonstrated on a benchmark with a convergence record **or**
   documented as not achievable with the current solver, with evidence.
2. No capability is enabled in the UI until it has passed its benchmark.
3. Where a coupled result exists, it is compared against the Phase 5 reduced-order prediction and
   the difference quantified — this is what tells us whether the reduced-order model was adequate.

---

## Phase 7 — Optimisation and experimental calibration

**Goal:** search the design space, and close the loop against reality.

**Deliverables**
- Parameter sweeps over turn count, width, thickness, span, bend radius, attachment spacing.
- Objectives: restoring torque at a target angle, effective stiffness, range of motion, peak
  strain, stress-concentration indicators, clearance, manufacturability.
- Multi-objective optimisation with Pareto front visualisation.
- Sensitivity analysis against material-parameter uncertainty.
- Material calibration from tensile and flexural test data.
- Comparison of predicted against measured torque–angle curves.

**Acceptance criteria**
1. A sweep reproduces known-correct results for designs already analysed individually.
2. Optimisation **refuses to run** on a model that has not passed its validity checks.
3. Conflicting objectives produce a Pareto front, not a single declared winner.
4. Sensitivity analysis reports how much the optimum shifts under stated material uncertainty.
5. At least one predicted torque–angle curve is compared against a physical measurement, and the
   agreement — good or bad — is recorded.
6. Results validated against experiment are retagged `EXPERIMENTALLY_VALIDATED`; nothing else is.

---

## Cross-cutting rules for every phase

- No feature ships with a placeholder calculation presented as working. Not-yet-implemented is
  labelled as such in the UI and lists the next concrete step.
- No silent fallback. If the requested method is unavailable, say so; do not quietly substitute
  a weaker one.
- Tests accompany the code in the same commit.
- Each phase updates the documentation it invalidates.
- Any assumption introduced is registered in the assumptions panel and the risk register.
