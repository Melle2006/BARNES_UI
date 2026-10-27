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

**A fourth instance, from Phase 6.** The self-contact benchmark drove a hairpin's free
end with a *prescribed displacement* larger than the gap between its legs. Contact
cannot resist a prescribed displacement: the node goes where it is told, and it took
one leg straight through the other. The run converged, raised no error, and reported
a closest approach of exactly minus the overshoot. The only visible symptom was 129
convergence cutbacks.

What makes it worth recording alongside the Phase 3 cases is that the obvious reading
— "CalculiX self-contact does not work" — would have been wrong, and would have gone
into the documentation as a solver limitation. The fault was in the question, not the
answer. See R13.

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

**MEASURED, Phase 7.** "Largely common to both" is now a number rather than a hope.
Both the reduced-order model and a small-strain FEA are linear in the elastic modulus,
so a modulus uncertainty multiplies every design's stiffness by the same factor. Over
a stated 8 to 18 MPa range the Pareto front is **identical at every modulus**: the
geometric objectives move 0 % and the stiffness moves 38 % of the mean, and the
ranking does not change at all.

So design *selection* is available today, while the material is uncalibrated. Design
*sizing* is not. `core/optimise/sensitivity.py` re-runs the search across the range
and compares the fronts rather than asserting the invariance, so an objective that
breaks the linearity — a fixed strain or force allowable — is reported instead of
quietly invalidating the conclusion.

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

**Residual:** none for the A3 arch — the error is now measured. See the update below.

**MEASURED, Phase 3.** On the A3 twin-strap flexure the reduced-order model overstates
rotational stiffness by **23.8 %** (7.558 against 6.103 N·mm/rad from CalculiX), compared
at 2° where the linear model is inside its own regime. The ratio is independent of the
material, since both models are linear in E, so the provisional modulus cancels out and
the figure is more trustworthy than either absolute value.

24 % licenses the reduced-order model for ranking design variants and parameter sweeps,
and rules it out for absolute torque. That was the standing assumption; it is now a
number. For the A8 meander the equivalent figure is still unmeasured and the planar model
is refused outright there (see R3 above).

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

**Hardened, Phase 4 and 5.** The mitigation is now in the type system rather than in
the UI. `Joint.require_axis()` raises until `confirm()` has been called, there is no
automatic path to `confirm()` anywhere in the codebase, and `SerialChain` calls
`require_axis()` on every joint when it is constructed — so an unconfirmed guess
cannot reach an animation. `find_axis_candidates` returns ranked *candidates* with
the supporting evidence (face count, total cylindrical area, axial extent) rather
than a single answer, and the ranking is labelled a heuristic wherever it appears.

The GUI's simulation tab drives one joint rather than a chain for the same reason:
the assembly importer is not exposed yet, so a hand would need guessed axes.

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
what detects this, and it cannot run against the A8 until the file arrives.

**Implemented, Phase 4.** `adapt_to_span` regenerates and never scales. Thickness and
width preservation is **asserted inside the function** rather than intended, so a
future strategy that forgets is caught there rather than in a plausible-looking
stiffness number. Criterion 2's volume check runs on every build from the GUI, not
only in the test suite. Four parameter sets reproduce the template's exact closed-form
volume.

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

**PARTLY MEASURED, Phase 6.** Contact converges on small benchmarks, with one
important qualification: only in the **surface-to-surface** formulation. Node-to-
surface — the formulation conventionally described as the robust one, and the one this
project's own code assumed — failed to converge on every contact benchmark at both
penalty stiffnesses tried, chattering until the increment fell below its minimum. The
benchmark script tries configurations in order and records which worked, so the
evidence names the setting. See [03-solver-comparison.md §5](03-solver-comparison.md).

Nothing has been attempted at the 33,000-element scale of the A3 flexure. The
benchmarks are 1,700 to 8,000 elements and finish in minutes; that is not evidence
about a real part.

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

**Hardened, Phase 5.** Extrapolation beyond the fitted angular range is now *refused*
rather than warned about: `JointSpring.torque()` raises unless the caller explicitly
opts in, and opting in attaches a caveat to the returned value. A fitted curve outside
its data is not a worse estimate but an arbitrary one, and a flexure genuinely
stiffens sharply as its turns begin to close — behaviour no fit over gentler angles
can know about. Every Mode 2 value also carries the four reduced-order caveats by
construction, attached at fit time rather than by whichever call site remembers.

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

## R13 — Concluding a capability is missing when the question was posed wrong

**Severity: medium. Likelihood: high, and it already happened.**

Registered after Phase 6. An investigative phase with a permitted negative outcome
has a failure mode of its own: a benchmark that does not pass is recorded as "the
solver cannot do this", and the record is believed afterwards by people who will not
re-run it. If the benchmark was set up wrong, a false limitation is now documentation.

The self-contact benchmark produced exactly this. Three set-ups, two of them wrong:

1. Every surface declared as both slave and master — the textbook self-contact
   recipe, which here meant every node began in contact with the face it belongs to.
   Diverged in the first increment.
2. A prescribed displacement driving the free end past the gap. Contact cannot resist
   a prescribed displacement. It converged, and the legs passed through each other.
3. A *force* closing the hairpin, which contact can balance.

Each failure looked like a solver limitation and none of them was one.

**Mitigation**
- A benchmark records the configurations it tried and which one worked, not only the
  verdict. A single-configuration "it does not converge" is not evidence.
- A capability record carries its run archive, so the deck can be read by someone who
  doubts the conclusion.
- `FAILED` and `NOT_AVAILABLE` are different statuses. `NOT_AVAILABLE` is reserved for
  what was checked against the manual — currently only viscoelasticity — and no
  benchmark result can set it.
- The benchmark scripts' docstrings record the wrong set-ups as well as the right one,
  so the next person does not repeat them and does not trust a verdict that came from
  one of them.

**Residual:** real, and not fully closable. A benchmark that passes for the wrong
reason is harder still to catch than one that fails for the wrong reason, which is
why every benchmark here compares against an answer known in advance rather than
against a previous run.

---

## Review

Revisit at the end of each phase. New assumptions get registered here. Entries resolved by
evidence — for example R6 once Phase 6 concludes — are marked resolved with the evidence cited
rather than deleted, so the reasoning survives.
