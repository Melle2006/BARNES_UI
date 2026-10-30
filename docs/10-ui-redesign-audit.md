# Workspace redesign — repository audit and the point-picking defect

Phase 0 of the workspace-redesign work: what is actually in the repository, what the
point-picking defect actually is, and what the remaining stages have to do. Written
before any behaviour was changed, and amended only to record what P1 changed.

**Status of this document's claims.** Everything in §1–§4 was read out of the source
in this working tree or out of the installed packages in `.venv`, with file and line
references given so each statement can be checked. §5 describes code written in this
pass, and §7 records its test run. §8 covers P2, the workspace redesign, whose run is
in §8.5: **808 passed, 0 failed, 0 skipped.** What is still unverified is listed at
the end of §7 and again in §8.6 — chiefly that nobody has yet used the real
application on a desktop.

---

## 1. Baseline

| Item | Value |
|---|---|
| Working tree | `C:\Users\msaip\OneDrive\Desktop\Barnes\Barnes_UI` |
| Git | repository present, branch `main`, working tree **clean** before this pass |
| HEAD at audit time | `c602162` "Record the A3 mesh-convergence study, and reproduce 6.103 from a committed script" |
| Remote | `origin` → `github.com/Melle2006/BARNES_UI` |
| Tracked Python | 107 modules under `src/`, `tests/`, `scripts/` |
| Test files | 20 (`tests/test_*.py`), one of them GUI (`test_gui_panels.py`, offscreen Qt) |
| README claim | 598 tests, "all seven phases built" |
| Suite after P1 | **704 passed, 0 failed, 0 skipped**, 66 s — see §7 |

Pinned environment, from `requirements.lock.txt`, cross-checked against the installed
packages actually present in `.venv`:

```
PySide6   6.8.2.1      (pyproject caps <6.9 on purpose; 6.12.0 fails at import)
pyvista   0.49.1
pyvistaqt 0.13.1
vtk       9.6.2
cadquery-ocp 8.0.1.1.0
gmsh      4.15.2    numpy 2.5.4    scipy 1.18.1    trimesh 5.2.0
scikit-fem 12.0.2   matplotlib 3.11.2   ezdxf 1.4.5   pytest 9.1.1
```

CalculiX (`ccx`) is a native executable and is not a Python package; whether it is
installed on this machine was not checked, so every solver-dependent path in the
repository must be treated as unverified here.

### Preserved work

Nothing was deleted, moved or rewritten. The working tree was clean before the pass,
so every change in it now is this pass's. No branch was created, no commit was made,
and no destructive git command was run.

---

## 2. Dependency map

Entry point and shell:

```
__main__.py → app.run()                               app.py
  configure_logging()                                 core/logging_setup.py
  _install_exception_hook()                            app.py
  MainWindow()                                        gui/main_window.py
    Viewport  (central widget)                        gui/viewer/viewport.py
      pyvistaqt.QtInteractor → VTK render window
      tessellate_shape()                              core/cad/tessellate.py
    QDockWidget "Workflow"  (left)                    gui/main_window.py:_build_geometry_dock
      QTabWidget: Geometry | Flexure | Template | FEA | Simulate | Optimise
        GeometryPanel                                 gui/panels/geometry_panel.py
        FlexurePanel                                  gui/panels/flexure_panel.py
        TemplatePanel                                 gui/panels/template_panel.py
        FeaPanel                                      gui/panels/fea_panel.py
        SimulationPanel                               gui/panels/simulation_panel.py
        OptimisePanel                                 gui/panels/optimise_panel.py
    QDockWidget "Measure"   (right)                   gui/main_window.py:_build_measurement_dock
    QDockWidget "Plots"     (bottom, hidden until used)  gui/panels/plots_panel.py
```

Engineering core, grouped by the capability the redesign has to reach:

