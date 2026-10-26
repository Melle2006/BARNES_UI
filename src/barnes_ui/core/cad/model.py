"""Data structures describing an imported CAD model.

These are plain dataclasses with no OpenCASCADE types in their public surface except
``SolidInfo.shape``, which is deliberately typed loosely so that this module can be
imported -- and the structures inspected and tested -- on a machine where the CAD
kernel is not installed. Only the loaders and the inspection routines actually touch
the kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Sequence

from ..units import LengthUnit, UnitConfidence

__all__ = [
    "CadFormat",
    "WarningSeverity",
    "GeometryWarning",
    "BoundingBox",
    "TopologyCounts",
    "SolidInfo",
    "GeometryModel",
]


class CadFormat(Enum):
    """Supported input formats, and whether they carry exact geometry.

    ``is_exact`` is the important column. A B-rep format keeps the real analytic
    surfaces, so a cylinder is a cylinder and its radius is a number in the file. A
    tessellated format has replaced that cylinder with triangles at whatever tolerance
    the exporter was set to, which means every curvature, arc length and bend radius
    derived from it is an approximation of unknown accuracy.

    Since the entire project is about geometry whose stiffness scales with the cube of
    a width, this distinction is tracked rather than glossed over.
    """

    STEP = ("STEP", (".step", ".stp"), True)
    IGES = ("IGES", (".iges", ".igs"), True)
    BREP = ("BREP", (".brep", ".brp"), True)
    STL = ("STL", (".stl",), False)
    DXF = ("DXF", (".dxf",), False)

    def __init__(self, label: str, extensions: tuple[str, ...], is_exact: bool) -> None:
        self.label = label
        self.extensions = extensions
        self.is_exact = is_exact

    @property
    def declares_units(self) -> bool:
        """Whether files of this format state their length unit.

        STEP and IGES both carry an explicit unit declaration in the header. BREP is an
        OpenCASCADE-native dump with no unit record. STL has none by design. DXF has an
        ``$INSUNITS`` header variable, but it is frequently left unset or wrong, so it
        is treated as a hint rather than a declaration.
        """
        return self in (CadFormat.STEP, CadFormat.IGES)

    @classmethod
    def from_path(cls, path: Path | str) -> "CadFormat":
        """Identify a format from a file extension.

        Raises :class:`ValueError` on an unknown extension. Sniffing file contents is
        deliberately not attempted: a mislabelled file is better reported than guessed
        at.
        """
        suffix = Path(path).suffix.lower()
        for fmt in cls:
            if suffix in fmt.extensions:
                return fmt
        known = ", ".join(sorted(e for f in cls for e in f.extensions))
        raise ValueError(
            f"Unsupported file extension {suffix!r}. Supported extensions: {known}"
        )

    @classmethod
    def all_extensions(cls) -> tuple[str, ...]:
        return tuple(sorted(ext for fmt in cls for ext in fmt.extensions))


class WarningSeverity(Enum):
    """How serious a geometry problem is.

    INFO
        Worth knowing, does not affect results.
    CAUTION
        Could affect results depending on what is done next. Analysis may proceed.
    BLOCKING
        The geometry should not be analysed until this is resolved. Display is still
        allowed, because looking at a broken model is how you work out what is wrong
        with it.
    """

    INFO = "info"
    CAUTION = "caution"
    BLOCKING = "blocking"


@dataclass(frozen=True)
class GeometryWarning:
    """A problem found in imported geometry.

    Carried on the model rather than raised, because most geometry problems are
    survivable and the user needs to see the model to judge them. Only an outright
    failure to read the file raises.
    """

    severity: WarningSeverity
    title: str
    detail: str
    solid_index: int | None = None

    def __str__(self) -> str:
        where = f" (solid {self.solid_index})" if self.solid_index is not None else ""
        return f"[{self.severity.value.upper()}]{where} {self.title}: {self.detail}"


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box, in the model's length unit.

    Axis-aligned in the *model's* coordinate system, which is whatever SolidWorks
    exported. It is therefore a property of the part's orientation in the file as much
    as of the part, and a part lying at an angle will report a box larger than its true
    envelope. Phase 2 adds an oriented box for cases where that matters.
    """

    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def size(self) -> tuple[float, float, float]:
        return (self.xmax - self.xmin, self.ymax - self.ymin, self.zmax - self.zmin)

    @property
    def centre(self) -> tuple[float, float, float]:
        return (
            0.5 * (self.xmin + self.xmax),
            0.5 * (self.ymin + self.ymax),
            0.5 * (self.zmin + self.zmax),
        )

    @property
    def diagonal(self) -> float:
        dx, dy, dz = self.size
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    @property
    def smallest_dimension(self) -> float:
        """Useful as a first guess at a plate or flexure's thickness direction."""
        return min(self.size)

    def merged_with(self, other: "BoundingBox") -> "BoundingBox":
        return BoundingBox(
            min(self.xmin, other.xmin),
            min(self.ymin, other.ymin),
            min(self.zmin, other.zmin),
            max(self.xmax, other.xmax),
            max(self.ymax, other.ymax),
            max(self.zmax, other.zmax),
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "xmin": self.xmin, "ymin": self.ymin, "zmin": self.zmin,
            "xmax": self.xmax, "ymax": self.ymax, "zmax": self.zmax,
        }


