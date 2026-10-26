"""Reading and writing project directories."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from ..cad.model import GeometryModel
from .schema import PROJECT_SCHEMA_VERSION, GeometryEntry, ProjectData

logger = logging.getLogger(__name__)

__all__ = ["ProjectStore", "ProjectStoreError", "PROJECT_SUFFIX"]

PROJECT_SUFFIX = ".barnesproj"
_MANIFEST = "project.json"
_GEOMETRY_DIR = "geometry"
_SUBDIRECTORIES = (_GEOMETRY_DIR, "materials", "runs", "reports")


class ProjectStoreError(Exception):
    """A project could not be created, read or written."""


class ProjectStore:
    """A project directory on disk.

    Instances are created through :meth:`create` or :meth:`open`, never directly, so
    that a store always refers to a directory that actually exists and has a valid
    manifest.
    """

    def __init__(self, root: Path, data: ProjectData) -> None:
        self.root = Path(root)
        self.data = data

    # -- lifecycle -------------------------------------------------------------

    @classmethod
    def create(
        cls, root: Path | str, name: str = "", application_version: str = ""
    ) -> "ProjectStore":
        """Create a new project directory.

        Refuses to overwrite a non-empty directory. Silently merging into whatever was
        already there produces projects with orphaned geometry that nothing references
        and is impossible to reason about later.
        """
        root = Path(root)
        if root.suffix != PROJECT_SUFFIX:
            root = root.with_suffix(PROJECT_SUFFIX)

        if root.exists():
            if any(root.iterdir()):
                raise ProjectStoreError(
                    f"{root} already exists and is not empty. Choose a different "
                    "location, or open the existing project instead."
                )
        else:
            try:
                root.mkdir(parents=True)
            except OSError as exc:
                raise ProjectStoreError(f"Could not create {root}: {exc}") from exc

        for sub in _SUBDIRECTORIES:
            (root / sub).mkdir(exist_ok=True)

        data = ProjectData(
            name=name or root.stem,
            application_version=application_version,
        )
        store = cls(root, data)
        store.save()
        logger.info("Created project at %s", root)
        return store

    @classmethod
    def open(cls, root: Path | str) -> "ProjectStore":
        """Open an existing project directory.

        Accepts either the directory or its ``project.json``, since users drag both.
        """
        root = Path(root)
        if root.is_file() and root.name == _MANIFEST:
            root = root.parent

        manifest = root / _MANIFEST
        if not manifest.is_file():
            raise ProjectStoreError(
                f"{root} is not a Barnes UI project: no {_MANIFEST} was found."
            )

        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProjectStoreError(
                f"{manifest} is not valid JSON ({exc}). The file may have been "
                "edited by hand or truncated by an interrupted save."
            ) from exc
        except OSError as exc:
            raise ProjectStoreError(f"Could not read {manifest}: {exc}") from exc

        raw = _migrate(raw, manifest)
        data = ProjectData.from_dict(raw)

        # Ensure the expected subdirectories exist. A project copied between machines
        # can arrive with empty directories dropped by the copy tool.
        for sub in _SUBDIRECTORIES:
            (root / sub).mkdir(exist_ok=True)

        logger.info("Opened project %s (%d geometry entries)", root, len(data.geometry))
        return cls(root, data)

    # -- persistence -----------------------------------------------------------

    def save(self) -> None:
        """Write the manifest.

        Writes to a temporary file and then replaces the original, so that a crash or
        a full disk partway through cannot leave a half-written manifest. ``Path.replace``
        is atomic on the same filesystem, which is what makes this safe rather than
        merely tidy.
        """
        self.data.touch()
        self.data.schema_version = PROJECT_SCHEMA_VERSION
        manifest = self.root / _MANIFEST
        temporary = manifest.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(self.data.as_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(manifest)
        except OSError as exc:
            raise ProjectStoreError(f"Could not save {manifest}: {exc}") from exc
        logger.debug("Saved project manifest to %s", manifest)

    # -- geometry --------------------------------------------------------------

    def add_geometry(self, model: GeometryModel, role: str = "unassigned") -> GeometryEntry:
        """Copy an imported CAD file into the project and record it.

        The copy is what makes a project self-contained and portable. The cost is disk
        space, which is cheap compared with a project that cannot be reopened.
        """
        source = Path(model.source_path)
        if not source.is_file():
            raise ProjectStoreError(f"Source file no longer exists: {source}")

        entry_id = uuid.uuid4().hex[:12]
        stored_filename = f"{entry_id}_{source.name}"
        destination = self.root / _GEOMETRY_DIR / stored_filename

        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            raise ProjectStoreError(
                f"Could not copy {source.name} into the project: {exc}"
            ) from exc

        entry = GeometryEntry(
            entry_id=entry_id,
            original_path=str(source),
            stored_filename=stored_filename,
            source_format=model.source_format.label,
            unit=model.unit.symbol,
            unit_confidence=model.unit_confidence.value,
            declared_unit=model.declared_unit.symbol if model.declared_unit else None,
            role=role,
            summary=model.as_dict(),
        )
        self.data.geometry.append(entry)
        self.save()
        logger.info("Added geometry %s (%s) to project", source.name, entry_id)
        return entry

    def geometry_path(self, entry: GeometryEntry) -> Path:
        """Absolute path to a stored geometry file."""
        return self.root / _GEOMETRY_DIR / entry.stored_filename

    def remove_geometry(self, entry_id: str) -> bool:
        """Remove an entry and its stored file. Returns False if it was not found."""
        entry = self.data.geometry_by_id(entry_id)
        if entry is None:
            return False
        path = self.geometry_path(entry)
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            logger.warning("Could not delete %s: %s", path, exc)
        self.data.geometry.remove(entry)
        self.save()
        return True

    def update_unit(self, entry_id: str, unit: str, confidence: str) -> None:
        """Record a user's unit confirmation so it survives reopening."""
        entry = self.data.geometry_by_id(entry_id)
        if entry is None:
            raise ProjectStoreError(f"No geometry entry with id {entry_id}")
        entry.unit = unit
        entry.unit_confidence = confidence
        self.save()

    # -- housekeeping ----------------------------------------------------------

    def runs_directory(self) -> Path:
        return self.root / "runs"

    def reports_directory(self) -> Path:
        return self.root / "reports"

    @property
    def name(self) -> str:
        return self.data.name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ProjectStore({self.root!s}, {len(self.data.geometry)} geometry)"


def _migrate(raw: dict, manifest: Path) -> dict:
    """Bring an older manifest up to the current schema version.

    No migrations exist yet -- version 1 is the first format. The function is here from
    the start so that the first time a migration is needed there is an obvious place
    to put it, rather than a scramble to add migration support to a format already in
    the wild.
    """
    version = int(raw.get("schema_version", 1))

    if version > PROJECT_SCHEMA_VERSION:
        raise ProjectStoreError(
            f"{manifest} was written by a newer version of Barnes UI "
            f"(schema {version}, this build understands {PROJECT_SCHEMA_VERSION}). "
            "Update the application to open it."
        )

    # Future migrations go here, each stepping the version by one:
    #
    #   if version == 1:
    #       raw = _migrate_1_to_2(raw)
    #       version = 2

    raw["schema_version"] = PROJECT_SCHEMA_VERSION
    return raw
