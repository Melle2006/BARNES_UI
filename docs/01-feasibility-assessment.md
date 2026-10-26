# Feasibility Assessment

**Status:** baseline assessment, written before Phase 1 implementation.
**Scope:** what this project can realistically deliver, what it cannot, and where the
boundary between the two sits.

This document exists so that nobody — including the people who wrote it — later mistakes an
aspiration for a delivered capability. Where a claim has been verified on the development
machine, it says so. Where it has not, it says that too.

---

## 1. Summary judgement

The project is feasible, but only if it is built as **three clearly separated fidelity levels**
rather than as one "simulation" feature:

| Level | What it is | Trustworthy for | Not trustworthy for |
|---|---|---|---|
| **L1 — Geometric measurement** | Dimensions read off the imported solid | Dimensions, volume, clearance | Anything about forces |
| **L2 — Reduced-order mechanics** | Beam/rod model built from the extracted centreline and cross-sections | Fast screening, relative ranking of design variants | Absolute stiffness of a tightly curved serpentine |
| **L3 — Nonlinear FEA** | Finite-strain hyperelastic solid analysis in an external solver | Absolute stiffness and strain, *if* the material is calibrated | Anything, if the material parameters were guessed |

A fourth level — fully coupled nonlinear contact simulation of the whole hand — is judged
**impractical as a routine workflow** on a single desktop machine and is deliberately not the
target. The staged approach in [05-development-plan.md](05-development-plan.md) substitutes a
reduced-order joint model extracted from L3 instead.

The single largest risk is not computational. It is that **TPU 95A is a hardness grade, not a
material model**, and that every force the application reports is only as good as the material
characterisation behind it. This is addressed in section 6 and in
[07-risk-register.md](07-risk-register.md).

---

## 2. What can be automated reliably

These are mechanisable with established libraries and need no engineering judgement at run time.