@dataclass(frozen=True)
class TopologyCounts:
    """Counts of topological entities in a solid.

    Mostly diagnostic. A flexure with an unexpectedly large face count usually means
    the export tessellated something that should have stayed analytic, and a zero shell
    count on a supposed solid means the import produced surfaces rather than a volume.
    """

    solids: int = 0
    shells: int = 0
    faces: int = 0
    wires: int = 0
    edges: int = 0
    vertices: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "solids": self.solids, "shells": self.shells, "faces": self.faces,
            "wires": self.wires, "edges": self.edges, "vertices": self.vertices,
        }


@dataclass
class SolidInfo:
    """One connected solid body and everything measured about it.

    ``shape`` holds the OpenCASCADE ``TopoDS_Shape`` for B-rep imports and ``None`` for
    mesh imports. It is typed ``Any`` so that this module imports cleanly without the
    CAD kernel present; code that needs the real type should check ``is_exact`` on the
    owning model first.

    Mass is intentionally absent. It requires a density, density is a material
    property, and this is a geometry module -- computing a mass here would mean
    inventing a material, which is exactly the habit this project is trying to avoid.
    """

    index: int
    name: str
    volume: float
    surface_area: float
    centre_of_mass: tuple[float, float, float]
    bounding_box: BoundingBox
    counts: TopologyCounts
    is_valid: bool
    validity_detail: str = ""
    inertia_tensor: tuple[tuple[float, float, float], ...] | None = None
    shape: Any = None
    triangles: Any = None  # populated lazily by tessellate.py for display

    @property
    def has_exact_shape(self) -> bool:
        return self.shape is not None

    def as_dict(self) -> dict[str, Any]:
        """Serialisable summary. Excludes the kernel shape and the display mesh."""
        return {
            "index": self.index,
            "name": self.name,
            "volume": self.volume,
            "surface_area": self.surface_area,
            "centre_of_mass": list(self.centre_of_mass),
            "bounding_box": self.bounding_box.as_dict(),
            "counts": self.counts.as_dict(),
            "is_valid": self.is_valid,
            "validity_detail": self.validity_detail,
        }


