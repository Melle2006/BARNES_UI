# Nonlinear FEA Solver Comparison

**Question:** which open-source solver should carry the finite-strain hyperelastic analysis of a
TPU flexure, on Windows, driven from Python?

**Answer:** CalculiX as the primary production solver, with an independent second opinion used
for verification rather than for production runs.

The reasoning is below, together with an explicit list of what has *not* been verified yet. The
project requirement is that a capability is confirmed before it is relied upon — several claims
commonly made about these solvers do not survive checking.

---

## 1. What the solver actually has to do

Requirements, in descending order of importance:

1. **Finite-strain (large deformation) kinematics.** Non-negotiable. A finger flexure undergoes
   rotations far outside the small-displacement regime.
2. **Hyperelastic constitutive models** — at minimum Neo-Hookean and Mooney-Rivlin, preferably
   Ogden, with the ability to enter coefficients fitted from our own test data.
3. **Nearly incompressible material handling.** TPU has a Poisson's ratio close to 0.5. Without
   mixed/hybrid formulation or selective integration, standard displacement elements lock and
   report a part as drastically stiffer than it is. This is the quiet failure mode that produces
   confident wrong answers.
4. **Second-order tetrahedral elements.** Realistically the only mesh type that can be generated
   automatically on a curved serpentine; first-order tets are unusable for this material.
5. **Prescribed-rotation loading with reaction-moment extraction.** The whole torque–angle
   workflow depends on being able to impose an angle and read back the moment.
6. **Windows availability** without building from source.
7. **Scriptable from Python** — text input deck plus subprocess is sufficient and is actually
   preferable to an API, because the deck is an auditable artefact that can be archived with the
   results.
8. Contact between bodies (Phase 6).
9. Self-contact (Phase 6, optional).
10. Time-domain viscoelasticity (Phase 7, only if test data ever justifies it).

---

## 2. Candidates

### CalculiX (`ccx`) — **selected**

**Hyperelastic support — verified.** The `*HYPERELASTIC` keyword accepts `ARRUDA-BOYCE`,
`MOONEY-RIVLIN`, `NEO HOOKE`, `OGDEN`, `POLYNOMIAL`, `REDUCED POLYNOMIAL` and `YEOH`. The order
parameter `N` applies to `OGDEN`, `POLYNOMIAL` and `REDUCED POLYNOMIAL`; the default is
`POLYNOMIAL` with `N=1`. Constants may be temperature-dependent. This covers requirement 2
comfortably.

One caution carried over from the CalculiX user community and worth confirming during
implementation: the Ogden formulation CalculiX implements follows the Abaqus convention rather
than Ogden's original formulation. Coefficients taken from a paper that used the original form
cannot be pasted in without checking. The application will label which convention its material
entry expects.

**Strengths**
- Abaqus-compatible input syntax, which means the large body of Abaqus modelling knowledge, and
  the user's own familiarity if any, transfers directly.
- `*NLGEOM` large-deformation steps are standard and well exercised.
- `C3D10` second-order tets, and hybrid element variants intended for incompressible materials.
- Node-to-face and face-to-face contact with penalty and augmented-Lagrange enforcement.
- Writes `.frd` results and `.dat` files that are straightforward to parse; reaction forces are
  directly obtainable via node sets.
- Windows binaries available, including inside FreeCAD's distribution.
- Free, no licence management.

**Weaknesses, stated honestly**
- Diagnostics are poor. A failed nonlinear increment often produces a terse message that does not
  identify the cause. Debugging convergence is a skill, not a lookup.
- Convergence on large-strain, nearly incompressible, contact-heavy models is genuinely fragile.
  Expect to spend real time on increment sizing and contact stabilisation.
- Shared-memory parallel only; no distributed solve. Acceptable for single-flexure models,
  limiting for whole-hand ones — which is a further reason the staged approach is right.
- The documentation is a reference manual, not a guide.

**Unverified — must be checked in Phase 3 before use:**
- Time-domain viscoelasticity. CalculiX has a `*VISCO` procedure and `*CREEP` material behaviour,
  but whether it supports a Prony-series viscoelastic *hyperelastic* material in the way Abaqus's
  `*VISCOELASTIC, TIME=PRONY` does has **not** been confirmed. A targeted search did not return
  authoritative CalculiX documentation on this point. Until the CalculiX user manual is checked
  directly and a test case is run, the project assumes **no viscoelastic capability** and reports
  hyperelastic-only results with that limitation stated on the output.
- Self-contact robustness on thin hyperelastic members.
- Whether the specific Windows build obtained is compiled with the needed options and with
  multithreading enabled.

### Code_Aster — rejected as primary, strong on capability

Capability is the best of the candidates: a deep nonlinear mechanics library, many hyperelastic
and viscoelastic laws, mature contact, and formal verification documentation for a large
proportion of its features. If this were a Linux project, the decision would be closer.