| Capability | Module | Notes |
|---|---|---|
| CAD import, format registry | `core/cad/registry.py`, `core/cad/loaders/{step,iges,brep,stl,dxf}.py` | STEP/IGES/BREP exact; STL blocked for analysis |
| Geometry model, validity, readiness | `core/cad/model.py`, `core/cad/inspect.py` | `is_analysis_ready`, `analysis_readiness_reasons()` |
| Tessellation for display | `core/cad/tessellate.py` | `TriangleMesh`; the accuracy limit for picking |
| CAD export | `core/cad/export.py` | `write_step` |
| OCC kernel access | `core/cad/_occ.py` | `KERNEL_AVAILABLE`, `require_kernel()` |
| Units and confidence | `core/units.py` | `LengthUnit`, `UnitConfidence` |
| Provenance | `core/provenance.py` | `Provenance`, `TaggedValue`, `downgraded_to` |
| Flexure centreline (axis sweep) | `core/flexure/centerline.py`, `core/flexure/section.py` | refuses meanders |
| Flexure centreline (path following) | `core/flexure/tracing.py` | `trace_centerline` |
| **Parametric generator** | `core/flexure/templates/meander.py` | `MeanderParameters`, `build_meander` — real OCC solid |
| Template adaptation | `core/flexure/adaptation.py` | `verify_regeneration`, reports which parameters moved |
| Reduced-order mechanics | `core/mechanics/{curved_beam,spatial_beam}.py` | planar refuses members that twist |
| Materials | `core/material/models.py`, `core/material/calibration.py` | `provisional_tpu`, the validation gate |
| Meshing | `core/fea/meshing.py` | gmsh, second-order tets |
| Solver | `core/fea/solver.py`, `deck.py`, `runner.py`, `results.py` | CalculiX discovery, deck, run, parse |
| Joint stiffness | `core/fea/joint_stiffness.py` | `JointStiffnessSetup`, `measure_joint_stiffness` |
| Capability gate | `core/fea/capabilities.py` | a capability is off until evidence turns it on |
| Assemblies, joints | `core/assembly/{loader,joint,model,interference}.py` | **not exposed in the GUI** |
| Kinematics, springs | `core/kinematics/*` | Mode 1 / Mode 2 separated in the type system |
| Sweeps, Pareto, sensitivity | `core/optimise/*` | refuses to name a winner on a conflict |
| Projects | `core/project/{schema,store}.py` | `ProjectStore`, geometry copied in |
| Background work | `gui/tasks.py` | `run_in_background`, progress and cancellation |

The `core` / `gui` separation is enforced mechanically by `tests/test_architecture.py`,
which AST-scans every module under `core/` for imports of PySide6, pyvista, vtk or
matplotlib at any nesting depth. The new selection controller sits under `gui/`
and is free of both Qt and VTK, so it is testable headless without weakening that rule.

---

## 3. The point-picking defect

### 3.1 The path, as it was

1. `MainWindow._build_measurement_dock` creates a checkable button labelled
   "Pick two points" and connects `toggled` → `_on_measure_toggled`.
2. `_on_measure_toggled(True)` clears `self._measure_points`, calls
   `Viewport.start_point_picking(self._on_point_picked)`, and sets the status bar to
   **"Click two points on the model."**
3. `Viewport.start_point_picking` called
   `plotter.enable_surface_point_picking(callback=…, show_message=False,
   show_point=True, point_size=12, color="#FF6B6B")`.
4. `_on_point_picked` appended to a list and, on the second entry, computed a
   Euclidean distance and wrote it into a read-only text box.

### 3.2 Root cause

**PyVista does not bind point picking to the left mouse button unless it is told to,
and the application never told it to.**

In the installed PyVista 0.49.1,
`.venv/Lib/site-packages/pyvista/plotting/picking.py`:

- line 800 — `enable_surface_point_picking(..., left_clicking=False, ...)`;
- line 938 — that value is forwarded unchanged to `enable_point_picking`;
- line 650 — `self._init_click_picking_callback(left_clicking=left_clicking)`;
- lines 432–442 — with `left_clicking=False` the observer registered is
  **`RightButtonPressEvent`**, not `LeftButtonPressEvent`;
