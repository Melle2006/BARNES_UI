# CalculiX Installation — What Was Installed and Why

This document exists because installing a third-party native binary is a decision, not a
detail. Anyone picking up this project is entitled to know what was put on the machine,
where it came from, why it was necessary, and what was done to check it before it was
trusted.

---

## 1. What was installed

| | |
|---|---|
| **Package** | `calculix_2.23_4win.zip` |
| **Version** | CalculiX 2.23 |
| **Source** | `http://www.dhondt.de/calculix_2.23_4win.zip` |
| **Published** | 2025-11-06 (server `Last-Modified`) |
| **Download size** | 61,675,985 bytes (58.8 MB) |
| **SHA-256** | `87fc4e1721df37370ec67d0a244bb14f9bf804b0a95df49e2ae7369d30ec72e8` |
| **Installed to** | `%LOCALAPPDATA%\Programs\CalculiX\calculix_2.23_4win\` |
| **Executable used** | `ccx_static.exe` (39.92 MB) |
| **Installed on** | 2026-10-26 |

Record the SHA-256. It is the only way anyone can confirm later that they have the same
solver this project's results were produced with.

### Why `dhondt.de`

Guido Dhondt is CalculiX's author. `dhondt.de` is his own site and the canonical
distribution point — the same source as the user manual cited throughout
[03-solver-comparison.md](03-solver-comparison.md), including the viscoelasticity
findings. There is no more authoritative source for the binary.

### What the archive contains

```
calculix_2.23_4win/
    ccx_static.exe          solver, statically linked          39.92 MB
    ccx_dynamic.exe         solver, dynamically linked         39.94 MB
    ccx_dynamic_i8.exe      solver, 8-byte integers            36.38 MB
    ccx_i4.exe              solver, 4-byte integers            40.34 MB
    cgx_GLUT.exe            pre/post-processor GUI              5.68 MB
    cgx_STATIC.exe          pre/post-processor, static          6.13 MB
    tetgen.exe              tetrahedral mesher                  1.42 MB
    glut64.dll              OpenGL toolkit for cgx              0.26 MB
    cgxCadTools/            CAD conversion helpers
