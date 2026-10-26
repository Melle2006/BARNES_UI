# Software Stack

Every choice below is justified against the specific needs of this project, and each entry
states its Windows installation route. Alternatives that were considered and rejected are
recorded so that the decision does not have to be re-litigated later.

---

## 1. The stack at a glance

| Layer | Choice | Version target | Why |
|---|---|---|---|
| Language | Python | 3.12 | Only ecosystem with CAD kernel bindings, meshing, solvers, GUI and plotting all available |
| GUI | PySide6 (Qt 6) | ≥ 6.6 | LGPL, official Qt binding, mature widget set, native Windows look |
| CAD kernel | OpenCASCADE via `cadquery-ocp` (OCP) | 8.0.x | The only open-source kernel with real STEP/IGES/BREP support; native win_amd64 wheel for Python 3.12 confirmed |
| Mesh/STL I/O | `trimesh` | ≥ 4.0 | Robust STL reader, mesh repair utilities, fast proximity queries |
| DXF | `ezdxf` | ≥ 1.3 | Pure Python, complete DXF entity coverage |
| 3D viewport | PyVista + `pyvistaqt` (VTK 9) | ≥ 0.44 | Embeds in Qt, picking and section planes out of the box, far less code than raw VTK |
| Plotting | Matplotlib (QtAgg backend) | ≥ 3.8 | Publication-quality static figures for reports |
| Numerics | NumPy, SciPy | ≥ 1.26, ≥ 1.11 | Curve fitting, integration, optimisation |
| Meshing (Phase 3) | Gmsh Python API | ≥ 4.12 | Reads BREP directly from OpenCASCADE, second-order tets, Windows wheel |
| FEA solver (Phase 3) | CalculiX (`ccx`) | ≥ 2.20 | See [03-solver-comparison.md](03-solver-comparison.md) |
| Multibody (Phase 5) | Custom rigid-body kinematics on NumPy | — | The hand has few joints with prescribed angles; a full physics engine is unnecessary weight |
| Tests | pytest | ≥ 8.0 | Standard; engineering core is testable headless |
| Packaging | `pyproject.toml`, src layout | — | Editable install, no path hacks |

---

## 2. Rationale for the decisive choices

### CAD kernel — OpenCASCADE through OCP

This is the choice everything else follows from, because it determines what files can be opened
at all.

OpenCASCADE is the only mature open-source B-rep modelling kernel. It provides STEP and IGES
readers, exact geometry queries (volume, inertia, curvature, surface type), boolean operations,
and triangulation. FreeCAD, KiCad's 3D viewer, and CadQuery are all built on it.

Two Python bindings exist: `pythonocc-core` and `OCP`. OCP was selected because it is distributed
as a PyPI wheel including a `cp312-cp312-win_amd64` build, verified to resolve on this machine,
whereas `pythonocc-core` is primarily distributed through conda. Avoiding a conda requirement
keeps the setup instructions to a single `pip install -e .`, which matters for collaborators who
will be setting this up without help.

**Rejected: FreeCAD as a library.** FreeCAD embeds OpenCASCADE and adds a document model, and it
is often suggested for projects like this. It was rejected as the foundation because importing
FreeCAD's Python modules outside the FreeCAD application is awkward on Windows, it drags in a
large GUI framework that would conflict with our own, and it offers nothing over OCP for the
operations we need. FreeCAD remains useful to the user as an external viewer and as a conversion
tool, and the project will not prevent that.

**Rejected: mesh-only (trimesh/Open3D) pipeline.** Working purely with triangle meshes would be
simpler and would handle STL natively. It was rejected because a tessellated model has lost the
exact surfaces. Bend radius, true arc length, and cross-section geometry — the quantities this
whole project is about — can only be approximated from a mesh, and the approximation error varies
with the export tolerance the user happened to pick in SolidWorks. For a part whose behaviour
depends on its third power of width, that is not acceptable. STL is still supported as an input
format, but with an explicit warning that exact geometric queries are unavailable for it.

### GUI — PySide6

Qt is the only option that gives a professional engineering layout (dockable panels, trees,
property grids, background task integration) with an acceptable licence. PySide6 is the official
binding under LGPL, which is the right licence for a project that may be shared.

