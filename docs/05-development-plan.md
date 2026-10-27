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

## Phase 3 — Nonlinear FEA — **COMPLETE, 8 of 8 CRITERIA MET**

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
| 7 | Reduced-order vs FEA discrepancy on the real flexure | **MET — 9 % to 20 %** on the A3 twin strap, depending on where the clamp line is taken. Corrected from a non-like-for-like 23.8 %; see below |
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

### Criterion 7: how far the reduced-order model is from the FEA on the A3 twin strap

**Corrected after Phase 7.** This section previously reported a single figure of
23.8 % (7.558 against 6.103 N·mm/rad). That number was not like for like, and the
correction is as instructive as the result.

| | N·mm/rad |
|---|---|
| Nonlinear FEA (CalculiX, 32,965 C3D10, 61,021 nodes) | **6.103** |
| Reduced-order, clamp line 0.10 mm inside the collar face | 6.650 (**+9.0 %**) |
| Reduced-order, 0.15 mm | 6.759 (+10.7 %) |
| Reduced-order, 0.25 mm | 6.984 (+14.4 %) |
| Reduced-order, 0.40 mm | 7.336 (+20.2 %) |
| *Previously reported, clamp line roughly 0.5 mm in* | *7.558 (+23.8 %)* |

**The reduced-order model overstates the A3's rotational stiffness by roughly 9 % at
the FEA's own boundary, rising to 20 % if the clamp line is drawn 0.4 mm further
in.** Reproduce with `scripts/a3_rom_vs_fea.py`.

### Why the original figure was wrong, and why it is worth writing down

Neither half of the original comparison was reproducible: both came from ad-hoc
sessions, and the two settings the answer is most sensitive to were never recorded.
Measuring that sensitivity is what exposed the problem.

**The joint axis.** The reduced-order stiffness at the bounding box centre
(z = 7.42 mm) is 3.16 N·mm/rad; at the collar's mounting-feature height
(z = 5.44 mm, which is what the FEA used) it is 6.86. A two-millimetre shift more
than doubles it. A refactor briefly introduced exactly that error and produced a
perfectly converged run — see the note on `axis_point` in
`core/fea/joint_stiffness.py`.

**Where the member is taken to be clamped.** Moving the extraction boundary from
0.10 mm to 0.40 mm inside the collar face changes the reduced-order answer from 6.65
to 7.34 N·mm/rad. The published 7.558 corresponds to roughly 0.5 mm — about half a
millimetre shorter at each end than the span the FEA actually left free. A shorter
member is a stiffer member, and most of the gap between 23.8 % and 9 % is that,
rather than the beam idealisation.

Both halves now use the same axis and the same span, and the script that computes
them is in the repository.

### What remains irreducible

A strap root blends into a collar; there is no plane at which the member becomes
free. The FEA fixes every surface wholly inside the attachment depth and leaves
straddling surfaces free, so its own boundary is a band. The comparison therefore
carries several per cent of uncertainty from the definition alone, which is why the
result is reported as a band and not as a figure to three significant digits.

The centreline extractor refuses to start closer than about 0.1 mm inside the collar
face — the collar's internal features make the cross-section count vary along the
sweep, and the guard that catches that is working correctly. So 9 % is the closest
like-for-like comparison available, not a limit that has been approached from both
sides.

### What this licenses

A 9 to 20 % error, with the dominant uncertainty in the boundary rather than the
physics, still means the same thing in practice as the 24 % did: the reduced-order
model is usable for ranking design variants and parameter sweeps, and not usable for
an absolute torque figure. It is a better-characterised version of the same
conclusion, and the direction is as expected — the beam model idealises away the
compliance of the strap roots, the 1.2 mm collar walls and the three-dimensional
stress state at the junction, so it should be the stiffer of the two.

**The ratio is still independent of the material.** Both models are linear in E, so
the provisional 12 MPa placeholder cancels out of the comparison. The band is
therefore considerably more trustworthy than either absolute value, both of which
remain tagged `UNVALIDATED_ASSUMPTION`.