- lines 653–656 — the on-screen hint PyVista would otherwise draw reads
  `'Left-click' if left_clicking else 'Right-click'`, followed by
  `' or press P to pick under the mouse'`.

So in the shipped build the model could only be picked by **right-clicking** it or by
hovering and pressing **P**. Left-clicking — which is what the panel, the status bar
and every user's instinct call "clicking the model" — dragged the camera and picked
nothing.

**The one thing that would have revealed this was switched off.** Step 3 passed
`show_message=False`, which suppresses exactly the text quoted above. Had the default
been left alone, the viewport would have displayed "Right-click or press P to pick
under the mouse" and the defect would have been a five-second diagnosis instead of a
silent one.

This is also why the symptom reads as *unreliable* rather than *absent*: a user who
happened to right-click, or who had their mouse buttons swapped, or who pressed P
while hovering, got a measurement. Everyone else got nothing.

### 3.3 The other defects on the same path

Each of these was read out of the source, and each is independent of the root cause —
fixing the button binding alone would have left all of them.

1. **A background click became a coordinate.** `vtkCellPicker` still returns a
   `GetPickPosition()` for a click into empty space: a point on the focal plane. With
   `pickable_window=False` PyVista returns early *before* calling the callback
   (`picking.py:904`), so the application could not distinguish a miss from a hit and
   could not report one. A click that produces nothing visible is indistinguishable
   from a tool that does not work.

2. **Only one marker was ever visible.** PyVista's picked-point representation is
   added under a single actor name for every pick — `picking.py:627`, `name=…
   PICKED_REPRESENTATION_NAMES['point']`, which is the constant `'_picked_point'`
   defined at line 43. The second pick therefore *replaced* the first point's marker,
   so a two-point selection was never shown as two points.

3. **Points outlived the model they were picked on.** `self._measure_points` was
   cleared when picking was armed and when the second point landed, and nowhere else.
   `_on_import_finished` and `_on_template_built` replaced `self._model` and the whole
   scene without touching it. A point picked before an import could therefore pair
   with a point picked after one, and the panel would report a distance **between two
   different parts**, with correct-looking coordinates and no warning.

4. **Clearing the scene left picking armed.** `Viewport.clear` called
   `plotter.clear()`, which removes the actors and the picking text but leaves
   PyVista's observers installed and its `_picker_in_use` flag set — `disable_picking`
   (`picking.py:456–486`) is the only thing that resets them, and `Plotter.clear` does
   not call it. The viewport was then armed against actors that no longer existed, and
   because `enable_point_picking` begins with `_validate_picker_not_in_use()`
   (`picking.py:590`), the next attempt to arm would raise `PyVistaPickingError` out of
   a Qt slot.

5. **Stopping left the markers behind.** `disable_picking` does not clear the picked
   representations, and `clear_measurement` removed only `"measurement_line"`. Markers
   from an abandoned selection stayed on screen.

6. **Coincident points were accepted.** Two picks on the same spot produced
   `Distance: 0.0000 mm`, presented as a measurement.

7. **There was no joint-axis path at all.** The viewport could measure and nothing
   else. The joint axis — the input the README names as the one a 2 mm error in
   changes the reported stiffness substantially — could only be typed in, or filled
   from a bounding box by `_suggest_joint_axis` / `_suggest_fea_axis`, both of which
   correctly describe themselves as guesses.

8. **The bounds grid was pickable.** `show_grid` adds a `vtkCubeAxesActor` with
   default pickability, so a click near the grid could in principle report a
   coordinate out in empty space.

---

## 4. What already exists for parametric design

Worth stating plainly, because the redesign brief treats parametric generation as
something to be built and most of the geometry half of it is already here and tested.

