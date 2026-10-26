# Barnes UI

A desktop application for designing TPU compliant flexures, measuring their stiffness, fitting
them to prosthetic-hand finger joints, and simulating the resulting motion and restoring torque.

**Current state: Phase 2 — flexure geometry and reduced-order mechanics.** The application
imports CAD, measures it, reconstructs flexure centrelines and section profiles, and computes a
reduced-order torque–angle curve about a joint axis. It does **not** yet run finite element
analysis, so no result here is a high-fidelity prediction, and the error of the fast model against
FEA has not yet been measured. That is Phase 3. See
[docs/05-development-plan.md](docs/05-development-plan.md).

![Phase 2 application window](docs/phase2-screenshot.png)

---

## What this project is for

A prosthetic hand under development uses TPU flexures as compliant joint elements: they bend as
the finger moves, store energy, and push the joint back toward its neutral position. The design
question is how the flexure's geometry — number of meander turns, width, thickness, span —
determines its stiffness, restoring torque, range of motion and peak strain.

Answering that by hand means exporting CAD, meshing it, writing a solver deck, running it,
parsing results, and repeating for every variant. This application automates the repetitive parts
while keeping every engineering assumption visible and overridable.

## The principle that shapes the whole codebase

**A plausible-looking wrong answer is worse than no answer.**

Design decisions get made from these numbers, and parts get printed from those decisions. A
finite element run that converges and renders a smooth deformed shape is extremely persuasive and
is worth nothing if the material coefficients were guessed. The number looks identical either
way.

So the code is built around a few non-negotiable rules:

- **Every value carries its provenance** — whether it was measured from CAD, estimated
  analytically, predicted by a reduced-order model, computed by FEA, or validated against a
  physical measurement. The tag travels with the value through every calculation into the plots
  and the CSV exports. A guessed material parameter cannot be laundered into an apparent
  measurement by passing through three functions.
- **No fabricated output.** If a solver is missing or fails to converge, that is reported as a
  failure. The application never substitutes a simpler model and presents the result as if it
  came from the one you asked for.
- **No invented material parameters.** "TPU 95A" is a hardness grade, not a constitutive model.
  Hyperelastic coefficients are never synthesised from it. Without calibrated data the
  application runs in a clearly marked provisional mode.
- **Convergence is not validity.** A converged solution of the wrong model is a precise answer to
  the wrong question, and the UI does not conflate the two.

If you only read one document, read
[docs/01-feasibility-assessment.md](docs/01-feasibility-assessment.md) — it states plainly what
this tool can and cannot do.

---

## Getting started

### Requirements

- Windows 10/11, macOS, or Linux (developed and verified on Windows 11)
- Python 3.10–3.12 (3.12 recommended; **not 3.13** — the CAD kernel has no wheel for it yet)
- About 1.5 GB of disk space, most of it the OpenCASCADE kernel
- A working OpenGL driver for the 3D viewport

### Install

```bash
git clone https://github.com/Melle2006/BARNES_UI.git
cd BARNES_UI
python -m venv .venv
```

Activate the environment — on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

Then install the package and its development tools:

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

The download is large (roughly 500 MB) because `cadquery-ocp` bundles the entire OpenCASCADE
runtime. This is expected and happens once.

To reproduce the exact environment this was verified against, use
`pip install -r requirements.lock.txt` instead.

### Run

```bash
python -m barnes_ui
```

Or open a file directly, which saves four clicks when iterating on one part:

```bash
python -m barnes_ui path/to/flexure.step
```

### Test

```bash
pytest
```

234 tests, running in about four seconds with no display required. The engineering core is
deliberately free of GUI dependencies so the test suite stays fast and headless — a rule enforced
by `tests/test_architecture.py` rather than left to discipline.

```bash
pytest -v                      # see each test
pytest --cov=barnes_ui         # with coverage
pytest -m "not gui"            # skip anything needing a display
```

---

## What Phase 1 does

| Capability | Notes |
|---|---|
| Import STEP, IGES, BREP | Exact B-rep geometry via OpenCASCADE |
| Import STL | Visualisation only — blocked for analysis, and the UI says why |
| Import DXF | 2D curves only |
| 3D viewport | Rotate, zoom, pan, standard views, section plane |
| Body tree | Per-body visibility and selection |
| Measured properties | Volume, surface area, bounding box, centre of mass, inertia, topology counts |
| Unit detection | Read from the STEP/IGES header; explicit confirmation for formats that declare none |
| Validity checking | OpenCASCADE topology check, disconnected bodies, zero-volume bodies, high aspect ratio |
| Analysis-readiness report | States exactly why a model is not ready, if it is not |
| Point-to-point measurement | On the display tessellation; exact vertex snapping not yet implemented |
| Projects | Save, reopen, imported CAD copied in so the project is self-contained |

## What Phase 2 adds

| Capability | Notes |
|---|---|
| Cross-section extraction | Area, centroid, second moments, from exact surfaces |
| Centreline reconstruction | Two-pass: locate along an axis, then re-cut normal to the tangent |
| Multi-member separation | Twin straps recovered as two independent members |
| Section profiles | Area and I against arc length |
| Material models | Neo-Hookean, Mooney-Rivlin, Ogden (N=1,2), linear elastic |
| Material fitting | Least-squares fit to uniaxial test data, with recorded validity range |
| Reduced-order stiffness | Clamped-clamped curved beam by Castigliano, bending + axial + shear |
| Torque–angle curves | Restoring torque and peak strain against joint angle |
| Provenance everywhere | Badge in the panel, banner stamped onto every exported figure |