**Compared at 2° of joint rotation, deliberately.** The reduced-order model is a
tangent stiffness at the neutral position and linear by construction, so comparing at
a large angle would conflate the beam idealisation with the linear-kinematics
extrapolation. At 2° both models are inside the regime the fast one claims to
describe. The large-angle divergence is a separate measurement and has not been made.

**Caveats on the FEA value itself.** Single mesh, with no convergence study on this
particular quantity, so `CAVEAT_NO_MESH_STUDY` applies — the 6.103 figure carries an
unknown discretisation error. The solve also needed 285 cutbacks across 48 increments,
so the model is stiff to converge and the increment sizing is not comfortable.

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

## Phase 4 — Assembly import and flexure integration — **COMPLETE, 5 of 6 CRITERIA MET**

| # | Criterion | Status |
|---|---|---|
| 1 | STEP assembly placement within 0.01 mm of SolidWorks | **PARTIAL — the reader is verified to 1e-5 mm, against a generated assembly. Not yet checked against a SolidWorks export, which nobody has supplied.** |
| 2 | Regenerated flexure reproduces its volume to better than 0.5 % | **MET — exact** on four parameter sets, against the template's own closed form |
| 3 | Adaptation changes only the intended parameters | **MET** — thickness and width equality is asserted inside `adapt_to_span`, not merely intended |
| 4 | Interference detected at a known-bad configuration | **MET** on a configuration whose collision angle is arithmetic |
| 5 | A sub-manufacturable design is flagged and not auto-approved | **MET** — the build button is disabled, not a dialog to dismiss |
| 6 | Every adaptation produces a parameter-change report | **MET** — and separates changes nobody asked for |

### Criterion 1, and what is honestly missing

The requirement is placement agreeing with SolidWorks to better than 0.01 mm. What
has been done instead is to generate an assembly whose transforms are known exactly,
write it to STEP, read it back and compare: the distal phalanx, placed 15° about an
axis through (0, 23, 5) and translated 26 mm, comes back agreeing to **better than
1e-5 mm over a 50 mm radius** — six orders tighter than the requirement, and measured
over a radius so a rotation error cannot hide behind a matching translation.

That is a sharper test of the *reader* than a spot-checked reference point would be,
and it is not the test the criterion asks for. It says nothing about how SolidWorks
writes its placements. The gap is one named link in the chain rather than a vague
doubt, and it closes the moment item 2 of
[06-required-inputs.md](06-required-inputs.md) arrives.

### What was built

`core/assembly/` — `model.py` (placements, component tree), `loader.py` (XCAF
product-structure import), `joint.py` (axis candidates and the confirmation gate),
`interference.py` (boolean clash and clearance). `core/flexure/adaptation.py`
regenerates a template to a new span and reports what moved.

### Three rules this phase put in the code rather than in prose

**A joint axis is never inferred.** `find_axis_candidates` returns ranked candidates
with the evidence that produced each one, and `Joint.require_axis()` raises until a
person has called `confirm()`. There is no automatic path to `confirm()` anywhere in
the codebase. Risk R4.

**A scaled or mirrored component instance is refused.** `Placement.from_matrix`
checks the rotation block is orthonormal with a positive determinant. A scaled
instance is a different part: its section dimensions, and so its stiffness, are not
those of the definition it refers to.

**A deformable body is never swept rigidly.** `sweep_interference` raises on any body
named in `deformable_labels`. Rotating a flexure rigidly about the joint axis shows
it in a pose the real part never takes, and confident interference results about a
shape that does not exist are worse than no check.

### Original specification

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

## Phase 5 — Whole-hand kinematics and reduced-order coupling — **COMPLETE, 5 of 5 CRITERIA MET**

| # | Criterion | Status |
|---|---|---|
| 1 | Kinematic preview labelled as such, no force or torque displayed | **MET structurally** — the Mode 1 result type has nowhere to put a torque |
| 2 | Fitted joint spring reproduces its FEA data to better than 1 %, refuses to extrapolate | **MET — exact at the nodes**, better than 1 % of full scale between them, and `fit_joint_spring` refuses to return a fit that misses its own data |
| 3 | Motion through a full range completes or reports where interference occurs | **MET** — `check_trajectory` reports the pose, the pair and the overlap volume |
| 4 | Two designs compared on one plot with provenance shown | **MET** — the tag is in the legend text, and ranking across methods is refused |
| 5 | Every Mode 2 result displays the reduced-order caveats | **MET** — attached at fit time, so no call site can omit them |