Rejected because of Windows practicality. The supported route is Salome-Meca on Linux; Windows
usage means WSL, a container, or an unofficial build. That is a significant barrier for
collaborators setting the project up unaided, which the project explicitly aims to avoid. The
command language is also a substantial learning investment.

Kept in reserve: if CalculiX proves unable to handle the Phase 6 contact work, moving that
specific analysis to Code_Aster under WSL is a reasonable escalation, and the architecture keeps
solver integration behind an interface so that this does not require rewriting the application.

### FEniCSx — rejected as primary, adopted for verification

FEniCSx lets you write the weak form of a hyperelastic problem directly, which means total
control over the formulation and no doubt about what is being solved. For producing an
independent check of a CalculiX result on a simple geometry, that is exactly what is wanted.

Rejected as primary because contact is not provided — it would have to be implemented — and
because Windows support is conda- or WSL-based. Building a production workflow on it would mean
writing solver infrastructure instead of using it.

Planned role: Phase 3 verification. A closed-form or FEniCSx solution of a simple hyperelastic
case, compared against CalculiX on the same case, establishes that the CalculiX integration is
wired up correctly before it is pointed at the real flexure. This is cheap insurance against
unit errors and boundary-condition mistakes, which are more likely sources of error than the
solver itself.

### Elmer FEM — rejected

Good Windows installer, active project, solid multiphysics. Its nonlinear solid mechanics and
hyperelastic material library are thinner than CalculiX's, and the contact implementation is less
developed for this class of problem. No advantage here that offsets that.

### MFEM, deal.II, Kratos — rejected

Libraries for building solvers rather than solvers. Appropriate if the project's purpose were to
develop a new formulation. It is not.

---

## 3. Decision

| | CalculiX | Code_Aster | FEniCSx | Elmer |
|---|---|---|---|---|
| Finite strain | Yes | Yes | Yes | Yes |
| Hyperelastic library | Good (7 models) | Excellent | Write it yourself | Limited |
| Nearly incompressible | Hybrid elements | Yes | Full control | Limited |
| 2nd-order tets | Yes (C3D10) | Yes | Yes | Yes |
| Contact | Yes | Excellent | No | Basic |
| Viscoelastic | **Unverified** | Yes | Write it yourself | Limited |
| Windows, no WSL | **Yes** | No | No | Yes |
| Python driving | Text deck + subprocess | Text deck | Native | Text deck |
| Learning cost | Moderate | High | High | Moderate |

**CalculiX is selected** because it is the only candidate that clears every hard requirement for
Phases 3 to 5 while installing on Windows without a Linux layer. Its weaknesses are in
diagnostics and in robustness at the hardest end of the problem — both of which fall in Phase 6,
by which point there will be a validated simpler model to fall back on and to compare against.

---

## 4. How the solver is integrated

The solver sits behind an interface (`core.fea.SolverBackend`) with a single CalculiX
implementation initially. Every run produces a durable, inspectable record:

```
runs/<run-id>/
    input.inp          generated deck, archived exactly as submitted
    solver.log         full stdout and stderr
    results.frd        raw solver output
    results.json       parsed quantities with units and provenance tags
    manifest.json      geometry hash, material set, mesh settings, solver version, timestamp
```

Three rules that are not negotiable, because they are what separates this from a tool that
produces convincing nonsense:

1. **No fabricated output.** If the solver is missing, fails to start, or fails to converge, that
   is reported as a failure. The application never substitutes a reduced-order result and
   presents it as FEA.
2. **Convergence status travels with the result.** A result object carries whether every
   increment converged, how many cutbacks occurred, and the final residuals. The UI shows it.
   An animation is not evidence of convergence, and the UI does not treat it as such.
3. **The deck is archived.** Anyone can open `input.inp` and check what was actually solved, with
   no need to trust the generating code.

---

## Sources

- [CalculiX 2.7 user manual, `*HYPERELASTIC`](https://web.mit.edu/calculix_v2.7/CalculiX/ccx_2.7/doc/ccx/node212.html)
- [CalculiX discourse: OGDEN N=2 and N=3 material model](https://calculix.discourse.group/t/ogden-n-2-and-n-3-material-model/1563) — user discussion noting the formulation difference; treat as a lead to verify, not as documentation
- [Abaqus keyword reference, `*HYPERELASTIC`](https://abaqus-docs.mit.edu/2017/English/SIMACAEKEYRefMap/simakey-r-hyperelastic.htm) — useful because CalculiX follows the same naming conventions
- [Abaqus keyword reference, `*VISCOELASTIC`](https://docs.software.vt.edu/abaqusv2024/English/SIMACAEKEYRefMap/simakey-r-viscoelastic.htm) — the behaviour whose CalculiX equivalent remains unconfirmed
- [CadQuery OCP build system](https://github.com/CadQuery/ocp-build-system) — Windows wheel availability for the CAD kernel
