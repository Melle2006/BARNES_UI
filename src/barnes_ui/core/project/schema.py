"""Project file schema.

A project is a *directory*, not a single file. Analysis runs in later phases produce
solver decks, logs and result files that are far too large to embed in a document, and
a directory keeps them inspectable with ordinary tools.

    MyProject.barnesproj/
        project.json        this schema, human-readable
        geometry/           copies of the imported CAD files
        materials/          material definitions and test data        [Phase 2]
        runs/               one directory per analysis run            [Phase 3]
        reports/            exported figures and CSV                  [Phase 3]

Imported CAD is copied in rather than referenced. Referencing is tempting and breaks
the first time somebody tidies their Downloads folder, at which point a project that
took a week to set up no longer opens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "PROJECT_SCHEMA_VERSION",
    "GeometryEntry",
    "ProjectData",
]

#: Incremented whenever the on-disk format changes in a way that needs migrating.
#: ``store.py`` holds the migrations. Version 1 is the Phase 1 format.
PROJECT_SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class GeometryEntry:
    """One imported CAD file recorded in a project.

    Holds the measured summary as well as the file reference, so that the project
    dashboard can list models with their volumes without re-importing and re-measuring
    every file on open -- which for a large assembly is a slow operation.

    ``unit_confidence`` is persisted because a unit the user confirmed must stay
    confirmed across sessions. Re-asking on every open would train people to click
    through the prompt, which defeats its purpose.
    """

    entry_id: str
    original_path: str
    stored_filename: str
    source_format: str
    unit: str
    unit_confidence: str
    declared_unit: str | None = None
    role: str = "unassigned"      # "flexure" | "hand_assembly" | "unassigned"
    imported_at: str = field(default_factory=_utc_now)
    summary: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "original_path": self.original_path,
            "stored_filename": self.stored_filename,
            "source_format": self.source_format,
            "unit": self.unit,
            "unit_confidence": self.unit_confidence,
            "declared_unit": self.declared_unit,
            "role": self.role,
            "imported_at": self.imported_at,
            "summary": self.summary,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeometryEntry":
        return cls(
            entry_id=data["entry_id"],
            original_path=data.get("original_path", ""),
            stored_filename=data["stored_filename"],
            source_format=data.get("source_format", "UNKNOWN"),
            unit=data.get("unit", "mm"),
            unit_confidence=data.get("unit_confidence", "assumed"),
            declared_unit=data.get("declared_unit"),
            role=data.get("role", "unassigned"),
            imported_at=data.get("imported_at", _utc_now()),
            summary=data.get("summary", {}),
            notes=data.get("notes", ""),
        )


@dataclass
class ProjectData:
    """The contents of ``project.json``."""

    name: str
    schema_version: int = PROJECT_SCHEMA_VERSION
    created_at: str = field(default_factory=_utc_now)
    modified_at: str = field(default_factory=_utc_now)
    application_version: str = ""
    description: str = ""
    geometry: list[GeometryEntry] = field(default_factory=list)

    # Reserved for later phases. Present from version 1 so that adding them does not
    # need a schema bump -- an older build writing this file simply leaves them empty.
    materials: list[dict[str, Any]] = field(default_factory=list)
    analyses: list[dict[str, Any]] = field(default_factory=list)
    joints: list[dict[str, Any]] = field(default_factory=list)

    def touch(self) -> None:
        self.modified_at = _utc_now()

    def geometry_by_id(self, entry_id: str) -> GeometryEntry | None:
        for entry in self.geometry:
            if entry.entry_id == entry_id:
                return entry
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "application_version": self.application_version,
            "description": self.description,
            "geometry": [g.as_dict() for g in self.geometry],
            "materials": self.materials,
            "analyses": self.analyses,
            "joints": self.joints,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectData":
        return cls(
            name=data.get("name", "Untitled"),
            schema_version=int(data.get("schema_version", 1)),
            created_at=data.get("created_at", _utc_now()),
            modified_at=data.get("modified_at", _utc_now()),
            application_version=data.get("application_version", ""),
            description=data.get("description", ""),
            geometry=[GeometryEntry.from_dict(g) for g in data.get("geometry", [])],
            materials=list(data.get("materials", [])),
            analyses=list(data.get("analyses", [])),
            joints=list(data.get("joints", [])),
        )
