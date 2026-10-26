"""Running CalculiX and archiving everything the run produced.

Every run leaves a durable, inspectable record, as specified in
``docs/03-solver-comparison.md``:

    runs/<run-id>/
        input.inp       the deck exactly as submitted
        solver.log      full stdout and stderr
        results.frd     raw solver output
        results.dat     printed reactions
        manifest.json   mesh, material, settings, solver version, timing

The working directory is created outside the project tree. This repository lives under
a OneDrive-synced folder, and a solver writing thousands of intermediate files into a
synced directory produces lock contention and conflict copies; only the final artefacts
are copied back.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from ..material.models import HyperelasticModel
from .meshing import Mesh
from .results import FeaResult, parse_convergence, parse_dat_reactions, parse_frd_displacements
from .solver import SolverInfo, SolverNotAvailableError, installation_instructions

logger = logging.getLogger(__name__)

__all__ = ["run_analysis", "RunError"]


class RunError(RuntimeError):
    """The solver run could not be carried out."""


def run_analysis(
    deck_text: str,
    mesh: Mesh,
    material: HyperelasticModel,
    solver: SolverInfo | None,
    archive_directory: Path | str | None = None,
    timeout: float = 3600.0,
    progress: Callable[[float, str], None] | None = None,
    cancellation=None,
) -> FeaResult:
    """Submit a deck to CalculiX and parse what comes back.

    Raises :class:`SolverNotAvailableError` when ``solver`` is ``None``. It does not
    substitute anything: the application never presents a reduced-order result where an
    FEA result was requested.
    """
    if solver is None:
        raise SolverNotAvailableError(installation_instructions())

    run_id = uuid.uuid4().hex[:12]
    scratch = Path(tempfile.mkdtemp(prefix=f"barnes_ccx_{run_id}_"))
    job = "job"
    deck_path = scratch / f"{job}.inp"
    deck_path.write_text(deck_text, encoding="utf-8")

    if progress:
        progress(0.05, "Submitting to CalculiX...")

    started = time.perf_counter()
    try:
        # "-i jobname", not a bare job name. The official Windows build's own usage
        # banner is "Usage: CalculiX.exe -i jobname", and invoking it without -i makes
        # it print that banner and exit 0 without solving anything -- which would have
        # looked like a successful run producing no results.
        completed = subprocess.run(
            [str(solver.executable), "-i", job],
            cwd=str(scratch),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        log_text = (completed.stdout or "") + "\n" + (completed.stderr or "")
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        log_text = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        raise RunError(
            f"CalculiX exceeded the {timeout:.0f} s time limit. The run directory was "
            f"left at {scratch} for inspection."
        ) from exc
    except OSError as exc:
        raise RunError(f"CalculiX could not be started: {exc}") from exc

    elapsed = time.perf_counter() - started
    if progress:
        progress(0.8, "Parsing results...")

    convergence = parse_convergence(log_text)
    if exit_code != 0 and convergence.converged:
        # Trust the exit code over the log heuristic: a non-zero exit with no detected
        # error means the log parse missed something, and the safe reading is failure.
        convergence.converged = False
        convergence.errors.append(
            f"Solver exited with code {exit_code} despite no error text in the log."
        )

    result = FeaResult(
        convergence=convergence,
        reaction_forces=parse_dat_reactions(scratch / f"{job}.dat"),
        displacements=parse_frd_displacements(scratch / f"{job}.frd"),
        mesh_description=mesh.describe(),
        material_provenance=material.provenance,
        material_caveats=tuple(material.caveats),
    )
    result.notes.append(f"Solved in {elapsed:.1f} s; {convergence.summary}.")

    archive = _archive(
        scratch, job, deck_text, log_text, archive_directory, run_id,
        mesh, material, solver, elapsed, convergence.converged,
    )
    result.run_directory = archive

    if progress:
        progress(1.0, convergence.summary)

    if not convergence.converged:
        logger.warning("Run %s did not converge: %s", run_id, convergence.summary)
    return result


def _archive(
    scratch: Path,
    job: str,
    deck_text: str,
    log_text: str,
    archive_directory: Path | str | None,
    run_id: str,
    mesh: Mesh,
    material: HyperelasticModel,
    solver: SolverInfo,
    elapsed: float,
    converged: bool,
) -> Path:
    """Copy the durable artefacts out of scratch, including for a failed run.

    A failed run is archived too. Its log is the only thing that makes the failure
    diagnosable, and discarding it would make convergence problems impossible to chase.
    """
    if archive_directory is None:
        archive_directory = Path(tempfile.gettempdir()) / "barnes_ui_runs"
    destination = Path(archive_directory) / run_id
    destination.mkdir(parents=True, exist_ok=True)

    (destination / "input.inp").write_text(deck_text, encoding="utf-8")
    (destination / "solver.log").write_text(log_text, encoding="utf-8")

    for suffix in (".frd", ".dat", ".sta", ".cvg"):
        source = scratch / f"{job}{suffix}"
        if source.is_file():
            try:
                shutil.copy2(source, destination / f"results{suffix}")
            except OSError as exc:  # pragma: no cover
                logger.warning("Could not archive %s: %s", source, exc)

    manifest = {
        "run_id": run_id,
        "converged": converged,
        "elapsed_seconds": round(elapsed, 3),
        "solver": {
            "executable": str(solver.executable),
            "version": solver.version,
            "banner": solver.banner,
        },
        "mesh": {
            "description": mesh.describe(),
            "element_type": mesh.calculix_element_type,
            "element_count": mesh.element_count,
            "node_count": mesh.node_count,
            "element_size_mm": mesh.element_size,
            "quality": mesh.quality,
        },
        "material": {
            "description": material.describe(),
            "kind": material.kind.label,
            "parameters": list(material.parameters),
            "poisson_ratio": material.poisson_ratio,
            "provenance": material.provenance.label,
            "caveats": [c.message for c in material.caveats],
            "calibration_strain_range": material.calibration_strain_range,
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    try:
        shutil.rmtree(scratch, ignore_errors=True)
    except OSError:  # pragma: no cover
        pass

    logger.info("Archived run %s to %s", run_id, destination)
    return destination
