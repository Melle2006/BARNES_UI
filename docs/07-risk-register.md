# Risk Register

Ordered by expected damage, not by likelihood. The top entry is the one this project is mostly
designed around.

Severity: how bad it is if it happens. Likelihood: how probable it is if nothing is done about
it. "Mitigation" describes what the design does; "Residual" is what remains afterwards.

---

## R1 — Plausible but physically wrong results

**Severity: critical. Likelihood: high.**

The defining risk of this class of tool. A nonlinear FEA that converges, renders a smooth
deformed shape, and prints a torque of 14.3 N·mm is extremely persuasive — and is worth nothing
if the material coefficients were guessed, the mesh was too coarse, or the boundary conditions
did not represent how the part is really held. Design decisions get made from that number, parts
get printed, and the error only surfaces when the hardware does not behave as predicted.

Convergence is a statement about the numerics. It says nothing about whether the model
represents reality.

**Mitigation**
- Mandatory provenance tagging on every value, carried through every downstream operation and
  into exports; see [04-architecture.md §4](04-architecture.md).
- Provisional mode when material parameters are uncalibrated, marked visibly and permanently.
- An assumptions panel beside every result, never collapsed by default.
- Analytical benchmarks before the solver is pointed at real geometry (Phase 3 criteria 1–2).
- Mesh-convergence study required before a result is quoted.
- Global equilibrium check — reaction moment against applied moment — on every run.
- Reduced-order and FEA results always shown together with the gap quantified.
- Warnings when the material is driven outside its calibrated strain range.
- No silent fallbacks anywhere.

**Residual:** none of this catches a boundary condition that is self-consistent but does not
match the physical mounting. Only item 11 in [06-required-inputs.md](06-required-inputs.md) — a
physical measurement — closes that gap, and nothing else does.

---

## R2 — Material characterisation is the accuracy ceiling

**Severity: critical. Likelihood: certain, until test data exists.**

"TPU 95A" is a hardness grade. Filaments sold under it differ materially. A printed part differs
from bulk material through layer adhesion, orientation and infill, and is anisotropic. Every
absolute force this tool reports scales directly with the material parameters.

**Mitigation**
- Refuse to invent coefficients from the hardness label.
- Accept datasheet values, label them as datasheet-derived, and note that they describe bulk
  rather than printed material.
- Record the strain range a fit is valid over, and warn on extrapolation.
- Prefer fewer parameters when data is thin: a three-term Ogden will fit one curve beautifully
  and extrapolate badly.
- Phase 7 sensitivity analysis quantifies how much conclusions move under material uncertainty.

**Residual:** absolute predictions stay unvalidated until a specimen is tested. Relative
comparisons between designs remain useful throughout, because the material error is largely
common to both.

---

## R3 — Reduced-order model is wrong for tightly curved serpentines

**Severity: high. Likelihood: high.**

Beam theory assumes the cross-section is small compared with the radius of curvature and that
strains are small. In a tight meander turn, neither holds. The reduced-order model may be off by
far more than a few percent, and because it is fast and produces smooth plots it is exactly the
kind of output that gets trusted.

**Mitigation**
- The reduced-order model is labelled a screening tool everywhere, never a predictor.
- Its error against FEA is measured for the real geometry in Phase 3 and recorded.
- Both curves are always plotted together once FEA exists.
- The assumptions panel names the slender-beam and small-strain assumptions explicitly.

**Residual:** between Phase 2 and Phase 3 the error is genuinely unknown. The UI says so in
those words during that window.

**Update, measured.** The concern turned out to be understated, and in a different way
than expected. On a generated serpentine meander the planar bending-only model
overstated rotational stiffness by a **factor of 670** — not a percentage error, a
multiple. Two causes compounded: the model has no torsion term, and a meander's straight
runs lie along the joint axis so the planar projection collapses them to near-zero
length. 83.5 % of that member's stations were axis-aligned, and torsion carried ~30 % of
the strain energy.

