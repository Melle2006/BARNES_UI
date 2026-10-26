"""STEP (ISO 10303) import.

STEP is the recommended format for this project. It carries exact B-rep geometry, it
declares its units, and SolidWorks exports it well. See
``docs/01-feasibility-assessment.md`` for why native ``.SLDPRT`` files are not an
option.

A note on units, because it is the subtlest thing in this file
--------------------------------------------------------------

A STEP file declares its length unit in the header, in an entity that looks like::

    #346 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );

OpenCASCADE's reader *converts geometry to the target unit as it reads*, governed by
the ``xstep.cascade.unit`` parameter. This loader sets that parameter to ``MM``
explicitly rather than relying on the default.

The consequence is that after import, coordinates are in millimetres regardless of what
the file declared. The declared unit is still parsed and reported, because the user
should see whether their export came out in inches, but it must not be used to scale
anything -- that conversion has already happened. The two are kept in separate fields
on the model (``declared_unit`` and ``unit``) precisely so that nobody applies it twice.
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

logger = logging.getLogger(__name__)

__all__ = ["load_step", "parse_declared_unit"]


# Maps a STEP SI_UNIT prefix to the matching unit. The second element of SI_UNIT is
# always .METRE. for a length; the prefix is what distinguishes mm from m.
_SI_PREFIX_TO_UNIT = {
    "": LengthUnit.METRE,
    "MILLI": LengthUnit.MILLIMETRE,
    "CENTI": LengthUnit.CENTIMETRE,
    "DECI": LengthUnit.DECIMETRE,
    "MICRO": LengthUnit.MICROMETRE,
    "NANO": LengthUnit.NANOMETRE,
    "KILO": LengthUnit.KILOMETRE,
}

# Non-SI units appear as a CONVERSION_BASED_UNIT carrying a name string.
_CONVERSION_NAME_TO_UNIT = {
    "INCH": LengthUnit.INCH,
    "FOOT": LengthUnit.FOOT,
    "MIL": LengthUnit.MIL,
    "THOU": LengthUnit.MIL,
}

_SI_LENGTH_RE = re.compile(
    r"LENGTH_UNIT\s*\(\s*\).*?SI_UNIT\s*\(\s*\.?([A-Z]*)\.?\s*,\s*\.METRE\.\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_CONVERSION_RE = re.compile(
    r"CONVERSION_BASED_UNIT\s*\(\s*'([^']+)'", re.IGNORECASE
)


#: Size of each chunk read while scanning for the unit declaration.
_SCAN_CHUNK = 1 << 20  # 1 MiB

#: Overlap carried between chunks so a declaration straddling a boundary is still
#: matched. A LENGTH_UNIT entity is around 70 characters even when pretty-printed
#: across several lines, so 8 KiB is comfortably more than enough.
_SCAN_OVERLAP = 8192


def parse_declared_unit(path: Path) -> LengthUnit | None:
    """Read the length unit declared in a STEP file's data section.

    Returns ``None`` when no recognisable declaration is found, which is reported as a
    caution rather than being guessed at.

    This is a text scan rather than a call into the kernel, because OpenCASCADE applies
    the conversion internally and does not expose the original declaration in a
    convenient form.

    The scan covers the **whole file**, streamed in overlapping chunks so that memory
    use stays bounded regardless of file size.

    An earlier version read only the first 2 MB, on the assumption that unit entities
    appear near the start of the DATA section. That assumption is wrong and was caught
    by a real export: files written by OpenCASCADE's own STEP processor place the
    global unit context at the *end*, so a 2.27 MB part had its declaration at line
    51425 of 51430 and the unit came back undetected. The model was then flagged
    units-assumed and refused for analysis, despite the file stating millimetres
    perfectly clearly. Small test fixtures hid the bug because their declarations fell
    inside the window.

    Scanning the whole file costs a single sequential read, which is negligible beside
    the kernel's own parse of the same file.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            carry = ""
            while True:
                chunk = handle.read(_SCAN_CHUNK)
                if not chunk:
                    break
                window = carry + chunk
                unit = _match_unit(window)
                if unit is not None:
                    return unit
                carry = window[-_SCAN_OVERLAP:]
    except OSError as exc:
        logger.warning("Could not read %s to detect units: %s", path, exc)
        return None

    return None


def _match_unit(text: str) -> LengthUnit | None:
    """Find a length-unit declaration in a block of STEP text."""
    si_match = _SI_LENGTH_RE.search(text)
    if si_match:
        prefix = si_match.group(1).upper().strip(".")
        unit = _SI_PREFIX_TO_UNIT.get(prefix)
        if unit is not None:
            return unit
        logger.warning("Unrecognised SI prefix %r in STEP unit declaration.", prefix)

    # Fall back to a conversion-based unit, which is how inches are expressed.
    for name in _CONVERSION_RE.findall(text):
        unit = _CONVERSION_NAME_TO_UNIT.get(name.strip().upper())
        if unit is not None:
            return unit

    return None


