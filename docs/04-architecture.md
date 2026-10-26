# Architecture

---

## 1. The organising principle

**Engineering code never imports GUI code.**

`barnes_ui.core` is a pure Python library: CAD handling, mechanics, solvers, project storage.
It has no knowledge that a GUI exists. `barnes_ui.gui` depends on `core` and never the reverse.

This is enforced by an automated test (`tests/test_architecture.py`) that walks the import graph
and fails if anything under `core` imports PySide6, PyVista, or Matplotlib. The rule is stated in
many projects and eroded in most of them; here it is checked by CI.

Three concrete benefits:

- The physics is testable headless, so tests run in seconds without a display server.
- A calculation can be scripted or batched without starting the application.
- A GUI rewrite, or a command-line interface, does not touch a line of mechanics.

---

## 2. Folder structure

```
Barnes_UI/
├── README.md                     Start here — setup, run, test, orientation
├── CONTRIBUTING.md               Commit conventions, code standards, review checklist
├── pyproject.toml                Package metadata and dependencies
├── requirements.lock.txt         Exact working versions
│
├── docs/
│   ├── 01-feasibility-assessment.md    What is and is not achievable
│   ├── 02-software-stack.md            Library choices and why
│   ├── 03-solver-comparison.md         FEA solver evaluation
│   ├── 04-architecture.md              This file
│   ├── 05-development-plan.md          Phases with acceptance criteria
│   ├── 06-required-inputs.md           CAD files and material data needed from the user
│   └── 07-risk-register.md             What could make results wrong
│
├── src/barnes_ui/
│   ├── __main__.py               `python -m barnes_ui` entry point
│   ├── app.py                    Application bootstrap, logging, exception hook
│   │
│   ├── core/                     ── NO GUI IMPORTS BELOW THIS LINE ──
│   │   ├── units.py              Unit system, conversion, canonical internal units
│   │   ├── provenance.py         Result tagging and the rules on mixing categories
│   │   ├── logging_setup.py      File + console logging configuration
│   │   │
│   │   ├── cad/
│   │   │   ├── model.py          GeometryModel / SolidInfo / dataclasses
│   │   │   ├── registry.py       Format detection, dispatch to the right loader
│   │   │   ├── loaders/
│   │   │   │   ├── step.py       STEP via OCP, including header unit detection
│   │   │   │   ├── iges.py       IGES via OCP
│   │   │   │   ├── brep.py       Native OCCT BREP
│   │   │   │   ├── stl.py        STL via trimesh (no exact geometry)
│   │   │   │   └── dxf.py        2D profiles via ezdxf
│   │   │   ├── inspect.py        Bounding box, volume, inertia, topology, defects
│   │   │   └── tessellate.py     BREP → triangle mesh for display
│   │   │
│   │   ├── flexure/              [Phase 2] Centreline, width profile, reduced-order model
│   │   ├── material/             [Phase 2] Material models, fitting, validity ranges
│   │   ├── fea/                  [Phase 3] Mesh generation, deck writing, solver, parsing
│   │   ├── assembly/             [Phase 4] Component tree, joints, flexure adaptation
│   │   ├── kinematics/           [Phase 5] Forward kinematics, reduced-order joint springs
│   │   ├── optimise/             [Phase 7] Parameter sweeps, multi-objective search
│   │   │
│   │   └── project/
│   │       ├── schema.py         Versioned project file format
│   │       └── store.py          Save / load / migrate
│   │
│   ├── gui/
│   │   ├── main_window.py        Shell, menus, dock layout, tab structure
│   │   ├── tasks.py              QThread worker wrapper: progress, cancel, error routing
│   │   ├── viewer/
│   │   │   └── viewport.py       PyVista QtInteractor wrapper, picking, section planes
│   │   └── panels/
│   │       ├── project_panel.py  Project dashboard
│   │       ├── geometry_panel.py Import, solid tree, measurements
│   │       └── properties_panel.py  Inspected values with units
│   │
│   └── resources/                Icons, stylesheet, bundled reference data
│
└── tests/
    ├── test_architecture.py      Enforces the core/gui separation
    ├── test_units.py
    ├── test_provenance.py
    ├── test_cad_*.py
    └── data/                     Small generated fixtures, committed
```

Phase directories are created when their phase starts rather than sitting empty, so that the
tree always reflects what actually exists.

---

## 3. Core data model

A single structure carries an imported model through the whole application.

```python
GeometryModel
    source_path      : Path
    source_format    : CadFormat                 STEP | IGES | BREP | STL | DXF
    unit             : LengthUnit                detected or user-confirmed
    unit_confidence  : UnitConfidence            DECLARED | ASSUMED | USER_SET
    solids           : list[SolidInfo]
    is_exact         : bool                      False for mesh-derived imports
    warnings         : list[GeometryWarning]

SolidInfo
    index, name                                  name from the CAD file where present
    volume, surface_area, centre_of_mass
    bounding_box     : BoundingBox               axis-aligned, in the model's unit
    inertia_tensor
    counts           : TopologyCounts            faces, edges, vertices, shells
    is_valid         : bool                      BRepCheck_Analyzer result
    shape            : TopoDS_Shape | None       None for mesh imports
```

