"""IGES import.

IGES is supported because older CAD exchanges still use it, but STEP is preferred and
the loader says so. IGES is a surface-oriented format: many exports contain unsewn
faces rather than closed solids, which is fine for viewing and useless for structural
analysis. The loader attempts to sew the surfaces into solids and reports honestly
when that does not succeed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ...units import LengthUnit, UnitConfidence
from .._occ import occ, require_kernel, static
from ..inspect import inspect_shape
from ..model import CadFormat, GeometryModel, WarningSeverity
from .errors import GeometryLoadError
from .step import _add_structural_warnings

logger = logging.getLogger(__name__)

__all__ = ["load_iges"]


# IGES stores its unit as a code in the Global section, field 14. 2 = inch, 6 = mm.
_IGES_UNIT_CODES = {
    1: LengthUnit.INCH,
    2: LengthUnit.MILLIMETRE,
    4: LengthUnit.FOOT,
    5: LengthUnit.MIL,
    6: LengthUnit.METRE,
    7: LengthUnit.KILOMETRE,
    8: LengthUnit.MIL,
    9: LengthUnit.MICROMETRE,
    10: LengthUnit.CENTIMETRE,
    11: LengthUnit.MICROMETRE,
}

_IGES_UNIT_NAME_RE = re.compile(r"\b(MM|IN|INCH|M|CM|FT|MIL|UM)\b", re.IGNORECASE)


def _parse_declared_unit(path: Path) -> LengthUnit | None:
    """Best-effort read of the IGES Global section unit.

    IGES's global section is comma-delimited with Hollerith-encoded strings, which is
    awkward to parse properly. Since OpenCASCADE converts to mm on read anyway, the
    declared unit here is informational only, so a best-effort scan for the unit name
    string (field 15) is adequate. ``None`` is returned rather than a guess when the
    scan finds nothing.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            global_section = "".join(
                line for line in handle if len(line) > 72 and line[72] == "G"
            )
    except OSError as exc:
        logger.warning("Could not read %s to detect units: %s", path, exc)
        return None

    if not global_section:
        return None

    # Hollerith strings look like "2HMM". Find them and test against known names.
    for match in re.finditer(r"(\d+)H([^,;]*)", global_section):
        length = int(match.group(1))
        text = match.group(2)[:length]
        name_match = _IGES_UNIT_NAME_RE.fullmatch(text.strip())
        if name_match:
            try:
                return LengthUnit.from_symbol(name_match.group(1))
            except ValueError:
                continue
    return None


def load_iges(path: Path) -> GeometryModel:
    """Load an IGES file into a :class:`GeometryModel`."""
    require_kernel()
    path = Path(path)
    if not path.is_file():
        raise GeometryLoadError(f"File not found: {path}")

    declared = _parse_declared_unit(path)

    static(occ.Interface_Static, "SetCVal")("xstep.cascade.unit", "MM")

    reader = occ.IGESControl_Reader()
    try:
        status = reader.ReadFile(str(path))
    except Exception as exc:
        raise GeometryLoadError(f"The IGES file could not be parsed: {exc}") from exc

    if status != occ.IFSelect_ReturnStatus.IFSelect_RetDone:
        raise GeometryLoadError(
            f"The IGES file could not be read (reader status: {status}).\n\n"
            "Consider re-exporting as STEP AP214, which is better supported and "
            "carries solid bodies rather than loose surfaces."
        )

    try:
        reader.TransferRoots()
        shape = reader.OneShape()
    except Exception as exc:
        raise GeometryLoadError(
            f"The IGES geometry could not be transferred: {exc}"
        ) from exc

    if shape is None or shape.IsNull():
        raise GeometryLoadError("The IGES file transferred an empty shape.")

    solids = inspect_shape(shape)

    model = GeometryModel(
        source_path=path,
        source_format=CadFormat.IGES,
        unit=LengthUnit.MILLIMETRE,
        unit_confidence=UnitConfidence.DECLARED if declared else UnitConfidence.ASSUMED,
        solids=solids,
        declared_unit=declared,
    )

    model.add_warning(
        WarningSeverity.CAUTION,
        "IGES is a lossy exchange format",
        "IGES carries surfaces rather than solids and loses assembly structure and "
        "component names. STEP AP214 is strongly preferred for anything that will be "
        "analysed.",
    )

    if not declared:
        model.add_warning(
            WarningSeverity.CAUTION,
            "Length unit not found in Global section",
            "Millimetres were assumed. Confirm before relying on any dimension.",
        )

    _add_structural_warnings(model, len(solids))
    return model