**Rejected: PyQt6** — functionally equivalent, but GPL/commercial dual licensing creates an
obligation this project does not need to take on.
**Rejected: Dear PyGui / web front-end** — immediate-mode and browser UIs are quicker to start
but fight you on native file dialogs, docking, and embedding a VTK render window.

### 3D viewport — PyVista + pyvistaqt over raw VTK

VTK does the rendering either way. PyVista is a thin, well-maintained wrapper that reduces a
clipping-plane widget or a point-picking callback from ~80 lines of VTK boilerplate to ~5. The
`pyvistaqt.QtInteractor` widget drops directly into a Qt layout. Raw VTK remains reachable
underneath for anything PyVista does not expose, so nothing is given up.

### Meshing — Gmsh

Gmsh can consume an OpenCASCADE BREP shape directly, so the solid never has to be round-tripped
through a mesh format and re-healed. It generates second-order tetrahedra (`C3D10` in CalculiX
terms), which is what a nearly incompressible hyperelastic material needs — first-order tets lock
severely and would report a flexure as far stiffer than it is. It has a Python API and a Windows
wheel.

### Multibody — hand-rolled, not a physics engine

Phase 5 needs to place rigid phalanges at prescribed joint angles and evaluate a torsional spring
at each joint. That is forward kinematics plus a table lookup: a few hundred lines of NumPy with
no solver stability concerns. Pulling in PyBullet or MuJoCo would add a large dependency, a
second notion of "the model", and a time-stepping integrator that we do not want for a
quasi-static study. If genuine dynamics is ever needed — fast motion where inertia matters — that
decision can be revisited on its own merits.

---

## 3. Windows compatibility

| Package | Install route | Notes |
|---|---|---|
| `cadquery-ocp` | pip wheel | Verified: `cp312-cp312-win_amd64` wheel resolves. Large download (~200 MB) — expected, it contains the full OCCT runtime |
| `PySide6` | pip wheel | Pulls `PySide6_Essentials`, `PySide6_Addons`, `shiboken6` |
| `vtk` | pip wheel | 9.7.x. Needs a working OpenGL driver; software rendering under RDP can be slow |
| `pyvista`, `pyvistaqt` | pip wheel | Pure Python |
| `trimesh`, `ezdxf` | pip wheel | Pure Python |
| `numpy`, `scipy`, `matplotlib` | pip wheel | Already present in the Anaconda base environment on this machine |
| `gmsh` | pip wheel | Ships its own binary; no separate install |
| **CalculiX** | **manual** | Not a Python package. Needs a Windows build placed on `PATH` or configured in the app. See below |

### The one manual step: CalculiX

CalculiX is a native executable, not a pip package. On Windows the practical options are the
bConverged "CalculiX for Windows" distribution, or the binaries bundled inside a FreeCAD
installation (FreeCAD ships `ccx.exe`, which is a legitimate way to obtain it without a separate
download).

The application will **not** silently proceed without it. It locates `ccx` via an explicit
setting, falling back to `PATH`, and if it is absent the FEA features are disabled with a message
explaining how to install it — rather than quietly dropping to the reduced-order model and
presenting the result as if it were FEA.

### Known Windows caveats

- **OneDrive.** This project lives under a OneDrive-synced folder. Solver runs write many
  intermediate files; OneDrive will try to sync them mid-write. Scratch and solver working
  directories are therefore placed outside the project tree (under the user's local temp
  directory) and only final results are written back.
- **Path length.** Solver working directories are kept short for the same historical reason.
- **Antivirus.** Real-time scanning can slow down solver runs that write thousands of small files.
  Worth excluding the scratch directory if runs seem inexplicably slow.
- **High DPI.** Qt 6 handles this automatically; VTK render windows occasionally need the scale
  factor set explicitly, handled in the viewer setup.

---

## 4. Dependency policy

- Pinned with lower bounds in `pyproject.toml`, exact versions captured in
  `requirements.lock.txt` so a working combination can always be reproduced.
- No dependency is added without a note in the commit message explaining what it does and what
  was considered instead.
- The engineering core (`barnes_ui.core`) must not import PySide6, PyVista, or Matplotlib. This
  is enforced by a test, so that the physics stays runnable and testable headless and the rule
  does not erode over time.