`unit_confidence` deserves note. A STEP file declares its unit, so that is `DECLARED` and
trustworthy. An STL has none, so the application makes a `ASSUMED` guess (millimetres) and
visibly flags it until the user confirms, at which point it becomes `USER_SET`. The three states
are distinct because silently assuming millimetres on a file authored in inches is a 25× error
that propagates into every force the tool ever reports.

---

## 4. Provenance — the rule that makes results trustworthy

Every numeric result carries a tag recording how it was obtained:

| Tag | Meaning | Trust |
|---|---|---|
| `GEOMETRIC_MEASUREMENT` | Read from the CAD model | High, bounded by import fidelity |
| `ANALYTICAL_ESTIMATE` | Closed-form within stated assumptions | Only inside those assumptions |
| `REDUCED_ORDER_PREDICTION` | Beam/rod model | Screening only |
| `FEA_RESULT` | Converged finite element solution | Good, if the material is calibrated |
| `EXPERIMENTALLY_VALIDATED` | Compared against physical measurement | Highest |

Implemented in `core/provenance.py` as a `TaggedValue` carrying the number, its unit, its tag,
and a list of caveats. Enforced rules:

- Values with different tags are never silently combined; combining them produces a result
  tagged at the weakest input's level, with the caveats concatenated.
- A plot refuses to draw two different tags as the same series style.
- Any value derived from assumed material parameters carries a permanent caveat that survives
  every downstream operation, all the way into the CSV export and the generated report.

This is deliberately intrusive. It is the mechanism that stops a provisional estimate from being
laundered into an apparent measurement by passing through three functions.

---

## 5. The fidelity ladder

How the levels in the feasibility assessment connect in practice. This is the project's answer
to "simulate the whole hand", and the staging is the point.

```
  L1  Geometry            Import, measure, extract centreline and width profile
       │                  (Phases 1–2)
       ▼
  L2  Reduced-order       Curved-beam model → torque-angle curve in milliseconds
       │                  Used for sweeps and ranking. Error unknown until L3 exists.
       │  ◄── error quantified against ──┐
       ▼                                 │
  L3  Nonlinear FEA       Meshed solid, finite strain, hyperelastic
       │                  Single joint. Minutes to hours. (Phase 3)
       │
       │  extract torque-angle curve
       ▼
  L4  Reduced-order       Fit the L3 curve as a nonlinear torsional spring
       │  joint model     Valid where joint behaviour is a function of angle alone
       ▼
  L5  Whole-hand          Rigid phalanges + L4 springs. Interactive speed. (Phase 5)
      multibody           Spot-checked against further L3 runs.
```

The key move is **L3 → L4**: expensive physics is run once per design, condensed into a curve,
and then reused cheaply. This is standard practice and it is sound, with a specific validity
condition — the joint's torque must depend on its angle and nothing else. It stops being true
when contact state changes during the motion, when loading history matters (which for a
viscoelastic material it does), or when the flexure interacts with another deformable body. The
UI states these caveats on every L5 result rather than burying them in documentation.

**Mode 1 (kinematic preview)** and **Mode 2 (structural simulation)** are separate commands with
separate UI treatment. A kinematic preview is a rigid-body animation for checking clearance and
motion envelope; it computes no forces and is never presented as a physical simulation.

---

## 6. Threading

Meshing and solving take minutes. The UI must stay responsive.

Long operations run in a `QThread` via `gui/tasks.py`, which provides a uniform contract:
progress reporting, cooperative cancellation, exceptions marshalled back to the UI thread and
shown as errors rather than silently swallowed, and a guarantee that solver subprocesses are
terminated if the user cancels or closes the window.

Core code never knows about threads. It takes an optional `progress_callback` and an optional
cancellation token, both plain Python. This keeps `core` independently usable from a script.

---

## 7. Project file format

A project is a directory, not a single file, because solver runs produce large binary artefacts
that do not belong inside a document.

```
MyProject.barnesproj/
    project.json           versioned manifest, human-readable
    geometry/              copies of imported CAD, so the project is self-contained
    materials/             material definitions and test data
    runs/<run-id>/         one directory per analysis, as in the solver doc
    reports/
```

`project.json` carries a `schema_version`. `store.py` holds migrations so that an old project
opens in a newer build rather than failing. Imported CAD is **copied in**, not referenced,
because the alternative is projects that break when someone reorganises their Downloads folder.

---

## 8. Error handling

- Loaders raise typed exceptions (`UnsupportedFormatError`, `GeometryLoadError`,
  `InvalidGeometryError`) that the GUI maps to actionable messages. A failed STEP import tells
  the user which export settings to change.
- Geometry problems that are survivable become `GeometryWarning` entries on the model and are
  surfaced in the UI, not raised. A model with a small invalid face is still worth looking at;
  it just must not be silently analysed.
- Everything is logged to a rotating file under the user's application data directory, with the
  path shown in Help → About, so a bug report can include it.
- An unhandled exception shows a dialog with the traceback and the log path rather than closing
  the window.
