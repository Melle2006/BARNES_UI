"""BREP import.

BREP is OpenCASCADE's native serialisation. It round-trips exactly, which makes it the
right format for the application's own intermediate files -- a flexure regenerated in
Phase 4, for instance, is stored as BREP rather than re-exported through STEP.

It carries no unit declaration at all. The convention throughout OpenCASCADE is that
BREP coordinates are millimetres, and the application follows that convention while
flagging the unit as assumed, because a convention is not a declaration.
"""

from __future__ import annotations

from pathlib import Path

from ...units import LengthUnit, UnitConfidence
from .._occ import occ, require_kernel, static
from ..inspect import inspect_shape
from ..model import CadFormat, GeometryModel, WarningSeverity
from .errors import GeometryLoadError
from .step import _add_structural_warnings

__all__ = ["load_brep"]


def load_brep(path: Path) -> GeometryModel:
    """Load an OpenCASCADE BREP file."""
    require_kernel()
    path = Path(path)
    if not path.is_file():
        raise GeometryLoadError(f"File not found: {path}")

    shape = occ.TopoDS_Shape()
    builder = occ.BRep_Builder()
    try:
        ok = static(occ.BRepTools, "Read")(shape, str(path), builder)
    except Exception as exc:
        raise GeometryLoadError(f"The BREP file could not be read: {exc}") from exc

    if not ok or shape.IsNull():
        raise GeometryLoadError(
            "The BREP file could not be read. BREP is version-sensitive: a file "
            "written by a much newer OpenCASCADE release may not load here."
        )

    model = GeometryModel(
        source_path=path,
        source_format=CadFormat.BREP,
        unit=LengthUnit.MILLIMETRE,
        # A convention, not a declaration. The distinction is the whole point of
        # UnitConfidence.
        unit_confidence=UnitConfidence.ASSUMED,
        solids=inspect_shape(shape),
    )

    model.add_warning(
        WarningSeverity.CAUTION,
        "BREP carries no unit declaration",
        "Millimetres were assumed, following the OpenCASCADE convention. Confirm the "
        "unit before relying on any dimension.",
    )

    _add_structural_warnings(model, len(model.solids))
    return model