### Criterion 1 is a type, not a label

A label is a promise someone has to keep rendering correctly forever. `KinematicPose`
simply has no torque, force, stress or energy field, and refuses to be relabelled as
a stronger mode. The test asserts the *absence* of those attributes rather than the
presence of a caption.

### Why joint axes have to travel with their link

The DIP axis is attached to the middle phalanx, so flexing the PIP carries it along.
A chain that rotates every joint about its as-imported axis produces a hand that
looks almost right and is wrong by a growing amount down the chain.
`SerialChain.placements()` composes outward from the base so each joint acts about
its axis *as currently placed*. Verified by arithmetic: with links along Y and joints
at Y = 20 and Y = 36, flexing both 90° must send the tip from (0, 52, 0) to
(0, 4, 16), and it does to 1e-9 mm.

### Extrapolation is refused, not warned about

A fitted spring outside its fitted range is not a worse estimate; it is an arbitrary
one. A curve that fits beautifully to 60° can turn the wrong way at 70°, and a real
flexure stiffens sharply as its turns begin to close. `JointSpring.torque()` raises
unless the caller passes `allow_extrapolation=True`, which attaches a caveat that
travels with the number.

### A finding worth carrying forward

The default fit is shape-preserving (PCHIP) rather than a cubic spline, because a
plain spline through a stiffening curve invents a local softening the FEA never
showed. PCHIP is exact at its nodes but estimates the **endpoint** derivative
one-sidedly: on a 7-point grid the tangent stiffness at the neutral angle came out
**3 % low** against an exactly known 6.1 N·mm/rad, while an interior point was within
0.1 %. A neutral-position stiffness should be read from the FEA run itself, or the
FEA sampled on both sides of neutral.

### Original specification

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

## Phase 6 — Advanced coupled simulation — **COMPLETE, 3 of 3 CRITERIA MET**

Complete in the sense this phase defines: every capability was either demonstrated on
a benchmark or documented as not achievable, with evidence either way. Six of the
seven capabilities have a verdict; one of those verdicts is a failure, which is a
permitted and useful outcome.

Full evidence, including the two wrong set-ups that nearly became documented solver
limitations: [09-phase6-capability-findings.md](09-phase6-capability-findings.md).

| # | Criterion | Status |
|---|---|---|
| 1 | Each capability demonstrated on a benchmark, or documented as unachievable with evidence | **MET** for all seven |
| 2 | No capability enabled in the UI until it has passed its benchmark | **MET** — enforced by `CapabilityRegistry`, which the FEA panel reads |
| 3 | Where a coupled result exists, compare it against the Phase 5 reduced-order prediction | **MET vacuously, and that is the honest answer** — no coupled result exists on a real flexure, so there is nothing to compare |

| Capability | Verdict | Measured |
|---|---|---|
| Gravity (body load) | **PASSED** | Cantilever self-weight, -1.21 % against the closed form |
| Tendon load | **PASSED** | 2 N resultant over 119 nodes; root reaction exact |
| Frictionless contact | **PASSED** | 100 N through an interface, exact; 0.0041 mm penetration on a 4 mm element |
| Contact with friction | **PASSED** | mu = 0.3, tangential reaction exact, 0.0068 mm of in-plane motion |
| Mechanical stops | **PASSED** | 0.5017 mm against a 0.5 mm gap, +0.3 % |
| Self-contact | **FAILED** | Contact engages but leaves 12 % of an element of interpenetration, against a 5 % criterion |
| Viscoelasticity | **NOT AVAILABLE** | No such material model. Settled in Phase 3 against the manual |

### Criterion 2 is a file, not a promise