Mitigated by `core/mechanics/spatial_beam.py`, which carries torsion and both bending
axes, and by a guard in the planar model that **refuses** a member with more than 15 %
of its length along the joint axis rather than warning about it. An error of this size
does not degrade gracefully, and a warning leaves the wrong number on screen.

---

## R3b — Geometry extraction that silently produces a wrong centreline

**Severity: critical. Likelihood: high, until guarded.**

Discovered while developing against a generated meander, and the most instructive
failure the project has had so far.

`extract_members` sweeps cutting planes along a straight axis. On a serpentine meander,
a plane normal to the sweep axis cuts a straight run *and* part of the adjacent turn,
and because they are one fused body the intersection returns as a single connected
region — a long sliver, not a cross-section. The region-count guard therefore never
fires.

The result: **no error raised**, section area overstated 3.1×, second moment overstated
4×, and an arc length of 1.61 mm against a true centreline of 62.14 mm. Every figure
looked like a figure. It was caught only because the test geometry had analytically
known properties to check against — which is itself the lesson.

**Mitigation**
- Two independent geometric guards on the axis sweep: the extracted path must span
  roughly the requested sweep range, and arc length can never be less than the path's
  own extent along that axis (geometrically impossible, so a reliable detector).
- `core/flexure/tracing.py` provides path-following extraction for members that double
  back, with its own continuity and section-area guards.
- The refusal message names the tracer, so the user is routed to the right tool rather
  than left stuck.

**Residual:** both guards are heuristics on symptoms. The underlying defence is what
caught it in the first place — developing against geometry whose answer is known
exactly. Any new extraction strategy should be validated the same way before being
pointed at a real part.

---

## R4 — Joint axes cannot be recovered from CAD

**Severity: high. Likelihood: certain.**

STEP carries placed geometry, not mates. The intended joint axis is simply not in the file. An
axis inferred from proximity or from the nearest cylindrical face can be plausible and wrong, and
a joint axis that is a millimetre off or a degree skewed changes the torque–angle curve.

**Mitigation**
- Never infer kinematic structure from proximity.
- Candidate cylindrical faces offered as suggestions requiring explicit confirmation.
- Defined axes stored in the project and displayed in the viewport so they can be eyeballed.
- Kinematic preview (Mode 1) exists partly as a cheap way to sanity-check an axis before
  spending hours of solver time on it.

**Residual:** a user can confirm a wrong axis. The visual preview is the main defence.

---

## R5 — Geometry adaptation distorts mechanical behaviour

**Severity: high. Likelihood: high if done naively.**

Stretching a solid to span a new distance changes cross-sections. Stiffness scales with the cube
of width, so a 10 % distortion of width is a ~33 % change in bending stiffness that nobody asked
for and nobody sees.

**Mitigation**
- Parametric regeneration from a template, never scaling of the imported solid.
- Thickness preserved exactly unless explicitly varied.
- Every adaptation produces a parameter-change report.
- Phase 4 criterion 2: regenerating at original parameters must reproduce the original volume to
  better than 0.5 %, which proves the template matches the real design before it is used to
  change it.
- Minimum feature size checked against manufacturability.

**Residual:** the template must genuinely match the A8 design family. If the real part has
features the template does not model, the regenerated part is a different part. Criterion 2 is
what detects this.

---

## R6 — Solver convergence failure on the hard cases

**Severity: medium. Likelihood: high for Phase 6.**

Large strain, near-incompressibility, thin members and self-contact together are where
open-source nonlinear solvers become unreliable. CalculiX's diagnostics are terse.

**Mitigation**
- Phase 6 is explicitly investigative with a permitted negative outcome.
- Failures are reported as failures; no result is displayed.
- Full solver log archived with every run.
- Code_Aster under WSL held in reserve, with solver integration behind an interface so switching
  does not mean rewriting the application.

**Residual:** some analyses may simply not be achievable with this toolchain. Documenting that
honestly is an acceptable result.

---