**Verified in Phase 2** — the numbers, not the intent:

- Straight fixed-fixed member under pure imposed rotation: **9 ppm** against the exact
  slope-deflection result 4EI/L
- Section I extracted from CAD: **0.166667 mm⁴** against b·h³/12 = 0.1666667, six figures
- Depth doubled → stiffness ×**8.000** exactly; two parallel members → ×**2.000** exactly
- Castigliano against an independently written frame-FE solver, like-for-like: **0.057 %**

### What Phase 2 deliberately does not do

Finite element analysis. Meshing. Nonlinear material response. Large-deflection kinematics.
Contact. Flexure fitting onto an assembly. Hand animation. Optimisation.

None of it is stubbed out or faked. Where a later phase is referenced in the UI, it says which
phase and what is missing.

**The most important limitation of Phase 2**: the reduced-order model is linear, and on the A3
twin-strap part it predicts 42 % peak bending strain at 90° of flexion. That is far outside
small-strain validity, so the absolute torque is not trustworthy — only the relative comparison
between design variants is. Measuring the error against nonlinear FEA is the whole point of
Phase 3.

---

## A note on SolidWorks files

Native `.SLDPRT` and `.SLDASM` files **cannot be read** without SolidWorks. No open-source
library imports them with their parametric history; tools that appear to are reading the embedded
preview mesh, which is not adequate for analysis.

Export to STEP instead:

1. Open the part or assembly in SolidWorks
2. **File → Save As**
3. Choose **STEP AP214 (\*.step)**
4. For assemblies, tick **"Save all components as a single file"** so component placement is
   preserved — exporting components separately loses the assembly transforms

Nothing needed for analysis is lost in a STEP export. The application recognises native
SolidWorks extensions and shows these instructions rather than a bare "unsupported format".

One thing STEP does *not* carry is SolidWorks mates. Joint axes and motion limits cannot be
recovered from the export and must be defined in the application; this is why Phase 4 asks for
them explicitly instead of guessing from geometry.

---

## Project layout

```
docs/           Feasibility, stack choices, solver evaluation, architecture, plan, risks
src/barnes_ui/
    core/       Engineering code — CAD, mechanics, solvers, storage. NO GUI IMPORTS.
    gui/        Qt interface. Depends on core; never the reverse.
tests/          Headless test suite
```

The `core` / `gui` separation is the one architectural rule to know before editing anything. It
keeps the physics testable without a display and usable from a plain script, and a test fails if
it is broken.

Full details, including the data model and the fidelity ladder:
[docs/04-architecture.md](docs/04-architecture.md).

---

## Documentation

| Document | What it covers |
|---|---|
| [01-feasibility-assessment.md](docs/01-feasibility-assessment.md) | What is achievable, what needs user input, what is out of scope, and why |
| [02-software-stack.md](docs/02-software-stack.md) | Every library choice with its reasoning and rejected alternatives |
| [03-solver-comparison.md](docs/03-solver-comparison.md) | CalculiX vs Code_Aster vs FEniCSx vs Elmer for finite-strain TPU analysis |
| [04-architecture.md](docs/04-architecture.md) | Module layout, data model, provenance system, threading, project format |
| [05-development-plan.md](docs/05-development-plan.md) | Seven phases with measurable acceptance criteria |
| [06-required-inputs.md](docs/06-required-inputs.md) | CAD files and material data needed, and which phase each one blocks |
| [07-risk-register.md](docs/07-risk-register.md) | What could make the results wrong, and what is done about each |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Commit conventions, code standards, review checklist |

---

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 1 | CAD import and inspection | **Complete** |
| 2 | Flexure geometry, material models, reduced-order mechanics | **Complete** |
| 3 | Nonlinear FEA via CalculiX, with analytical verification | Not started |
| 4 | Hand assembly import, joint definition, flexure adaptation | Not started |
| 5 | Whole-hand kinematics and reduced-order coupling | Not started |
| 6 | Contact, self-contact, friction, viscoelasticity | Not started |
| 7 | Optimisation and experimental calibration | Not started |

Each phase has acceptance criteria that are testable statements rather than descriptions of
intent. A phase is done when someone else can run the stated check and watch it pass.

---

## Known limitations

These are honest limitations of the current build, not bugs:

- **Point measurement uses the display mesh**, so it carries the tessellation's chord tolerance.
  Fine for overall dimensions; exact vertex and edge snapping is Phase 2.
- **STL files cannot be analysed.** Tessellated geometry has lost the exact surfaces that
  curvature and bend radius depend on. The import works; analysis is blocked with an explanation.
- **PySide6 is capped below 6.9.** Version 6.12.0 installs and then fails to import on Windows 11
  with a current MSVC runtime. The reason is recorded in `pyproject.toml`; raise the cap only
  after testing the import.
- **Python 3.13 is not supported**, because `cadquery-ocp` has no wheel for it.
- **CalculiX's viscoelastic capability is unverified.** Until it is confirmed against the manual
  and a test case, the project assumes no viscoelastic support. See
  [docs/03-solver-comparison.md](docs/03-solver-comparison.md).

## Licence

MIT. See `pyproject.toml`.