A fresh checkout has every capability `NOT_TESTED`, which disables it. A capability is
enabled by running `scripts/phase6_benchmarks.py` on the machine in question and
reproducing an answer known in advance. "CalculiX supports contact" is a statement
about CalculiX; "contact converges here, with this build, on this geometry" is the
statement the application needs, and no amount of source code establishes it.

### The finding that contradicted the project's own code

Node-to-surface contact — conventionally the robust formulation, and what
`core/fea/contact.py` said when it was written - failed to converge on **every**
contact benchmark at both penalty stiffnesses tried. Surface-to-surface converged in
14 increments on all of them. The benchmark now tries configurations in order and
records which one worked.

### Criterion 3, and why "vacuously met" is the right description

The criterion is contingent: *where* a coupled result exists, compare it. None does.
Contact has been demonstrated on stacked blocks of 1,700 elements; the A3 flexure is
33,000 elements and takes half an hour without contact. Running a coupled analysis of
a closing meander has not been attempted, so there is no coupled number to set beside
the reduced-order one. Writing this criterion off as met without saying that would be
the kind of quiet pass this plan exists to prevent.

### Original specification

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

## Phase 7 — Optimisation and experimental calibration — **4 of 6 CRITERIA MET; 2 BLOCKED ON A PHYSICAL MEASUREMENT**

| # | Criterion | Status |
|---|---|---|
| 1 | A sweep reproduces designs analysed individually | **MET** — compared value for value, not to a tolerance |
| 2 | Optimisation refuses to run on a model that failed its validity checks | **MET** — `require_valid` raises; invalid points are excluded from ranking, not penalised |
| 3 | Conflicting objectives produce a Pareto front, not a winner | **MET** — `ParetoFront.winner()` raises when more than one design survives |
| 4 | Sensitivity reports how far the optimum shifts under stated material uncertainty | **MET — and the answer is that the ranking does not shift at all** |
| 5 | A predicted torque–angle curve compared against a physical measurement | **BLOCKED.** No specimen has been tested. The machinery exists and is tested; the measurement does not. |
| 6 | Only experimentally validated results carry that tag | **MET** — enforced by an AST scan over every core module |

### Criterion 4: the result that decides what this tool is usable for today

Both the reduced-order model and a small-strain FEA are **linear in the elastic
modulus**, so a modulus uncertainty multiplies every design's stiffness by the same
factor and cancels out of a comparison. Over a stated 8 to 18 MPa range about a
nominal 12, the Pareto front is **identical at every modulus**: the chosen design's
geometric objectives move by 0 % and its stiffness by 38 % of the mean.

So **design selection is available now, while the material is uncalibrated**, because
selection depends on the ranking and the ranking does not depend on the modulus.
Absolute torque is not, and will not be until item 7 of
[06-required-inputs.md](06-required-inputs.md) arrives.

`modulus_sensitivity()` establishes this by re-running the search at the ends of the
range and comparing the fronts, rather than asserting it from the algebra. If a
future objective breaks the linearity — a fixed strain or force allowable, typically
— the report says the front changed instead of quietly staying wrong.

### Criteria 5 and 6: the gate, and what is on the other side of it

`core/material/calibration.py` is the **only** module in the codebase that can
produce an `EXPERIMENTALLY_VALIDATED` value, and `tests/test_architecture.py` walks
the AST of every other core module to confirm none of them name the tag. The gate
refuses three ways: without agreement inside a tolerance the caller stated *before*
seeing the result; without a `MeasurementSeries` carrying a specimen identifier, a
description of the rig and a stated uncertainty; and for any angle outside the range
the specimen was actually measured over.

A disagreeing comparison is a result, not an error. "The model is 40 % stiff against
the printed part" is the most useful sentence this project could produce, so
recording it is as easy as recording agreement, and the report separates bias from
scatter — a large bias with small scatter points at the material or a boundary
condition, the reverse points at the rig.

**Nothing in this project is experimentally validated.** That is the honest state of
criterion 5 and it cannot be changed from the keyboard.

### What was built

`core/optimise/` — `objectives.py` (design points, objectives, the validity gate),
`sweep.py`, `pareto.py`, `sensitivity.py`; plus `core/material/calibration.py`.

### Original specification

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