**CAD import and inspection**
- Reading STEP (AP203/AP214/AP242), IGES, and BREP through the OpenCASCADE kernel.
- Reading STL (binary and ASCII) and DXF.
- Triangulating solids for display, at a controllable deviation tolerance.
- Bounding box, volume, surface area, centre of mass, inertia tensor.
- Topology counts: solids, shells, faces, edges, vertices.
- Splitting a compound into disconnected solids.
- Detecting invalid topology (OpenCASCADE's `BRepCheck_Analyzer`).
- **Unit detection from the STEP header.** STEP files declare their length unit explicitly, so
  this is a read, not a guess. STL and raw meshes carry no units at all and always require
  confirmation.

**Numerics and bookkeeping**
- Mesh generation from a BREP solid (Gmsh).
- Writing a solver input deck, running the solver as a subprocess, parsing its results.
- Extracting reaction forces and moments from a solved model.
- Assembling force–displacement and torque–angle curves from a sequence of solved increments.
- Mesh-refinement studies, parameter sweeps, CSV and figure export.
- Interference detection between solids (boolean common, or mesh-based proximity).
- Rigid-body kinematic placement of components given joint axes and angles.

**Quality control**
- Comparing a reduced-order result against an FEA result and reporting the gap.
- Comparing an FEA result against a closed-form benchmark with known validity.
- Tagging every number with how it was obtained, and refusing to mix categories in a plot.

---

## 3. What requires user input and cannot be inferred

These need a human decision. The application must ask rather than assume, because a wrong
assumption here produces a result that looks completely normal.

**Units on unitless formats.** STL, and meshes in general, have no unit. A 12-unit part is
12 mm or 12 cm depending on what the exporter meant. Must be confirmed.

**Which solid is which.** A STEP assembly is a tree of shapes. Nothing in the file says "this is
the proximal phalanx and that is the flexure". Component names survive from SolidWorks often
enough to be a useful hint, but they are a hint, not data.

**Joint axes and motion limits.** This is the important one. SolidWorks mates define the
kinematics, and **STEP does not carry mates**. A STEP assembly exports the *placed geometry*, not
the relationships that placed it. The intended axis of a PIP joint therefore cannot be recovered
from the export. A cylindrical face can be detected and offered as a candidate axis, but which
cylinder is the joint, which way is positive rotation, and what the flexion limits are must be
set by the user. Inferring the kinematic structure from proximity alone is explicitly rejected:
two parts being near each other does not make them a hinge.

**The flexure centreline.** For a straightforward constant-width meander this can be extracted
automatically with reasonable confidence. For geometry with varying width, fillets blending into
the path, or junctions where the path branches, "the centreline" is not uniquely defined by the
solid. The application must offer an interactive route: pick the start face, the end face, and
inspect the extracted path, with the option to correct it.

**Boundary conditions.** Which faces are clamped, which are driven, and whether the load is
force- or displacement-controlled. These are modelling decisions.

**Material parameters.** See section 6.

**Which deformation modes matter.** Whether out-of-plane buckling should be permitted or
suppressed changes the answer substantially for a thin flexure, and the correct choice depends on
how the part is actually restrained in the hand.

---

## 4. What is difficult, unreliable, or out of scope

Stated plainly so that no time is spent attempting them under the impression that they are
routine.

**Native SolidWorks files (`.SLDPRT`, `.SLDASM`).** There is no open-source reader that imports
native SolidWorks files with their parametric feature history. Some tools can extract the
embedded tessellation or a preview, which is not the same thing and is not adequate for analysis.
FreeCAD cannot do this reliably either, and any claim otherwise should be treated as false.
**The required workflow is to export from SolidWorks to STEP** (AP214 or AP242), which the user
already has a licence for. For assemblies, export as a single STEP assembly so that component
placement is preserved. This is a one-time manual step per design revision and is accepted as a
permanent boundary of the project, not a temporary limitation.

**Recovering a feature tree from STEP.** STEP AP214 carries boundary-representation geometry.
It does not carry "extrude 1.2 mm", "pattern 5 instances", or the sketch that drove them.
Parametric *re*-generation in this application therefore has to come from a template defined
inside the application — not from reverse-engineering the import. This is why
[Module E](05-development-plan.md#phase-4) is built around a parametric flexure template plus a
reconstructed centreline, rather than around morphing the imported solid.

**Stretching an imported solid to fit a new joint spacing.** Technically easy, mechanically
wrong. Scaling a solid changes cross-sections, which changes the second moment of area
non-linearly, which changes the stiffness by an amount nobody has computed. The application will
regenerate from parameters instead, and will report which parameters changed.

**Self-contact of a tightly folded serpentine.** Contact between separate bodies is a solved
problem in the candidate solvers. Self-contact of a thin, highly deformed, nearly incompressible
member is where open-source nonlinear solvers become fragile and slow. Treated as a Phase 6
investigation with an explicit possibility of a negative outcome.

**Viscoelasticity of TPU.** The physics is real — TPU creeps, relaxes, shows hysteresis, and
takes a permanent set. Capturing it requires both (a) solver support, which is not yet verified
for the primary candidate, and (b) rate-dependent test data, which does not exist for this
material yet. Until both exist, the application will report purely hyperelastic results and
**state on the result itself that hysteresis and rate effects are not modelled**.

**Fully coupled whole-hand nonlinear FEA.** Multiple hyperelastic flexures, multiple contact
pairs, large rotations, across a full grasp cycle. The cost and the convergence fragility make
this unsuitable as the routine workflow the user runs while iterating on a design. The staged
substitute is described in section 5 of [04-architecture.md](04-architecture.md).

---

## 5. The three kinds of "stiffness" this tool reports

The user's request specifically asks for this distinction to be made explicit, because the three
are routinely conflated and the difference is large for a serpentine flexure.

**Geometry-based (reduced-order) estimate.** The flexure is reduced to a curved beam following
its centreline, with a cross-section that varies along the path. Bending stiffness is integrated
along the arc length using the local second moment of area. For a rectangular section of
out-of-plane thickness `t(s)` and in-plane width `w(s)`, bending about the axis for which `w` is
the relevant dimension uses `I(s) = t(s)·w(s)³ / 12`.

This is fast — milliseconds — and it correctly captures the first-order effect of changing width,
thickness, or path length. It is useful for ranking variants.

Its assumptions fail in specific, predictable ways for this geometry. Beam theory assumes the
cross-section is small relative to the radius of curvature; in a tight meander turn it is not, and
the stress distribution through the section is no longer linear. It assumes small strain; TPU in a
finger joint is not in that regime. It ignores shear deformation in short, stubby segments, and it
ignores the compliance of the junction regions where straight runs meet turns. For a tightly
curved serpentine, the discrepancy against FEA is expected to be substantial — not a few percent.
**The reduced-order model is therefore a screening tool whose error must be quantified against
FEA, not a predictor to be trusted on its own.**

**Nonlinear finite element analysis.** The actual solid is meshed and solved with finite-strain
kinematics and a hyperelastic constitutive law. This captures large rotation, the real
cross-sectional stress distribution, stress concentration at internal corners, and the stiffening
or softening that comes from the material law. It is the reference the reduced-order model is
measured against.

What it does *not* automatically give you is correctness. A converged nonlinear solution of the
wrong material model is a precise answer to the wrong question. Convergence is a numerical
property; validity is a physical one.

**Coupled whole-hand simulation.** The flexures, the rigid phalanges, contact, and the actuation
all solved together so that the motion and the forces are consistent with each other. This is the
only level at which "what does the finger actually do" is answered, rather than "what does this
flexure do when I impose a motion on it".

The practical substitute, and the one this project targets: run L3 on a single joint, extract the
torque–angle curve, fit it as a nonlinear torsional spring, and use that spring in a fast
multibody model of the whole hand. This is legitimate and widely used, and it is accurate **to the
extent that the joint's behaviour really is a function of angle alone** — which stops being true
once contact state changes during the motion, once loading history matters, or once the flexure
interacts with another deformable part. Those caveats are displayed alongside the result.

---

## 6. The material problem

This deserves its own section because it dominates the accuracy of everything downstream.

"TPU 95A" names a Shore A hardness. It does not determine a stress–strain curve. Two filaments
both sold as 95A can differ considerably in modulus. On top of that, a 3D-printed part is not the
bulk material: layer adhesion, print orientation, extrusion temperature, and whether the part is
solid or infilled all change the effective response, and the part is mechanically anisotropic
along the build direction.

Consequences that the application must respect:

- **Hyperelastic coefficients must not be synthesised from the hardness number.** There are
  published correlations from Shore hardness to an elastic modulus; they carry large scatter and
  they give a *small-strain* modulus, which is not what a Mooney-Rivlin or Ogden fit needs.
  Using one to populate hyperelastic constants would produce numbers that look authoritative and
  are not.
- The application accepts material parameters from a datasheet or from fitted test data, and
  otherwise runs in a **clearly labelled provisional mode** whose outputs are marked as
  unvalidated throughout — in the UI, in the plots, in the CSV exports, and in the report.
- Which hyperelastic model to use is a function of the available data and the strain range, not of
  implementation convenience. With only a uniaxial tensile curve to a modest strain, a
  one-parameter Neo-Hookean or a two-parameter Mooney-Rivlin fit is defensible. An Ogden fit with
  three terms has enough freedom to fit almost any single curve beautifully and then extrapolate
  badly outside the tested range. More parameters is not more accurate.
- A fit is only valid over the strain range it was fitted on. The application should record the
  calibration range and warn when a simulation drives the material outside it.

**The minimum useful material test** is a uniaxial tensile test on a specimen printed with the
same material, printer, orientation, and settings as the real flexure, taken to at least the
maximum strain the flexure will see. A cyclic test at two or three strain rates is what would be
needed to say anything quantitative about hysteresis.

---

## 7. Verified environment facts

Checked on the development machine on 2026-10-26, rather than assumed:

| Check | Result |
|---|---|
| Python | 3.12.3, 64-bit Windows |
| OpenCASCADE Python bindings (`cadquery-ocp`) | `cadquery_ocp-8.0.1.1.0-cp312-cp312-win_amd64.whl` resolves from PyPI — a native Windows wheel for this exact Python exists, no conda required |
| PySide6 | 6.12.0 resolves |
| VTK / PyVista / pyvistaqt | 9.7.1 / 0.49.1 / 0.13.1 resolve |
| trimesh, ezdxf | 5.2.0, 1.4.5 resolve |
| Git | 2.48.1 |

This matters because the Windows installability of the OpenCASCADE bindings is historically the
single most common reason this class of project stalls at setup. It is confirmed working here via
plain `pip`, which removes the main environment risk.

**Not yet verified, must be confirmed in Phase 3 before being relied on:**
- CalculiX's time-domain viscoelastic capability and its exact keyword syntax.
- CalculiX's behaviour for self-contact on thin hyperelastic members.
- Whether the Windows CalculiX distribution in use is built with the required solver options.

---

## 8. Recommended minimum viable product

The smallest thing that delivers real engineering value, in priority order:

1. **Import the A8 flexure STEP file and measure it properly.** Replace screenshot-derived
   estimates with actual CAD dimensions: arc length, width profile, extrusion depth, minimum
   feature size, bend radii. This alone resolves a standing problem — several dimensions currently
   in use were estimated from screenshots and have never been checked against the model.
2. **Extract the centreline and width profile, and compute a reduced-order torque–angle curve**
   for a prescribed joint rotation, with every assumption listed next to the number.
3. **Run the same case in nonlinear FEA and show both curves on one plot with the gap quantified.**

Step 3 is where the tool starts to be trustworthy, because it is the first point at which the fast
model is being checked rather than believed. Steps 1 and 2 are Phases 1 and 2; step 3 is Phase 3.

Everything after that — assembly integration, hand animation, optimisation — multiplies the value
but depends entirely on these three being right.
