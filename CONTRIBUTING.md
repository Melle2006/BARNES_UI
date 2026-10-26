# Contributing

Read this before your first commit. It is short, and the commit-message section in particular is
a hard requirement rather than a style preference.

---

## Commit messages

**Commit messages on this project are long and explanatory. This is deliberate.**

People working on this project may not have AI tooling available. The git history and the
documentation are their only means of understanding why the code is the way it is. A commit
message reading `fix bug` destroys information that cannot be recovered, because the reasoning
existed only in the head of whoever wrote it.

Write the message you would want to find in `git blame` eighteen months from now, when the person
reading it is you and you have forgotten everything.

### Format

```
Short imperative subject line, under 72 characters

What changed, in prose. Not a list of files -- the diff already lists the
files. Describe the behaviour that is different now.

Why it changed. The motivation, the bug being fixed, the requirement being
met. This is the part that cannot be reconstructed from the diff and is the
single most valuable thing in the message.

What else was considered and rejected, and why. This is what stops the next
person reopening a settled decision, or re-making a mistake that was already
made and reverted once.

Anything a reader needs to know to continue: follow-up work, limitations,
assumptions introduced, things that were verified and how.
```

### Rules

- **Subject line:** imperative mood ("Add", "Fix", "Rework"), not past tense. Under 72
  characters. No trailing full stop.
- **Blank line** after the subject. Always.
- **Body wrapped at 79 characters** so it reads properly in a terminal.
- **Explain the why, not just the what.** If the body only restates the diff, it is not finished.
- **Record rejected alternatives.** "Considered X, rejected because Y" is often the most useful
  sentence in the whole message.
- **State what was verified and how.** "Volume matches the analytical value of 720.876 mm^3" is
  worth far more than "tested".
- **No AI attribution.** No `Co-Authored-By` trailers for AI tools, no "generated with" lines.
  The repository is human-authored work.

### Good

```
Merge coincident vertices when loading STL files

STL imports were reporting a 12-triangle box as 12 separate bodies. The
loader called trimesh.load_mesh with process=False, intending to avoid any
silent modification of the geometry.

That was the wrong call for this format. STL stores every triangle with its
own copy of each corner vertex, so without merging, no two triangles share a
vertex. Connected-component splitting then finds no connections and returns
one component per triangle, and the watertightness test is meaningless for the
same reason.

process=True merges coincident vertices. No vertex moves, so the geometry is
unchanged -- only the topology, which is the thing that was missing. The
trade-off is that trimesh also drops degenerate and duplicate faces, which is
acceptable and arguably desirable for a file we are only going to display.

Verified against a generated 10x20x3 box: now one body, 12 triangles, 600 mm^3,
reported watertight. Covered by test_display_mesh_is_cached_by_the_loader.
```

### Bad

```
fix stl
```

```
Update stl.py

Changed process to True.
```

The second is worse than it looks: it says what the diff already says and omits the only thing a
reader actually needs, which is why.

---

## Code standards

### The one architectural rule

**`barnes_ui.core` must never import PySide6, PyVista, VTK or Matplotlib.**

Engineering code stays independent of the interface. This keeps the physics testable without a
display, keeps the test suite fast, and means a UI change cannot break a calculation.
`tests/test_architecture.py` enforces it by scanning the import graph, so breaking the rule fails
the build rather than merely disappointing someone.

### Style

- Type hints on public functions.
- Docstrings that explain *why*, not just what. The code already says what.
- `from __future__ import annotations` at the top of every module.
- Four-space indent, 88-character soft limit.
- `snake_case` for functions, `PascalCase` for classes, `_leading_underscore` for private.

### Comments

Comment the surprising, not the obvious.

```python
# Bad -- restates the code
# increment the counter
counter += 1

# Good -- explains a non-obvious decision
# useShapeTolerance=False: setting it True pads every face by its modelling
# tolerance, which reported a 10 mm box as 10.0000002 mm. Harmless for a clash
# check, wrong for a reported dimension.
```

If a line took you ten minutes to get right, leave a note saying why, or the next person spends
the same ten minutes.

### Units

- Canonical internal units are **mm, N, MPa, radians**. Convert only at the boundaries.
- Every value shown to a user carries its unit. No exceptions.
- Degrees exist only at the UI boundary; no calculation sees one.

### Provenance

Any new calculated quantity must carry a `Provenance` tag. If you add a mechanics routine, its
output is tagged, its assumptions are registered as `Caveat`s, and those caveats survive into the
exports. See `core/provenance.py` — the module docstring explains the reasoning.

### Never do these

- Return a fabricated number when the real computation is unavailable.
- Fall back silently from a requested method to a weaker one.
- Present a reduced-order result as FEA, or an animation as proof of convergence.
- Synthesise hyperelastic coefficients from a hardness rating.
- Ship a placeholder calculation described as working. Label it not-implemented and say what the
  next concrete step is.

---

## Tests

- New code comes with tests **in the same commit**.
- Prefer generated fixtures with exactly known properties over committed binary files. A 10×20×3
  box has a volume of 600 mm³ and nothing has to be taken on trust. See `tests/conftest.py`.
- Assert against analytically known values, not against previously recorded output. A golden
  value nobody can derive is a golden value nobody can check.
- Tests must pass headless.

Run before pushing:

```bash
pytest
```

---

## Adding a dependency

1. Add it to `pyproject.toml` **with a comment** saying what it does and what was considered
   instead.
2. Regenerate the lock file: `pip freeze --exclude-editable > requirements.lock.txt`
3. Verify it imports on Windows. Resolving is not the same as working — PySide6 6.12.0 installed
   cleanly and then failed at import.
4. Explain the choice in the commit message.

---

## Adding a CAD format

1. New module in `core/cad/loaders/`.
2. Add the extension and exactness flag to `CadFormat` in `core/cad/model.py`. Be honest about
   `is_exact`: a tessellated format must be marked inexact, which is what keeps it out of the
   mechanics modules.
3. Register it in `core/cad/registry.py::_loader_for`.
4. Tests covering: a successful load, a corrupt file, unit detection or the absence of it, and
   the analysis-readiness outcome.
5. Error messages must say what the user should *do*, not just what failed.

---

## Documentation

When a change invalidates something in `docs/`, update it in the same commit. Documentation that
contradicts the code is worse than no documentation, because it is believed.

Specifically:

- A new assumption goes in the risk register.
- A verified solver capability replaces its "unverified" note in the solver comparison.
- A completed phase gets its acceptance criteria checked off in the development plan, with the
  measured numbers recorded.
