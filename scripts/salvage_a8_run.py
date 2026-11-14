"""Post-process an A8 run whose solver was interrupted, without solving again.

    python scripts/salvage_a8_run.py RUN_DIR LABEL --groups iteration3_r2 --out results/iteration3/a8

A container restart stops CalculiX part-way, but its scratch directory keeps the
deck (job.inp), the reaction history (job.dat) and the fields (job.frd) up to the last
converged increment. This rebuilds the model exactly as a8_meander_study.py would
(geometry and gmsh meshing are deterministic), checks that the rebuilt mesh has the
same element and node counts as the archived deck, and runs the study's own
post-processing on the existing files. The record is marked as salvaged and not
converged, and reports the angle the solver reached.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]

import a8_meander_study as A  # noqa: E402


def mesh_line(text):
    m = re.search(r"\*\* Mesh: (\d+) C3D10 elements, (\d+) nodes", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("label")
    ap.add_argument("--groups", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--finger", default="iteration3")
    a = ap.parse_args()
    old_deck = (a.run_dir / "job.inp").read_text(errors="replace")
    want = mesh_line(old_deck)
    sta = (a.run_dir / "job.sta").read_text().splitlines()
    rows = [r.split() for r in sta if re.match(r"\s*1\s+\d+\s+\d+U?\s", r)]
    increments = max(int(r[1]) for r in rows)
    cutbacks = sum(1 for r in rows if r[2].endswith("U"))

    def fake_run(deck, mesh, material, solver, archive_directory=None, timeout=None):
        got = mesh_line(deck)
        if got != want:
            raise RuntimeError(f"rebuilt mesh {got} does not match the interrupted run's {want}")
        arch = Path(archive_directory) / f"salvaged_{a.run_dir.name}"
        arch.mkdir(parents=True, exist_ok=True)
        shutil.copy(a.run_dir / "job.dat", arch / "results.dat")
        (arch / "results.frd").unlink(missing_ok=True)
        (arch / "results.frd").symlink_to(a.run_dir / "job.frd")
        conv = SimpleNamespace(converged=False, increments_completed=increments, cutbacks=cutbacks,
                               summary=f"salvaged after the solver was stopped at increment {increments} "
                                       f"({cutbacks} cutbacks)")
        return SimpleNamespace(run_directory=arch, convergence=conv)

    A.run_analysis = fake_run
    A.KEEP_FRD = True                     # the .frd belongs to the interrupted run; leave it
    argv = ["--finger", a.finger, "--groups", a.groups, "--only", a.label, "--out", str(a.out),
            "--archive", str(a.run_dir.parent / "salvage_arch")]
    claim = a.out / "cases" / f"{a.label}.claim"
    claim.unlink(missing_ok=True)
    A.main(argv)
    rec_path = a.out / "cases" / f"{a.label}.json"
    rec = json.loads(rec_path.read_text())
    rec["salvaged_from"] = str(a.run_dir)
    rec_path.write_text(json.dumps(rec, indent=2))
    print("salvaged", a.label, "reached", rec.get("reached_deg"), "T90", (rec.get("torque_n_mm") or {}).get("90"))


if __name__ == "__main__":
    main()