**Genuinely implemented, generating real CAD:** one family, the **meander
(serpentine)**, in `core/flexure/templates/meander.py`. `build_meander` returns an
OpenCASCADE solid assembled from boxes and annular half-sectors by boolean union, with
coplanar faces unified afterwards. Parameters: `run_length`, `n_runs`, `pitch`,
`width`, `thickness`, `tab_length`, `tab_width`. `MeanderParameters.__post_init__`
rejects infeasible combinations (fewer than two runs, non-positive dimensions, pitch
not exceeding width, an inner turn radius at or below modelling tolerance), and the
class derives `centreline_length`, `expected_volume`, `envelope` and
`minimum_feature_size` analytically — so the built solid's measured volume can be
checked against the exact value the parameters imply, which `_template_worker` in
`main_window.py` does on every build.

**Not a generator:** the A3 twin-strap arch is an *imported* part, not a family. The
"flexure" path (`core/flexure/centerline.py`, `core/mechanics/curved_beam.py`)
measures and analyses imported geometry; it does not synthesise it.

So the parametric-design stage is not a from-scratch build. What it needs is a family
abstraction over the one real generator, a parameter model that the GUI reads rather
than duplicates, named design variants, and the provenance links from a variant to the
analysis run that used it. The geometry generation itself is done and verified.

---

## 5. What P1 changed

Three files touched, two added.

| File | Change |
|---|---|
| `src/barnes_ui/gui/viewer/selection.py` | **new.** The two-point protocol as an explicit state machine. No Qt, no VTK, no geometry kernel. `SelectionPurpose`, `SelectionState`, `PickOutcome`, `TwoPointSelection`, `PointSelectionController`. |
| `src/barnes_ui/gui/viewer/viewport.py` | Picking rewritten: left button bound, misses detected and reported, one marker actor per point, session tokens, own on-screen instruction, explicit teardown on `clear`, `enable_section` and `close_viewport`, bounds grid made unpickable. |
| `src/barnes_ui/gui/main_window.py` | Measure dock rebuilt around the controller: purpose selector, state-driven instruction, Confirm / Clear / Cancel, joint-axis definition that writes into the Flexure and FEA panels only after confirmation, invalidation on import and on regeneration. |
| `tests/test_selection.py` | **new.** The controller, headless. |
| `tests/test_gui_picking.py` | **new.** The viewport against a real VTK render window, and the window's wiring. |

Design decisions worth recording:

- **A measurement and a joint axis share the picker and nothing else.** A measurement
  is readable the moment the second point lands. An axis is not readable *at all*
  until `confirm()` — `confirmed_axis` returns `None` for a preview, for a
  measurement, and after any invalidation — so there is no route by which an
  unconfirmed pick reaches an analysis.
- **Coincidence tolerance differs by purpose by five orders of magnitude.** A 0.01 mm
  distance is a legitimate measurement; a *direction* from two points 0.01 mm apart is
  the tessellation's chord error divided by the baseline and multiplied into an angle.
  Measurement refuses only floating-point noise (1e-6 mm); an axis demands the greater
  of 0.5 mm and 2 % of the model's bounding-box diagonal.
- **The origin of a confirmed axis is the midpoint of the two picks.** That is the only
  origin two points justify, and the confirmation message says so rather than implying
  the axis was measured.
- **Session tokens, not flags.** `begin()` returns a token; `add_point` takes one and
  drops anything from a replaced session. VTK observers and Qt slots both outlive the
  code that registered them.
- **The tessellation warning stays.** Nothing here snaps to exact vertices or edges,
  so the panel still says the measurement carries the display mesh's chord tolerance.
  The claim that this is "Phase 2 work" was dropped — Phase 2 shipped and it was not
  done.

---

## 6. Remaining stages

In the brief's own order, with what the audit says each one actually involves.

**P2 — workflow UI. Done; see §8.**

**P3–P4 — family abstraction and variants.** A registry over `build_meander` so a
second family can be added without touching the GUI; a validated parameter model as the
single source of truth for bounds and units; named variants persisted through
`core/project/store.py` rather than a second storage system.

**P5–P6 — analysis provenance and comparison.** Bind every run to an immutable
snapshot of the inputs that produced it, mark dependents stale when an input changes,
keep superseded runs as history, and compare only compatible configurations.