@dataclass
class GeometryModel:
    """An imported CAD file and everything known about it.

    Note on units for B-rep imports: OpenCASCADE's STEP and IGES readers convert
    incoming geometry to millimetres as they read it. The unit declared in the file
    header is therefore recorded in ``declared_unit`` for information, while ``unit``
    -- the unit the stored coordinates are actually in -- is millimetres. Conflating
    those two is a way to apply the same conversion twice, so they are separate fields.
    """

    source_path: Path
    source_format: CadFormat
    unit: LengthUnit
    unit_confidence: UnitConfidence
    solids: list[SolidInfo] = field(default_factory=list)
    warnings: list[GeometryWarning] = field(default_factory=list)
    declared_unit: LengthUnit | None = None
    loader_notes: list[str] = field(default_factory=list)
    curves: Any = None  # DXF polyline data; None for solid formats

    @property
    def is_exact(self) -> bool:
        """Whether exact analytic surfaces are available.

        False for mesh-derived imports, where curvature and arc length are
        approximations whose error depends on the exporter's tolerance.
        """
        return self.source_format.is_exact

    @property
    def name(self) -> str:
        return self.source_path.stem

    @property
    def solid_count(self) -> int:
        return len(self.solids)

    @property
    def total_volume(self) -> float:
        return sum(s.volume for s in self.solids)

    @property
    def total_surface_area(self) -> float:
        return sum(s.surface_area for s in self.solids)

    @property
    def overall_bounding_box(self) -> BoundingBox | None:
        if not self.solids:
            return None
        box = self.solids[0].bounding_box
        for solid in self.solids[1:]:
            box = box.merged_with(solid.bounding_box)
        return box

    @property
    def has_blocking_warnings(self) -> bool:
        return any(w.severity is WarningSeverity.BLOCKING for w in self.warnings)

    @property
    def is_analysis_ready(self) -> bool:
        """Whether this model may be handed to a mechanics calculation.

        Requires exact geometry, at least one solid, every solid topologically valid,
        no blocking warnings, and a unit that was not merely assumed. The unit
        condition is there because a model silently assumed to be in millimetres when
        it is in inches gives forces wrong by a factor of 25.4 raised to some power,
        with nothing on screen to indicate it.
        """
        return (
            self.is_exact
            and bool(self.solids)
            and all(s.is_valid for s in self.solids)
            and not self.has_blocking_warnings
            and self.unit_confidence.is_trustworthy
        )

    def analysis_readiness_reasons(self) -> list[str]:
        """Why :attr:`is_analysis_ready` is False. Empty when it is True."""
        reasons: list[str] = []
        if not self.is_exact:
            reasons.append(
                f"{self.source_format.label} is a tessellated format, so exact "
                "geometric queries are unavailable. Re-export as STEP for analysis."
            )
        if not self.solids:
            reasons.append("No solid bodies were found in the file.")
        invalid = [s.index for s in self.solids if not s.is_valid]
        if invalid:
            reasons.append(
                f"Topologically invalid solid(s): {', '.join(map(str, invalid))}."
            )
        if self.has_blocking_warnings:
            for w in self.warnings:
                if w.severity is WarningSeverity.BLOCKING:
                    reasons.append(f"{w.title}: {w.detail}")
        if not self.unit_confidence.is_trustworthy:
            reasons.append(
                "The length unit was assumed rather than declared. Confirm it before "
                "running any analysis."
            )
        return reasons

    def warnings_of(self, severity: WarningSeverity) -> list[GeometryWarning]:
        return [w for w in self.warnings if w.severity is severity]

    def add_warning(
        self,
        severity: WarningSeverity,
        title: str,
        detail: str,
        solid_index: int | None = None,
    ) -> None:
        self.warnings.append(GeometryWarning(severity, title, detail, solid_index))

    def __iter__(self) -> Iterator[SolidInfo]:
        return iter(self.solids)

    def as_dict(self) -> dict[str, Any]:
        """Serialisable summary, used by the project store and the report writer."""
        box = self.overall_bounding_box
        return {
            "source_path": str(self.source_path),
            "source_format": self.source_format.label,
            "unit": self.unit.symbol,
            "unit_confidence": self.unit_confidence.value,
            "declared_unit": self.declared_unit.symbol if self.declared_unit else None,
            "is_exact": self.is_exact,
            "solid_count": self.solid_count,
            "total_volume": self.total_volume,
            "total_surface_area": self.total_surface_area,
            "overall_bounding_box": box.as_dict() if box else None,
            "is_analysis_ready": self.is_analysis_ready,
            "solids": [s.as_dict() for s in self.solids],
            "warnings": [
                {
                    "severity": w.severity.value,
                    "title": w.title,
                    "detail": w.detail,
                    "solid_index": w.solid_index,
                }
                for w in self.warnings
            ],
            "loader_notes": list(self.loader_notes),
        }


def summarise_models(models: Sequence[GeometryModel]) -> dict[str, Any]:
    """Aggregate summary across several models, for the project dashboard."""
    return {
        "model_count": len(models),
        "total_solids": sum(m.solid_count for m in models),
        "total_volume": sum(m.total_volume for m in models),
        "all_analysis_ready": all(m.is_analysis_ready for m in models) if models else False,
    }