## R7 — Element locking in nearly incompressible material

**Severity: high. Likelihood: medium.**

Worth separating from R6 because it does not announce itself. First-order tetrahedra with a
near-0.5 Poisson's ratio lock and report a part as far stiffer than it is — and the run converges
cleanly. There is no error message; there is just a wrong number.

**Mitigation**
- Second-order tets (`C3D10`) as the default and only automatic choice.
- Hybrid element formulations used where CalculiX provides them for hyperelastic materials.
- Mesh-convergence study required, which exposes locking as a result that does not settle.
- Phase 3 criterion 2 — a single-element hyperelastic tension test against the analytical
  Neo-Hookean solution — catches a locking element formulation immediately.

**Residual:** a sufficiently distorted mesh in a tight turn can still misbehave. Mesh quality
metrics are shown.

---

## R8 — Unit errors

**Severity: high. Likelihood: low, but cheap to eliminate.**

A millimetre/metre confusion produces results wrong by 10³ to 10⁹ depending on the quantity.
Mixing N/mm² with N/m² between the geometry, the material entry and the solver deck is a classic
and quiet failure.

**Mitigation**
- One canonical internal unit system, converted at the boundaries only.
- STEP header units read rather than assumed; three-state unit confidence on the model.
- Units displayed beside every value in the UI and in every export.
- Unit round-trip tests.
- The cantilever benchmark (Phase 3 criterion 1) fails loudly on any unit error.

**Residual:** low once the benchmarks are in place.

---

## R9 — Reduced-order joint model used outside its validity

**Severity: medium. Likelihood: medium.**

Condensing FEA into a torque-vs-angle spring is sound only while the joint's torque depends on
angle alone. It stops being true when contact state changes mid-motion, when loading history
matters — which for a viscoelastic material it does — or when the flexure interacts with another
deformable part. The whole-hand simulation will keep producing smooth, confident plots after the
assumption has broken.

**Mitigation**
- Caveats displayed on every Mode 2 result, not buried in docs.
- Extrapolation beyond the fitted angular range refused without a visible warning.
- Phase 6 criterion 3: where a coupled result exists, compare it against the reduced-order
  prediction and quantify the difference.

**Residual:** real. This is a known approximation, used deliberately, with its limits stated.

---

## R10 — Tessellation error on mesh imports

**Severity: medium. Likelihood: medium.**

An STL has lost the exact surfaces. Bend radius and arc length computed from triangles carry an
error that depends on whatever export tolerance was used, and the user may not remember what it
was.

**Mitigation**
- `is_exact = False` on mesh-derived models, propagated into provenance.
- STEP recommended throughout; STL accepted for visualisation and rough checks.
- Exact geometric queries unavailable rather than approximated for mesh imports.

---

## R11 — Project and environment fragility

**Severity: low. Likelihood: medium.**

Dependency drift breaking a working install; OneDrive syncing solver scratch files mid-write;
long paths; projects that break when files move.

**Mitigation**
- `requirements.lock.txt` captures a known-good combination.
- Solver scratch directories outside the OneDrive tree.
- Imported CAD copied into the project directory, not referenced.
- Versioned project schema with migrations.

---

## R12 — Knowledge concentrated in one place

**Severity: medium. Likelihood: medium.**

Collaborators may not have AI tooling available, so the repository itself has to carry the
reasoning. A codebase whose design rationale lives only in someone's head stalls when that
person is unavailable.

**Mitigation**
- Detailed commit messages explaining motivation and alternatives rejected, not just the change.
- Documentation set covering feasibility, stack choices, solver evaluation, architecture and
  plan, kept current as part of each phase.
- A README written for someone starting from nothing.
- Decisions recorded with their rejected alternatives so they are not silently reopened.

---

## Review

Revisit at the end of each phase. New assumptions get registered here. Entries resolved by
evidence — for example R6 once Phase 6 concludes — are marked resolved with the evidence cited
rather than deleted, so the reasoning survives.