**P7–P9 — further families, sweeps, verification.** `core/optimise/*` already does
sweeps, Pareto fronts and sensitivity; the work is exposing them against real variants
and documenting what each reported stiffness definition is.

---

## 7. Tests executed, and what is still unverified

### 7.1 The run

```
.\.venv\Scripts\python.exe -m pytest -q
704 passed in 66.22s (0:01:06)        exit code 0
```

**704 passed, 0 failed, 0 skipped, 0 errors.**

`tests/test_selection.py` and `tests/test_gui_picking.py` contribute 90 test
functions, 95 collected cases once the one parametrised case is expanded. The
remainder — 609 — is the pre-existing suite, and since the whole run exited 0, **no
pre-existing test regressed.** That 609 was originally arithmetic on the total, since
the attempt to run the two halves separately was defeated by the tooling outage in
§7.3. It has since been measured directly: the suite was run at each commit of the
`workflow-redesign` branch, and the commit before this stage's code reports exactly
**664 passed** — 609 plus this stage's 55 collected cases.

**Nothing was skipped**, which is itself worth recording, because three of the ways
this suite could have reported a hollow pass are all ruled out by it:

- the `gui`-marked tests in `test_gui_picking.py` **ran**, so a real VTK render window
  was created rather than the module skipping on no usable OpenGL;
- the `cad_kernel`-marked tests ran, so OpenCASCADE is present and the generated STEP
  fixtures were really built and re-imported;
- `tests/test_architecture.py` passed, so the new `gui/viewer/selection.py` has not
  leaked a Qt or VTK import into `core/`.

### 7.2 The assertion that matters most

`test_arming_binds_the_left_mouse_button` passed. It reaches into PyVista's picking
component and asserts that after `start_point_picking` the installed observer is
`_picking_left_clicking_observer` and that `_picking_right_clicking_observer` is
`None`. That is private API on purpose: the public surface does not report what the
mouse is bound to, and that binding is exactly what §3.2 shows was wrong. It is the
only automated check in the repository that the left button picks, and a mocked
callback test would have passed throughout the bug's life. If a PyVista upgrade
renames the attribute, this test failing is the correct outcome.

### 7.3 Still unverified

- **Nobody has clicked the real application.** The automated tests drive
  `Viewport._on_point_picked` and the window's slots directly, and they confirm the
  left-button observer is installed — but an installed observer firing on a genuine
  mouse-down in a visible window is one link further than any test here reaches. Until
  someone performs the manual check below, "left-clicking the model now produces a
  measurement" rests on the PyVista source in §3.2 plus the observer assertion in
  §7.2, and not on an observation.
- **No FEA was run.** CalculiX *is* installed on this machine -- the startup smoke
  test in §8.4 logged `Found CalculiX at
  C:\Users\msaip\AppData\Local\Programs\CalculiX\calculix_2.23_4win\ccx_static.exe`,
  which corrects an earlier statement in this document's history that it had not been
  probed. Discovery succeeding is not a solve succeeding, and no solve was submitted
  in this work.
- **No performance work was done.** P1 touched picking only.

### 7.4 Commands

```powershell
cd C:\Users\msaip\OneDrive\Desktop\Barnes\Barnes_UI
.\.venv\Scripts\python.exe -m pytest -q                      # whole suite
.\.venv\Scripts\python.exe -m pytest tests/test_selection.py tests/test_gui_picking.py -v
.\.venv\Scripts\python.exe -m pytest -m "not gui" -q          # headless only
.\.venv\Scripts\python.exe -m barnes_ui                       # launch the application
.\.venv\Scripts\python.exe -m barnes_ui path\to\part.step      # open a part directly
```

Manual check for the defect this pass targets, and the one outstanding item in §7.3:

1. Open a STEP part and fit it to the window.
2. Choose "Distance between two points"; press **Pick two points**.
3. **Left-click** twice on the model. Both markers must stay visible, the line must be
   drawn, and the panel must report the distance.
4. Left-click the background. The panel must say the click missed; the first point
   must survive.