```

**`ccx_static.exe` is the one this project uses.** Statically linked, so it carries no
external DLL dependency — which removes exactly the failure mode `probe_solver` was
written to catch, where a binary sits on disk looking fine and fails the moment it is
invoked because a runtime library is missing.

`cgx` and `tetgen` are unused. This project has its own viewer and uses Gmsh for
meshing. They are left in place because they are part of a coherent distribution and
removing pieces of it would make the SHA-256 above meaningless.

---

## 2. Why it was necessary

CalculiX is the production FEA solver chosen in
[03-solver-comparison.md](03-solver-comparison.md). It is a native executable, not a
Python package, so it cannot be installed by `pip` and the project cannot carry it.

Before installing it, two Phase 3 acceptance criteria were blocked and had to be
recorded as such:

- **Criterion 2** — hyperelastic uniaxial tension against the Neo-Hookean closed form,
  to better than 1 %. The material law itself was already verified analytically in
  `test_material`, but confirming that *CalculiX integrates it correctly* needs a run.
- **Criterion 7** — the discrepancy between the reduced-order model and FEA on the real
  flexure. This is the single most important number in Phase 3: until it is measured,
  the fast model's error is unknown, and nobody can say whether it may be trusted for
  design iteration.

A third thing was unverifiable without it: whether the decks this project generates are
accepted by a real solver at all. They were not, as it turned out. See section 4.

### Why not FreeCAD

FreeCAD bundles CalculiX and was the first route considered, because the FreeCAD wiki
confirms its packages "already include Gmsh and CalculiX". It was rejected once checked:

- FreeCAD's own wiki says a better, more up-to-date CalculiX is available from the
  official site, so the bundled copy is the worse of the two.
- It is a ~1 GB installer that registers itself with Windows, to obtain one ~40 MB
  executable.
- This project explicitly does **not** depend on FreeCAD.
  [02-software-stack.md](02-software-stack.md) rejected FreeCAD-as-a-library: awkward to
  import outside its own application on Windows, drags in a GUI framework that conflicts
  with this project's Qt, and offers nothing over the OCP bindings already in use.
  Installing the whole application to harvest one binary would invite the assumption
  that a dependency exists where none does.

The official ZIP needs no installer, writes nothing outside its own directory, and gives
a newer solver.

---

## 3. What was checked before trusting it

An executable downloaded from the internet is untrusted until inspected. In order:

1. **Headers before body.** `Content-Type: application/zip`, `Content-Length` matching
   the eventual file size.
2. **Magic bytes.** `50 4b 03 04` — a genuine ZIP. Worth noting that Git Bash's `file`
   reported only "data", because its magic database here is limited; the bytes settled
   it.
3. **Archive integrity.** `zipfile.testzip()` reported no corrupt member across all 13
   entries.
4. **Path safety.** Every member checked for absolute paths, drive letters and `..`
   traversal segments. None found. Re-checked a second time at extraction, not only at
   inspection, since the two are separate moments.
5. **Executable inventory.** All 10 `.exe`/`.dll` entries listed and accounted for
   before extraction, so nothing arrived unnoticed.
6. **Isolation.** Downloaded into its own empty directory. The inspection and extraction
   scripts were written in a *different* directory, because a Python interpreter started
   inside an untrusted archive's folder will import modules planted there.
7. **It actually runs.** `probe_solver` executed it and read its banner. Installed is
   not the same as working.

---

## 4. What installing it immediately revealed

Three defects in this project's own code, none of which could have been found any other
way. This is the argument for installing it rather than shipping an unexercised
pipeline.

**The solver needs `-i`.** Its usage banner is `Usage: CalculiX.exe -i jobname`. The
runner invoked `ccx jobname` without the flag, which makes CalculiX print the banner and
exit **0** without solving anything — a successful-looking run producing no results.

**Gmsh and CalculiX order C3D10 mid-side nodes differently.** Positions 8 and 9 are
swapped: Gmsh has `mid(2,3)` then `mid(1,3)`, CalculiX the reverse. The first real
submission failed on element after element with
`*ERROR in e_c3d: nonpositive jacobian`, despite every element having a positive corner
volume by this project's own quality check. The corner orientation was correct all
along; a 10-node tetrahedron's Jacobian depends on all ten nodes, and two misplaced
mid-edge nodes fold the element.

**The log parser mistook residuals for errors.** CalculiX's linear solver prints lines
reading `error  9.2425e-09` — convergence residuals. Matching bare `error` declared a
perfectly healthy run non-converged: three decreasing residuals, a clean `Job finished`,
correct reactions, verdict *failure*. Only `*ERROR`, with the asterisk, marks a real
error. This was the mirror image of the failure mode the project is built around —
reporting a good result as bad rather than a bad result as good.

And one more, found driving a joint rotation:

**A `*RIGID BODY` referencing an undefined node set produces a converged null solve.**
The deck writer only emitted node sets referenced by boundary conditions or reaction
sets, so the rigid body's member set was never defined. CalculiX emitted a single
`*WARNING`, carried on, solved a model with nothing tied and nothing loaded, and reported
**CONVERGED** with every displacement and every reaction exactly zero. A correct solution
to a problem nobody posed.

`FeaResult.is_null_solution` now detects this and `is_trustworthy` is false for it, on
the principle that convergence is a numerical property and says nothing about whether a
question was asked.

---

## 5. Reproducing this install

```bash
curl -L -o calculix_2.23_4win.zip http://www.dhondt.de/calculix_2.23_4win.zip
sha256sum calculix_2.23_4win.zip   # expect 87fc4e17...30ec72e8
```

Extract anywhere, then point the application at the solver. Either put it on `PATH`, or
set the environment variable, which takes priority:

```bash
setx BARNES_UI_CCX "%LOCALAPPDATA%\Programs\CalculiX\calculix_2.23_4win\ccx_static.exe"
```

`core/fea/solver.py` searches, in order: an explicitly supplied path, `BARNES_UI_CCX`,
`PATH`, then a short list of conventional Windows locations including FreeCAD's `bin`
directory, so a FreeCAD-bundled solver is also found without configuration.

### Checking it worked

```bash
python -c "from barnes_ui.core.fea.solver import require_solver; print(require_solver().describe())"
```

Note that the official Windows build prints **no version string** — only its usage
banner — so `probe_solver` falls back to reading the version from the install directory
name and says so in its notes. Rename the directory and the version becomes a guess. The
raw banner is archived with every run regardless, so the run record never depends on
that inference.

---

## 6. What it does not fix

Installing CalculiX does not give this project viscoelasticity. CalculiX has none —
established against the manual in
[03-solver-comparison.md](03-solver-comparison.md#viscoelasticity--resolved-and-the-answer-is-no).
TPU genuinely creeps, relaxes, shows hysteresis and takes a permanent set, and none of
that can be modelled with this solver at any version. Every result remains purely
hyperelastic and says so on its face.

Nor does it supply material parameters. The provisional 12 MPa placeholder is still a
placeholder, and every force computed from it is still tagged
`UNVALIDATED_ASSUMPTION` no matter how converged the solve. A better solver does not
improve a guessed input; see [06-required-inputs.md](06-required-inputs.md) item 7.
