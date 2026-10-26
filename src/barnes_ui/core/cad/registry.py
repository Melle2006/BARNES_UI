"""Format detection and loader dispatch.

The single entry point for importing CAD into the application. Callers use
:func:`load_geometry` and never import a loader directly, so adding a format means
registering it here and nothing else changes.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from .model import CadFormat, GeometryModel
from .loaders.errors import (
    CadError,
    GeometryLoadError,
    KernelUnavailableError,
    UnsupportedFormatError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "load_geometry",
    "supported_extensions",
    "file_dialog_filter",
    "native_solidworks_advice",
]


def _loader_for(fmt: CadFormat) -> Callable[[Path], GeometryModel]:
    """Return the loader for a format.

    Imports are deferred to call time so that loading an STL does not pay the cost of
    importing the CAD kernel, and so that a missing optional dependency only breaks
    the format that needs it.
    """
    if fmt is CadFormat.STEP:
        from .loaders.step import load_step
        return load_step
    if fmt is CadFormat.IGES:
        from .loaders.iges import load_iges
        return load_iges
    if fmt is CadFormat.BREP:
        from .loaders.brep import load_brep
        return load_brep
    if fmt is CadFormat.STL:
        from .loaders.stl import load_stl
        return load_stl
    if fmt is CadFormat.DXF:
        from .loaders.dxf import load_dxf
        return load_dxf
    raise UnsupportedFormatError(f"No loader registered for {fmt}")  # pragma: no cover


#: Native SolidWorks extensions, recognised solely in order to give a useful error.
_NATIVE_SOLIDWORKS = {".sldprt", ".sldasm", ".slddrw"}


def native_solidworks_advice(path: Path) -> str:
    """The message shown when someone tries to open a native SolidWorks file.

    Worth its own function because this will be the single most common mistake, and
    the answer needs to be concrete rather than "unsupported format". See
    ``docs/01-feasibility-assessment.md`` for why no open-source reader can do this.
    """
    kind = "assembly" if path.suffix.lower() == ".sldasm" else "part"
    extra = (
        "\n   - Tick 'Save all components as a single file' so that component "
        "placement is preserved."
        if kind == "assembly"
        else ""
    )
    return (
        f"'{path.name}' is a native SolidWorks {kind} file, which cannot be read "
        "without SolidWorks itself. No open-source library can import these with "
        "their parametric history, and anything claiming otherwise is only reading "
        "the embedded preview mesh.\n\n"
        "To use this file here:\n"
        "   1. Open it in SolidWorks.\n"
        "   2. File > Save As.\n"
        f"   3. Choose 'STEP AP214 (*.step)'.{extra}\n"
        "   4. Import the resulting .step file.\n\n"
        "STEP carries exact geometry, so nothing needed for analysis is lost."
    )


def load_geometry(path: Path | str) -> GeometryModel:
    """Import a CAD file, dispatching on its extension.

    Raises
    ------
    UnsupportedFormatError
        The extension is not handled. Native SolidWorks files get a specific message
        explaining the export route.
    GeometryLoadError
        The file could not be read.
    KernelUnavailableError
        A B-rep format was requested but the CAD kernel is not installed.
    """
    path = Path(path)

    if not path.exists():
        raise GeometryLoadError(f"File not found: {path}")
    if not path.is_file():
        raise GeometryLoadError(f"Not a file: {path}")

    suffix = path.suffix.lower()
    if suffix in _NATIVE_SOLIDWORKS:
        raise UnsupportedFormatError(native_solidworks_advice(path))

    try:
        fmt = CadFormat.from_path(path)
    except ValueError as exc:
        raise UnsupportedFormatError(
            f"{exc}\n\nIf this came from SolidWorks, export it as STEP AP214."
        ) from exc

    loader = _loader_for(fmt)

    started = time.perf_counter()
    logger.info("Importing %s as %s", path.name, fmt.label)
    try:
        model = loader(path)
    except CadError:
        raise  # already carries an actionable message
    except RuntimeError as exc:
        # require_kernel() raises RuntimeError with installation instructions.
        if "OpenCASCADE" in str(exc):
            raise KernelUnavailableError(str(exc)) from exc
        raise GeometryLoadError(f"Import of {path.name} failed: {exc}") from exc
    except Exception as exc:
        # Anything unexpected is wrapped so the GUI always gets a CadError, but the
        # original traceback is preserved for the log.
        logger.exception("Unexpected failure importing %s", path)
        raise GeometryLoadError(
            f"Import of {path.name} failed unexpectedly: {exc}\n\n"
            "The application log has the full traceback."
        ) from exc

    elapsed = time.perf_counter() - started
    logger.info(
        "Imported %s in %.2f s: %d solid(s), %.4g mm^3 total",
        path.name, elapsed, model.solid_count, model.total_volume,
    )
    model.loader_notes.append(f"Imported in {elapsed:.2f} s.")
    return model


def supported_extensions() -> tuple[str, ...]:
    return CadFormat.all_extensions()


def file_dialog_filter() -> str:
    """Qt file-dialog filter string.

    Built here rather than in the GUI so that the list of formats has exactly one
    source of truth. Native SolidWorks extensions are included on purpose: letting the
    user select one and then showing the export instructions is far more helpful than
    hiding the file and leaving them wondering why it is not listed.
    """
    all_exts = " ".join(f"*{e}" for e in supported_extensions())
    parts = [f"All supported CAD files ({all_exts})"]
    for fmt in CadFormat:
        exts = " ".join(f"*{e}" for e in fmt.extensions)
        parts.append(f"{fmt.label} ({exts})")
    parts.append("SolidWorks native - shows export instructions (*.sldprt *.sldasm)")
    parts.append("All files (*)")
    return ";;".join(parts)