5. **Clear**, pick again, **Cancel** — the camera must tumble normally afterwards.
6. Switch to "Joint axis from two points", pick twice. Check the Flexure and FEA panels
   are **still untouched**, then press **Confirm** and check the origin and direction
   appear in the Flexure panel and the origin in the FEA panel.
7. Pick twice on the same spot in axis mode; it must be refused with the threshold
   quoted.
8. Import a different part mid-selection; the panel must say the selection was
   discarded, and the next pick must start a fresh pair.

---

## 8. P2 — the workspace redesign

### 8.1 What replaced what

The six peer tabs are gone as a top-level structure. Nothing they exposed was removed.

| Before (named after modules) | After (named after the task) |
|---|---|
| Geometry | **Inspect** workspace, in full — plus a new read-only summary card in Design |
| Template | **Design** workspace |
| Flexure, FEA, Simulate | **Analyse** workspace, as "Reduced-order model", "Nonlinear FEA", "Motion" |
| Optimise | **Compare** workspace |

Layout, top to bottom: a project header spanning the window, then the workflow bar,
then a splitter with the workspace panels on the left and the viewport on the right.
The panels moved out of a dock widget into the splitter — the viewport has to stay
large, which a splitter states once (panels get their 460 px minimum, the viewport
gets the rest and keeps it on resize) where four competing docks left it to whichever
Qt sized first. Measure and Plots remain docks.

Analyse is the only workspace with sub-tabs, one level deep, because three panels in
one column is roughly three thousand pixels of form. They are labelled by the question
each answers rather than by the module behind it.

### 8.2 The workflow model

`src/barnes_ui/gui/workflow.py` — no Qt, no VTK, so all of it is testable headless.

Six steps across the three task workspaces (Inspect owns none; it is supporting, not a
stage): Geometry → Parameters → Joint axis → Readiness → Analysis → Comparison. Five
statuses: Not started, In progress, Complete, Needs attention, Blocked.

`assess(facts) -> Workflow` is a pure function. **There is no fact meaning "the user
visited this panel"**, so a step cannot reach Complete by being navigated past —
`test_an_empty_project_has_no_complete_steps` pins that. Four decisions in it are worth
recording:

- **Blocked and Needs attention are different claims.** Blocked means an earlier step
  has to happen first and there is nothing to do *here*; Needs attention means this
  step is where the problem is. It matters for where the user gets sent: Readiness
  reporting Needs attention for a missing joint axis made it outrank the Joint axis
  step that fixes it, so the bar pointed at Analyse to solve a Design problem. Readiness
  is now a gate, never a task.
- **A step with nothing to do is never offered as the next step.** The Parameters step
  on an imported part is permanently Not started — a STEP file carries no parametric
  history — and its `next_action` is `None`, so navigation skips it instead of burying
  the step that matters behind one that cannot be finished.
- **`limitation` is separate from `next_action`.** What this build cannot do at all
  (named variants; an axis read from a file; exact vertex snapping; an uncalibrated
  material) is stated independently of what the user can do now. Conflating them would
  either promise a feature or hide a gap.
- **Where the geometry came from and whether it still matches are two facts.**
  `geometry_is_generated` is history and does not change when a parameter is edited;
  `parameters_match_geometry` is the live comparison. One field doing both work made an
  edited parameter indistinguishable from an imported part.

### 8.3 Staleness

Results stop being current the moment an input under them moves, and the workflow says
which input:

- a parameter edited after a solid was generated → the Parameters step drops to In
  progress ("the preview is stale: it is a picture of a different design") and any
  result goes to Needs attention. Compared **by value** against the parameters the
  solid was built from, not tracked with a dirty flag, so nudging a spinbox and putting
  it back reports nothing — a warning that fires on a no-op trains people to ignore it;
- a confirmed joint axis changed after a result → stale, naming the axis;
- an import → results are **cleared**, not marked stale. A stale result is one you can
  still compare against; a result for a different part is not;
