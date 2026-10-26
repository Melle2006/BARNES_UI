"""DXF import, for 2D profiles and sketches.

DXF is a 2D format and is handled differently from the solid formats: there are no
bodies, no volume, and nothing to tessellate. What it provides is planar curves, which
matter for this project because a flexure's cross-section or centreline path may be
authored as a sketch, and importing that sketch directly is more accurate than
reconstructing it from a solid.

Phase 1 reads the curves, reports extents and entity counts, and draws them. Turning a
DXF profile into a parametric flexure template is Phase 4 work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ...units import LengthUnit, UnitConfidence
from ..model import BoundingBox, CadFormat, GeometryModel, WarningSeverity
from .errors import GeometryLoadError

logger = logging.getLogger(__name__)

__all__ = ["load_dxf", "CurveSet"]


# AutoCAD's $INSUNITS header variable. Frequently left at 0 ("unitless"), which is why
# a value here is treated as a hint rather than as a declaration.
_INSUNITS_TO_UNIT = {
    1: LengthUnit.INCH,
    2: LengthUnit.FOOT,
    4: LengthUnit.MILLIMETRE,
    5: LengthUnit.CENTIMETRE,
    6: LengthUnit.METRE,
    8: LengthUnit.MIL,
    13: LengthUnit.NANOMETRE,
}

#: Number of straight segments used to approximate a full circle when flattening arcs
#: and splines for display. 72 gives half-degree resolution, visually smooth at any
#: sensible zoom. Display only -- no measurement is taken from these points.
_ARC_SEGMENTS = 72


@dataclass
class CurveSet:
    """Planar curves recovered from a DXF, flattened to polylines for display.

    Each entry in ``polylines`` is an (N, 3) array of points. Curved entities are
    approximated; the original entity type is kept in ``entity_counts`` so the user
    can see what was approximated.
    """

    polylines: list[np.ndarray] = field(default_factory=list)
    entity_counts: dict[str, int] = field(default_factory=dict)

    @property
    def point_count(self) -> int:
        return sum(int(p.shape[0]) for p in self.polylines)

    def bounds(self) -> BoundingBox | None:
        if not self.polylines:
            return None
        stacked = np.vstack(self.polylines)
        lo = stacked.min(axis=0)
        hi = stacked.max(axis=0)
        return BoundingBox(
            float(lo[0]), float(lo[1]), float(lo[2]),
            float(hi[0]), float(hi[1]), float(hi[2]),
        )


def load_dxf(path: Path) -> GeometryModel:
    """Load 2D curves from a DXF file."""
    path = Path(path)
    if not path.is_file():
        raise GeometryLoadError(f"File not found: {path}")

    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise GeometryLoadError(
            "The 'ezdxf' package is required to read DXF files. "
            "Install it with: pip install ezdxf"
        ) from exc

    try:
        document = ezdxf.readfile(str(path))
    except Exception as exc:
        raise GeometryLoadError(
            f"The DXF file could not be read: {exc}\n\n"
            "If it was produced by an unusual exporter, try saving it as DXF R2010 "
            "or later."
        ) from exc

    declared = _declared_unit(document)
    curves = _extract_curves(document.modelspace())

    model = GeometryModel(
        source_path=path,
        source_format=CadFormat.DXF,
        unit=declared or LengthUnit.MILLIMETRE,
        # $INSUNITS is unreliable in practice, so even when present it is treated as a
        # hint that still wants confirmation.
        unit_confidence=UnitConfidence.ASSUMED,
        declared_unit=declared,
        curves=curves,
    )

    model.add_warning(
        WarningSeverity.BLOCKING,
        "DXF contains 2D curves, not solids",
        "A DXF has no volume and cannot be analysed structurally on its own. It is "
        "useful as a profile or centreline definition, which Phase 4 will consume. "
        "For stiffness analysis, import the 3D part as STEP.",
    )

    if declared:
        model.loader_notes.append(
            f"$INSUNITS suggests {declared.symbol}, which DXF exporters often set "
            "incorrectly. Treat as a hint and confirm."
        )
    else:
        model.add_warning(
            WarningSeverity.CAUTION,
            "DXF declares no units",
            "The $INSUNITS header variable is absent or set to 'unitless'. "
            "Millimetres were assumed.",
        )

    if not curves.polylines:
        model.add_warning(
            WarningSeverity.BLOCKING,
            "No drawable curves found",
            "The model space contains no lines, arcs, circles, polylines or splines. "
            "If the geometry is inside a block or on a frozen layer, explode or "
            "unfreeze it before exporting.",
        )

    summary = ", ".join(f"{n}x {k}" for k, n in sorted(curves.entity_counts.items()))
    model.loader_notes.append(f"Entities read: {summary or 'none'}.")
    return model


def _declared_unit(document) -> LengthUnit | None:
    try:
        code = int(document.header.get("$INSUNITS", 0))
    except Exception:  # pragma: no cover - malformed header
        return None
    return _INSUNITS_TO_UNIT.get(code)


def _extract_curves(modelspace) -> CurveSet:
    """Flatten supported DXF entities into polylines.

    Unsupported entity types are counted but not drawn, and the count is reported, so
    that a drawing which came through half-empty is obvious rather than mysterious.
    """
    curves = CurveSet()

    for entity in modelspace:
        kind = entity.dxftype()
        curves.entity_counts[kind] = curves.entity_counts.get(kind, 0) + 1
        try:
            points = _entity_to_points(entity, kind)
        except Exception as exc:  # pragma: no cover - defensive per-entity guard
            logger.debug("Could not flatten %s: %s", kind, exc)
            continue
        if points is not None and len(points) >= 2:
            curves.polylines.append(np.asarray(points, dtype=np.float64))

    return curves


def _entity_to_points(entity, kind: str) -> list[tuple[float, float, float]] | None:
    """Convert one entity to a list of points, or None if it is not drawable."""
    if kind == "LINE":
        start, end = entity.dxf.start, entity.dxf.end
        return [(start.x, start.y, start.z), (end.x, end.y, end.z)]

    if kind == "CIRCLE":
        return _arc_points(
            entity.dxf.center, entity.dxf.radius, 0.0, 360.0
        )

    if kind == "ARC":
        return _arc_points(
            entity.dxf.center,
            entity.dxf.radius,
            entity.dxf.start_angle,
            entity.dxf.end_angle,
        )

    if kind == "LWPOLYLINE":
        points = [(p[0], p[1], entity.dxf.elevation) for p in entity.get_points()]
        if entity.closed and points:
            points.append(points[0])
        return points

    if kind == "POLYLINE":
        points = [(v.dxf.location.x, v.dxf.location.y, v.dxf.location.z)
                  for v in entity.vertices]
        if entity.is_closed and points:
            points.append(points[0])
        return points

    if kind == "SPLINE":
        # flattening() yields points within a distance tolerance of the true curve.
        return [(p.x, p.y, p.z) for p in entity.flattening(0.01)]

    if kind in ("ELLIPSE",):
        return [(p.x, p.y, p.z) for p in entity.flattening(0.01)]

    return None


def _arc_points(
    centre, radius: float, start_deg: float, end_deg: float
) -> list[tuple[float, float, float]]:
    """Sample an arc or circle into points.

    DXF arcs run counter-clockwise from start to end, so a sweep that comes out
    negative is wrapped by 360 degrees rather than being drawn backwards.
    """
    sweep = end_deg - start_deg
    if sweep <= 0:
        sweep += 360.0
    count = max(2, int(_ARC_SEGMENTS * sweep / 360.0) + 1)
    angles = np.radians(np.linspace(start_deg, start_deg + sweep, count))
    return [
        (centre.x + radius * float(np.cos(a)),
         centre.y + radius * float(np.sin(a)),
         centre.z)
        for a in angles
    ]
