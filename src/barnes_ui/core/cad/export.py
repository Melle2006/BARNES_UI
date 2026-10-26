"""Writing geometry back out to exchange formats.

Used for the generated reference parts, and from Phase 4 for adapted flexures and
modified assemblies.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ._occ import occ, require_kernel, static

logger = logging.getLogger(__name__)

__all__ = ["write_step", "write_brep", "ExportError"]


class ExportError(RuntimeError):
    """Geometry could not be written."""


def write_step(shape: Any, path: Path | str, unit: str = "MM") -> Path:
    """Write a shape as STEP AP214.

    The length unit is set explicitly rather than inherited from whatever the process
    last happened to set. A file written under a unit the author did not intend is the
    same class of bug as the import-side one that cost this project a debugging session,
    and it is avoided the same way: state the unit at the boundary rather than rely on a
    default.
    """
    require_kernel()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    static(occ.Interface_Static, "SetCVal")("write.step.unit", unit)

    writer = occ.STEPControl_Writer()
    status = writer.Transfer(
        shape, occ.STEPControl_StepModelType.STEPControl_AsIs
    )
    if status != occ.IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ExportError(f"Could not transfer the shape for STEP export: {status}")

    if writer.Write(str(path)) != occ.IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ExportError(f"Could not write {path}.")

    logger.info("Wrote STEP to %s (%d bytes)", path, path.stat().st_size)
    return path


def write_brep(shape: Any, path: Path | str) -> Path:
    """Write a shape as OpenCASCADE BREP.

    Round-trips exactly, so it is the right format for the application's own
    intermediate files. It carries no unit declaration, which is why STEP is used for
    anything leaving the application.
    """
    require_kernel()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not static(occ.BRepTools, "Write")(shape, str(path)):
        raise ExportError(f"Could not write {path}.")

    logger.info("Wrote BREP to %s", path)
    return path