- a generated solid that fails its own volume check → the Geometry step goes to Needs
  attention and Readiness and Analysis are **Blocked**, even though OpenCASCADE calls
  the solid valid and `analysis_ready` is True. Previously this was a modal dialog, and
  a dismissed dialog stops saying anything.

A failed solve is Needs attention with the solver's reason and "a failed solve is not a
zero-stiffness design". A cancelled one is not a failure and claims nothing.

### 8.4 Files

| File | Change |
|---|---|
| `gui/workflow.py` | **new.** Steps, statuses, facts, `assess`. Qt-free. |
| `gui/workspaces.py` | **new.** `WorkspaceNavigator`: selector over a page stack. |
| `gui/panels/workflow_bar.py` | **new.** Clickable step chips plus the next-action line. |
| `gui/panels/project_header.py` | **new.** Application, project, active design, unsaved marker. |
| `gui/panels/geometry_summary.py` | **new.** Read-only geometry card for Design. |
| `gui/panels/_common.py` | `STATUS_COLOURS` added, beside the provenance palette. |
| `gui/main_window.py` | Tabbed dock replaced by header + workflow bar + splitter; fact gathering; staleness; stale "Phase 1" title and About text corrected. |
| `gui/panels/template_panel.py` | `blocking_reason()`, `parameters_changed` signal. |
| `gui/panels/fea_panel.py` | `solver_available`, `solver_description`. |
| `tests/test_workflow.py` | **new.** 32 tests of the derivation. |
| `tests/test_gui_workspaces.py` | **new.** 72 tests of the widgets and the window's wiring. |
| `tests/test_gui_picking.py` | Tab-switching test rewritten for workspaces. |

Two panel accessors were added rather than reading private widgets from the window, so
the workflow reports the same verdict the Build button and the solver label enforce
instead of a second copy of the rule drifting away from it.

### 8.5 Tests

```
.\.venv\Scripts\python.exe -m pytest -q
808 passed in 74.17s (0:01:14)        exit code 0
```

**808 passed, 0 failed, 0 skipped** — 704 before this stage plus the 104 new ones, so
nothing that was passing regressed.

Nine of the new tests failed on first run and all nine were fixed in the source rather
than in the assertions, except three where the test had encoded the wrong expectation:
the Readiness/Joint-axis precedence, the two-facts split, and a default. Those are
described in §8.2 and the tests now state the corrected rule with the reason.

Startup was verified by running the real entry point offscreen
(`scratchpad/smoke_launch.py`): `app.run()` returns 0, four workspaces exist, Design is
current, the viewport is visible, and all six panels are in the widget tree. That run
also logged CalculiX 2.23 being found.

### 8.6 Still not done at P2

- **Nobody has used the redesigned window on a desktop.** Everything above is offscreen
  Qt. The layout's behaviour under real resizing, and whether the workflow bar reads as
  intended at a glance, are not things these tests can tell you.
- **Named design variants are still not implemented**, so Compare compares candidates
  within one sweep run and the header says "unsaved" rather than naming a design. The
  workflow states this as a limitation on every Comparison state rather than leaving a
  gap the user discovers.
- **No analysis run was exercised through the new layout** — the FEA and simulation
  paths are reached through it in the tests only as far as their panels.

---

## 9. Visual checking

### 9.1 Why it was needed

The P2 window passed 808 tests and looked like this on the machine it runs on: the
header's three fields rendered as near-black boxes floating on a light desktop, and
four of the six workflow chips were red the moment the application opened.

Both are invisible to the suite by construction. Every test asserted that a label
held the right string, and every label did. `ProjectHeader` set
`background: #22262C` on itself with pale text on its children -- correct on the dark
theme it was written against, unreadable on the light one actually in use. And since
a Qt stylesheet's `background` is inherited by child widgets while the parent paints
nothing, what appeared was not even a bar.

The lesson is narrow and worth stating: **a test suite can check what a widget says
and not what it looks like.** Something has to look.

### 9.2 The harness

