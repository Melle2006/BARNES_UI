"""Project persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from barnes_ui.core.cad.registry import load_geometry
from barnes_ui.core.project.schema import PROJECT_SCHEMA_VERSION, ProjectData
from barnes_ui.core.project.store import PROJECT_SUFFIX, ProjectStore, ProjectStoreError

from conftest import requires_kernel


class TestCreate:
    def test_creates_the_directory_structure(self, tmp_path: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        assert store.root.suffix == PROJECT_SUFFIX
        assert (store.root / "project.json").is_file()
        for sub in ("geometry", "materials", "runs", "reports"):
            assert (store.root / sub).is_dir()

    def test_appends_the_suffix_when_missing(self, tmp_path: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        assert store.root.name == f"demo{PROJECT_SUFFIX}"

    def test_does_not_append_the_suffix_twice(self, tmp_path: Path) -> None:
        store = ProjectStore.create(tmp_path / f"demo{PROJECT_SUFFIX}")
        assert store.root.name == f"demo{PROJECT_SUFFIX}"

    def test_refuses_a_non_empty_directory(self, tmp_path: Path) -> None:
        """Merging into an existing directory produces projects nobody can reason about."""
        target = tmp_path / f"used{PROJECT_SUFFIX}"
        target.mkdir()
        (target / "something.txt").write_text("hello", encoding="utf-8")
        with pytest.raises(ProjectStoreError, match="not empty"):
            ProjectStore.create(target)

    def test_accepts_an_existing_empty_directory(self, tmp_path: Path) -> None:
        target = tmp_path / f"empty{PROJECT_SUFFIX}"
        target.mkdir()
        assert ProjectStore.create(target).root == target

    def test_name_defaults_to_the_directory_stem(self, tmp_path: Path) -> None:
        assert ProjectStore.create(tmp_path / "A8_study").name == "A8_study"


class TestOpen:
    def test_round_trips(self, tmp_path: Path) -> None:
        created = ProjectStore.create(tmp_path / "demo", name="Flexure study")
        reopened = ProjectStore.open(created.root)
        assert reopened.name == "Flexure study"
        assert reopened.data.schema_version == PROJECT_SCHEMA_VERSION

    def test_accepts_the_manifest_path(self, tmp_path: Path) -> None:
        """Users drag either the folder or the json, so both must work."""
        created = ProjectStore.create(tmp_path / "demo")
        assert ProjectStore.open(created.root / "project.json").root == created.root

    def test_rejects_a_directory_that_is_not_a_project(self, tmp_path: Path) -> None:
        with pytest.raises(ProjectStoreError, match="not a Barnes UI project"):
            ProjectStore.open(tmp_path)

    def test_reports_corrupt_json_clearly(self, tmp_path: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        (store.root / "project.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ProjectStoreError, match="not valid JSON"):
            ProjectStore.open(store.root)

    def test_refuses_a_newer_schema(self, tmp_path: Path) -> None:
        """Opening a future format and silently dropping fields would lose work."""
        store = ProjectStore.create(tmp_path / "demo")
        manifest = store.root / "project.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["schema_version"] = PROJECT_SCHEMA_VERSION + 5
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ProjectStoreError, match="newer version"):
            ProjectStore.open(store.root)

    def test_recreates_missing_subdirectories(self, tmp_path: Path) -> None:
        """Copy tools routinely drop empty directories."""
        store = ProjectStore.create(tmp_path / "demo")
        (store.root / "runs").rmdir()
        assert (ProjectStore.open(store.root).root / "runs").is_dir()


class TestSave:
    def test_leaves_no_temporary_file_behind(self, tmp_path: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        store.save()
        assert not list(store.root.glob("*.tmp"))

    def test_updates_the_modified_timestamp(self, tmp_path: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        before = store.data.modified_at
        store.data.description = "changed"
        store.save()
        assert store.data.modified_at >= before

    def test_writes_readable_json(self, tmp_path: Path) -> None:
        """The manifest is meant to be inspectable with a text editor."""
        store = ProjectStore.create(tmp_path / "demo", name="Readable")
        text = (store.root / "project.json").read_text(encoding="utf-8")
        assert "\n" in text          # indented, not one long line
        assert json.loads(text)["name"] == "Readable"


@requires_kernel
class TestGeometryEntries:
    def test_copies_the_file_into_the_project(self, tmp_path: Path, box_step: Path) -> None:
        """Copying is what makes a project survive the source file being moved."""
        store = ProjectStore.create(tmp_path / "demo")
        entry = store.add_geometry(load_geometry(box_step))
        stored = store.geometry_path(entry)
        assert stored.is_file()
        assert stored.stat().st_size == box_step.stat().st_size

    def test_survives_the_source_being_deleted(self, tmp_path: Path, box_step: Path) -> None:
        source = tmp_path / "copy.step"
        source.write_bytes(box_step.read_bytes())
        store = ProjectStore.create(tmp_path / "demo")
        entry = store.add_geometry(load_geometry(source))
        source.unlink()
        assert store.geometry_path(entry).is_file()
        assert ProjectStore.open(store.root).data.geometry[0].entry_id == entry.entry_id

    def test_records_the_measured_summary(self, tmp_path: Path, box_step: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        entry = store.add_geometry(load_geometry(box_step))
        assert entry.summary["solid_count"] == 1
        assert entry.summary["total_volume"] == pytest.approx(600.0, rel=1e-3)

    def test_unit_confirmation_persists_across_reopening(
        self, tmp_path: Path, box_step: Path
    ) -> None:
        """Re-asking on every open trains people to click through the prompt."""
        store = ProjectStore.create(tmp_path / "demo")
        entry = store.add_geometry(load_geometry(box_step))
        store.update_unit(entry.entry_id, "mm", "user_set")
        reopened = ProjectStore.open(store.root)
        assert reopened.data.geometry[0].unit_confidence == "user_set"

    def test_remove_deletes_the_entry_and_the_file(
        self, tmp_path: Path, box_step: Path
    ) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        entry = store.add_geometry(load_geometry(box_step))
        path = store.geometry_path(entry)
        assert store.remove_geometry(entry.entry_id)
        assert not path.exists()
        assert store.data.geometry == []

    def test_remove_unknown_id_returns_false(self, tmp_path: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        assert store.remove_geometry("deadbeef") is False

    def test_missing_source_raises(self, tmp_path: Path, box_step: Path) -> None:
        store = ProjectStore.create(tmp_path / "demo")
        model = load_geometry(box_step)
        model.source_path = tmp_path / "vanished.step"
        with pytest.raises(ProjectStoreError, match="no longer exists"):
            store.add_geometry(model)


class TestSchema:
    def test_round_trips_through_a_dict(self) -> None:
        original = ProjectData(name="Test", description="A description")
        restored = ProjectData.from_dict(original.as_dict())
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.schema_version == original.schema_version

    def test_later_phase_fields_are_present_from_version_one(self) -> None:
        """Reserved so that adding materials or analyses needs no schema bump."""
        data = ProjectData(name="Test").as_dict()
        for key in ("materials", "analyses", "joints"):
            assert key in data

    def test_geometry_lookup_by_id(self) -> None:
        from barnes_ui.core.project.schema import GeometryEntry

        data = ProjectData(name="Test")
        data.geometry.append(
            GeometryEntry(
                entry_id="abc123", original_path="/x.step", stored_filename="abc123_x.step",
                source_format="STEP", unit="mm", unit_confidence="declared",
            )
        )
        assert data.geometry_by_id("abc123") is not None
        assert data.geometry_by_id("missing") is None