def load_step(path: Path) -> GeometryModel:
    """Load a STEP file into a :class:`GeometryModel`.

    Raises :class:`GeometryLoadError` with an actionable message on failure. Problems
    that do not prevent the model being shown -- no solids, invalid topology,
    unreadable unit declaration -- are attached as warnings instead, because the user
    usually needs to look at the model to work out what went wrong with it.
    """
    require_kernel()
    path = Path(path)
    if not path.is_file():
        raise GeometryLoadError(f"File not found: {path}")

    declared = parse_declared_unit(path)

    # Force the reader's output unit. Without this the behaviour depends on whatever
    # the parameter was last set to in this process, which is a nasty source of
    # order-dependent bugs when several files are opened in one session.
    static(occ.Interface_Static, "SetCVal")("xstep.cascade.unit", "MM")

    reader = occ.STEPControl_Reader()
    try:
        status = reader.ReadFile(str(path))
    except Exception as exc:
        raise GeometryLoadError(
            f"The STEP file could not be parsed: {exc}\n\n"
            "If it was exported from SolidWorks, try re-exporting as STEP AP214."
        ) from exc

    if status != occ.IFSelect_ReturnStatus.IFSelect_RetDone:
        raise GeometryLoadError(
            f"The STEP file could not be read (reader status: {status}).\n\n"
            "The file may be truncated, corrupted, or not actually a STEP file. "
            "Re-export it from SolidWorks as STEP AP214."
        )

    root_count = reader.NbRootsForTransfer()
    if root_count == 0:
        raise GeometryLoadError(
            "The STEP file parsed correctly but contains no transferable geometry.\n\n"
            "This usually means the export contained only metadata, reference "
            "geometry or suppressed bodies. Check that the bodies are visible and "
            "unsuppressed before exporting."
        )

    try:
        reader.TransferRoots()
        shape = reader.OneShape()
    except Exception as exc:
        raise GeometryLoadError(
            f"The STEP geometry could not be transferred into the modelling kernel: "
            f"{exc}"
        ) from exc

    if shape is None or shape.IsNull():
        raise GeometryLoadError(
            "The STEP file transferred an empty shape. Nothing can be displayed or "
            "analysed."
        )

    solids = inspect_shape(shape)

    model = GeometryModel(
        source_path=path,
        source_format=CadFormat.STEP,
        # Geometry is in mm after the reader's conversion -- see the module docstring.
        unit=LengthUnit.MILLIMETRE,
        unit_confidence=(
            UnitConfidence.DECLARED if declared else UnitConfidence.ASSUMED
        ),
        solids=solids,
        declared_unit=declared,
    )

    if declared:
        model.loader_notes.append(
            f"File declares its length unit as {declared.symbol}. Geometry was "
            f"converted to mm on import."
        )
    else:
        model.add_warning(
            WarningSeverity.CAUTION,
            "Length unit not found in header",
            "No LENGTH_UNIT declaration could be located in the STEP header, so "
            "millimetres were assumed. Confirm the unit before relying on any "
            "dimension.",
        )

    model.loader_notes.append(f"Transferred {root_count} root entity/entities.")
    _add_structural_warnings(model, root_count)
    return model


def _add_structural_warnings(model: GeometryModel, root_count: int) -> None:
    """Attach warnings about things that are worth the user's attention.

    Deliberately separate from loading so that the same checks can be reused by the
    IGES and BREP loaders, and so that each condition can be tested on a hand-built
    model without touching a file.
    """
    if not model.solids:
        model.add_warning(
            WarningSeverity.BLOCKING,
            "No solid bodies",
            "The file contains no closed solids. It is probably a surface or "
            "wireframe export. Structural analysis needs a solid: in SolidWorks, "
            "check that the export includes solid bodies rather than surfaces.",
        )
        return

    for solid in model.solids:
        if not solid.is_valid:
            model.add_warning(
                WarningSeverity.BLOCKING,
                f"Invalid topology in {solid.name}",
                solid.validity_detail,
                solid_index=solid.index,
            )
        if solid.volume <= 0.0:
            model.add_warning(
                WarningSeverity.BLOCKING,
                f"Zero or negative volume in {solid.name}",
                "The body encloses no volume, so it cannot be meshed or analysed.",
                solid_index=solid.index,
            )

    if len(model.solids) > 1:
        model.add_warning(
            WarningSeverity.INFO,
            "Multiple disconnected solids",
            f"The file contains {len(model.solids)} separate bodies. If this was "
            "meant to be a single part, the export may have failed to merge them. "
            "If it is an assembly, that is expected.",
        )

    # A very thin body relative to its other dimensions is the signature of a flexure,
    # and also of a sliver that will be hard to mesh. Worth surfacing either way.
    for solid in model.solids:
        dx, dy, dz = solid.bounding_box.size
        extents = sorted((dx, dy, dz))
        if extents[0] > 0 and extents[2] / extents[0] > 200:
            model.add_warning(
                WarningSeverity.CAUTION,
                f"Very high aspect ratio in {solid.name}",
                f"Smallest extent {extents[0]:.4g} mm against largest "
                f"{extents[2]:.4g} mm (ratio {extents[2] / extents[0]:.0f}:1). Thin "
                "bodies need a carefully controlled mesh; expect to set element size "
                "manually in Phase 3.",
                solid_index=solid.index,
            )