`scripts/visual_check.py` drives the real widgets into thirteen states and writes a
PNG of each to `results/visual/`, plus close-ups of the header, the workflow bar and
the Measure dock where the colour decisions live.

```powershell
.\.venv\Scripts\python.exe scripts\visual_check.py
.\.venv\Scripts\python.exe scripts\visual_check.py --only stale
```

Two decisions in it are deliberate:

**It uses the native Qt platform, not offscreen.** The first version forced
`QT_QPA_PLATFORM=offscreen` and every string rendered as a row of empty boxes,
because offscreen Qt has no access to the system fonts -- useless for the thing the
images exist to check. Worse, it would have used a default palette rather than the
desktop's, and the defects being hunted *were* palette defects. The window is created
with `WA_DontShowOnScreen`, so it lays out exactly as a shown window does and never
appears. `BARNES_VISUAL_OFFSCREEN=1` forces the old behaviour where there is no
display at all; the layout is still right and the text is still boxes.

**It does not compare against reference images.** A pixel-diff harness on a Qt
application fails on a font-rendering change and passes on a contrast error that makes
a panel unreadable, which is exactly backwards. The images are evidence for a human
decision. The states are chosen to be the ones where a mistake is expensive: an empty
application (what a new user sees first), a stale result (the state the whole
provenance discipline exists to make visible), a blocked step, a generated solid that
fails its own volume check, and the two narrowest layouts the window permits.

### 9.3 What it caught, and the fixes

| Defect | Fix |
|---|---|
| Header unreadable: dark background, pale text, on a light desktop | No background at all. Text colour only, inheriting the theme; a faint `·` divider between fields and a 1 px rule under the bar for structure. The UNSAVED badge keeps its background because it sets its foreground in the same rule. |
| Four red chips on an empty project | **Red is now reserved for the user's problem.** Blocked -- not reachable yet, nothing to do here -- is the muted grey used elsewhere for inactive text; Needs attention is red. The original mapping had it backwards. |
| At 900 px the viewport was crushed to 305 px, the narrowest region on screen | A minimum width on the viewport as well as the panels. Stretch factors give a growing window's space to the viewport, which is right, and a shrinking window's loss to it too, which is not. A parameter form scrolls; a 3D view does not. The window now declines to shrink below 1120 x 720, which is what its three regions need. |

### 9.4 The guard

`TestThemeSafety` in `tests/test_gui_workspaces.py` scans every `setStyleSheet`
literal under `gui/` and fails any rule that sets a background without setting a
foreground in the same rule. That is the exact shape of the header bug, and it is a
static scan for the same reason `test_architecture.py` scans source rather than
importing: a rule inside a rarely taken branch would pass a check that only looked at
the window as currently built.

It cannot catch a bad colour *choice* -- only a colour that depends on the theme to be
legible. Choosing well still needs someone to look at the pictures.

### 9.5 Tests after the visual pass

```
812 passed in 76.70s (0:01:16)        exit code 0
```

**812 passed, 0 failed, 0 skipped** -- 808 plus two theme-safety tests and two layout
floors.

---

## 10. Commits

Branch `workflow-redesign`, cut from `main` at `c602162`. Not pushed.

| Commit | Scope | Suite at that commit |
|---|---|---|
| `3337090` | Point picking: the left-button binding and seven related defects, plus the selection controller | **664 passed** |
| `acc988f` | The four workspaces, the workflow model, staleness, and the window's rewiring | **812 passed** |
| *(this one)* | The visual-check harness, the layout and colour fixes it found, and this document | **812 passed** |

Each was run on its own checkout rather than assumed, which is also what turned the
609 figure in §7.1 from arithmetic into a measurement.

The split is by what can stand alone, not by stage: the selection controller is
independent of the window, so it is its own commit, while P1's wiring into the window
necessarily lands with P2 because both edit `main_window.py` and neither half of that
file is a working program. The colour and layout fixes in §9.3 are in the third commit
with the harness that found them, which means the second commit contains a header that
is unreadable on a light desktop. That is what happened, and the history says so
rather than tidying it away.
