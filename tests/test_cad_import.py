"""CAD import tests.

These implement the Phase 1 acceptance criteria from docs/05-development-plan.md.
Geometry is generated with exactly known properties so the assertions are against
real numbers rather than against previously recorded output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from barnes_ui.core.cad.model import CadFormat, GeometryModel, WarningSeverity
from barnes_ui.core.cad.registry import (
    file_dialog_filter,
    load_geometry,
    native_solidworks_advice,
    supported_extensions,
)
from barnes_ui.core.cad.loaders.errors import GeometryLoadError, UnsupportedFormatError
from barnes_ui.core.cad.loaders.step import parse_declared_unit
from barnes_ui.core.units import LengthUnit, UnitConfidence

from conftest import BOX_AREA, BOX_VOLUME, BOX_X, BOX_Y, BOX_Z, requires_kernel


# --------------------------------------------------------------------------
# Format detection
# --------------------------------------------------------------------------

class TestFormatDetection:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("part.step", CadFormat.STEP),
            ("part.STP", CadFormat.STEP),
            ("part.iges", CadFormat.IGES),
            ("part.igs", CadFormat.IGES),
            ("part.brep", CadFormat.BREP),
            ("part.stl", CadFormat.STL),
            ("profile.dxf", CadFormat.DXF),
        ],
    )
    def test_detects_by_extension(self, name: str, expected: CadFormat) -> None:
        assert CadFormat.from_path(Path(name)) is expected

    def test_unknown_extension_raises(self) -> None:
        with pytest.raises(ValueError):
            CadFormat.from_path(Path("part.xyz"))

    def test_brep_formats_are_exact(self) -> None:
        assert CadFormat.STEP.is_exact
        assert CadFormat.IGES.is_exact
        assert CadFormat.BREP.is_exact

    def test_mesh_formats_are_not_exact(self) -> None:
        """The distinction that keeps tessellated geometry out of the mechanics."""
        assert not CadFormat.STL.is_exact
        assert not CadFormat.DXF.is_exact

    def test_only_step_and_iges_declare_units(self) -> None:
        assert CadFormat.STEP.declares_units
        assert CadFormat.IGES.declares_units
        assert not CadFormat.STL.declares_units
        assert not CadFormat.BREP.declares_units


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_file_raises_geometry_load_error(self, tmp_path: Path) -> None:
        with pytest.raises(GeometryLoadError, match="not found"):
            load_geometry(tmp_path / "nope.step")

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "thing.xyz"
        path.write_text("x", encoding="utf-8")
        with pytest.raises(UnsupportedFormatError):
            load_geometry(path)

    @requires_kernel
    def test_corrupt_step_gives_actionable_message(self, corrupt_step: Path) -> None:
        """Acceptance criterion 5: a clear error, not a traceback."""
        with pytest.raises(GeometryLoadError) as excinfo:
            load_geometry(corrupt_step)
        message = str(excinfo.value)
        assert "STEP" in message
        # The message must tell the user what to do about it.
        assert "export" in message.lower() or "corrupt" in message.lower()

    def test_native_solidworks_part_explains_the_export_route(self, tmp_path: Path) -> None:
        path = tmp_path / "A8_flexure.SLDPRT"
        path.write_bytes(b"\x00\x01binary")
        with pytest.raises(UnsupportedFormatError) as excinfo:
            load_geometry(path)
        message = str(excinfo.value)
        assert "STEP AP214" in message
        assert "Save As" in message

    def test_native_solidworks_assembly_mentions_single_file_option(self) -> None:
        """Exporting components separately loses placement, which breaks Phase 4."""
        advice = native_solidworks_advice(Path("hand.SLDASM"))
        assert "single file" in advice.lower()
        assert "assembly" in advice.lower()


# --------------------------------------------------------------------------
# STEP
# --------------------------------------------------------------------------

@requires_kernel
class TestStepImport:
    def test_loads_and_reports_one_solid(self, box_step: Path) -> None:
        model = load_geometry(box_step)
        assert isinstance(model, GeometryModel)
        assert model.source_format is CadFormat.STEP
        assert model.solid_count == 1

    def test_volume_matches_to_better_than_point_one_percent(self, box_step: Path) -> None:
        """Acceptance criterion 1, against an exactly known volume."""
        model = load_geometry(box_step)
        assert model.total_volume == pytest.approx(BOX_VOLUME, rel=1e-3)

    def test_surface_area_is_exact(self, box_step: Path) -> None:
        model = load_geometry(box_step)
        assert model.total_surface_area == pytest.approx(BOX_AREA, rel=1e-6)

    def test_bounding_box_is_not_inflated_by_shape_tolerance(self, box_step: Path) -> None:
        """Dimensions are reported, so the box must be tight, not padded.

        Regression test: computing it with useShapeTolerance=True reported a 10 mm
        box as 10.0000002 mm.
        """
        model = load_geometry(box_step)
        dx, dy, dz = model.solids[0].bounding_box.size
        assert dx == pytest.approx(BOX_X, abs=1e-9)
        assert dy == pytest.approx(BOX_Y, abs=1e-9)
        assert dz == pytest.approx(BOX_Z, abs=1e-9)

    def test_unit_is_detected_from_the_header(self, box_step: Path) -> None:
        """Acceptance criterion 2."""
        model = load_geometry(box_step)
        assert model.declared_unit is LengthUnit.MILLIMETRE
        assert model.unit_confidence is UnitConfidence.DECLARED
        assert model.unit_confidence.is_trustworthy

    def test_unit_is_found_when_declared_late_in_a_large_file(
        self, tmp_path: Path, box_step: Path
    ) -> None:
        """Regression: the declaration may sit at the very end of the file.

        parse_declared_unit originally read only the first 2 MB, assuming unit
        entities appear near the start of the DATA section. Files written by
        OpenCASCADE's own STEP processor put the global unit context at the end
        instead, so a real 2.27 MB part had its declaration at line 51425 of 51430
        and came back undetected -- which flagged the model units-assumed and refused
        it for analysis even though the file plainly said millimetres.

        Built here by padding a valid STEP with comment filler so the declaration
        lands well beyond any fixed head window, without needing a large fixture.
        """
        original = box_step.read_text(encoding="utf-8", errors="replace")
        marker = "#44198 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );"
        assert "LENGTH_UNIT" in original

        # Strip the real declaration, pad past the old window, then re-add it at the end.
        stripped = "\n".join(
            line for line in original.splitlines() if "LENGTH_UNIT" not in line
        )
        filler = "\n".join(f"/* padding line {i} to push the unit declaration late */"
                           for i in range(60_000))
        padded = tmp_path / "late_unit.step"
        padded.write_text(
            stripped.replace("ENDSEC;\nEND-ISO-10303-21;", "")
            + "\n" + filler + "\n" + marker + "\nENDSEC;\nEND-ISO-10303-21;\n",
            encoding="utf-8",
        )
        assert padded.stat().st_size > 2_500_000, "fixture must exceed the old 2 MB window"

        assert parse_declared_unit(padded) is LengthUnit.MILLIMETRE

    def test_topology_counts_match_a_box(self, box_step: Path) -> None:
        counts = load_geometry(box_step).solids[0].counts
        assert counts.solids == 1
        assert counts.shells == 1
        assert counts.faces == 6
        assert counts.edges == 24       # OCCT counts each edge once per adjoining face

    def test_solid_is_valid(self, box_step: Path) -> None:
        assert load_geometry(box_step).solids[0].is_valid

    def test_centre_of_mass_is_the_box_centre(self, box_step: Path) -> None:
        cx, cy, cz = load_geometry(box_step).solids[0].centre_of_mass
        assert cx == pytest.approx(BOX_X / 2)
        assert cy == pytest.approx(BOX_Y / 2)
        assert cz == pytest.approx(BOX_Z / 2)

    def test_clean_model_is_analysis_ready(self, box_step: Path) -> None:
        model = load_geometry(box_step)
        assert model.is_analysis_ready
        assert model.analysis_readiness_reasons() == []

    def test_no_blocking_warnings_for_clean_geometry(self, box_step: Path) -> None:
        model = load_geometry(box_step)
        assert not model.has_blocking_warnings

    def test_multi_body_file_lists_bodies_separately(self, two_box_step: Path) -> None:
        """Acceptance criterion 4."""
        model = load_geometry(two_box_step)
        assert model.solid_count == 2
        volumes = sorted(s.volume for s in model.solids)
        assert volumes[0] == pytest.approx(125.0, rel=1e-3)      # 5^3
        assert volumes[1] == pytest.approx(BOX_VOLUME, rel=1e-3)
        assert model.total_volume == pytest.approx(BOX_VOLUME + 125.0, rel=1e-3)

    def test_multi_body_file_is_flagged(self, two_box_step: Path) -> None:
        model = load_geometry(two_box_step)
        titles = [w.title for w in model.warnings_of(WarningSeverity.INFO)]
        assert any("disconnected" in t.lower() for t in titles)


# --------------------------------------------------------------------------
# STL
# --------------------------------------------------------------------------

class TestStlImport:
    def test_loads(self, box_stl: Path) -> None:
        model = load_geometry(box_stl)
        assert model.source_format is CadFormat.STL
        assert model.solid_count >= 1

    def test_is_marked_inexact(self, box_stl: Path) -> None:
        """Acceptance criterion 3, first half."""
        assert not load_geometry(box_stl).is_exact

    def test_units_are_flagged_as_assumed(self, box_stl: Path) -> None:
        """Acceptance criterion 3, second half. STL carries no unit at all."""
        model = load_geometry(box_stl)
        assert model.unit_confidence is UnitConfidence.ASSUMED
        assert not model.unit_confidence.is_trustworthy

    def test_is_not_analysis_ready(self, box_stl: Path) -> None:
        """A tessellated model must never reach the mechanics modules."""
        model = load_geometry(box_stl)
        assert not model.is_analysis_ready
        reasons = " ".join(model.analysis_readiness_reasons()).lower()
        assert "tessellated" in reasons

    def test_blocks_analysis_with_an_explanation(self, box_stl: Path) -> None:
        model = load_geometry(box_stl)
        blocking = model.warnings_of(WarningSeverity.BLOCKING)
        assert blocking
        assert any("STEP" in w.detail for w in blocking)

    def test_mesh_volume_is_close_but_the_model_stays_inexact(self, box_stl: Path) -> None:
        """A box tessellates exactly, so the number agrees -- the flag does not."""
        model = load_geometry(box_stl)
        assert model.total_volume == pytest.approx(BOX_VOLUME, rel=1e-6)
        assert not model.is_exact

    def test_display_mesh_is_cached_by_the_loader(self, box_stl: Path) -> None:
        solid = load_geometry(box_stl).solids[0]
        assert solid.triangles is not None
        assert solid.triangles.triangle_count == 12   # a box is 12 triangles
        assert solid.shape is None                    # no exact geometry exists


# --------------------------------------------------------------------------
# DXF
# --------------------------------------------------------------------------

class TestDxfImport:
    def test_loads_curves(self, simple_dxf: Path) -> None:
        model = load_geometry(simple_dxf)
        assert model.source_format is CadFormat.DXF
        assert model.curves is not None
        assert len(model.curves.polylines) >= 2

    def test_has_no_solids(self, simple_dxf: Path) -> None:
        assert load_geometry(simple_dxf).solid_count == 0

    def test_is_blocked_for_analysis(self, simple_dxf: Path) -> None:
        model = load_geometry(simple_dxf)
        assert not model.is_analysis_ready
        assert model.has_blocking_warnings

    def test_entity_counts_are_reported(self, simple_dxf: Path) -> None:
        counts = load_geometry(simple_dxf).curves.entity_counts
        assert counts.get("LWPOLYLINE", 0) == 1
        assert counts.get("CIRCLE", 0) == 1

    def test_curve_extents_match_the_drawing(self, simple_dxf: Path) -> None:
        bounds = load_geometry(simple_dxf).curves.bounds()
        assert bounds is not None
        dx, dy, _ = bounds.size
        assert dx == pytest.approx(10.0, abs=0.1)
        assert dy == pytest.approx(20.0, abs=0.1)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class TestRegistry:
    def test_supported_extensions_cover_every_format(self) -> None:
        extensions = supported_extensions()
        for expected in (".step", ".stp", ".iges", ".igs", ".brep", ".stl", ".dxf"):
            assert expected in extensions

    def test_dialog_filter_includes_solidworks_so_the_advice_can_be_shown(self) -> None:
        text = file_dialog_filter()
        assert "*.step" in text
        assert "sldprt" in text.lower()

    def test_loader_notes_record_the_import(self, box_step: Path) -> None:
        if not CadFormat.STEP.is_exact:  # pragma: no cover - sanity guard
            pytest.skip("unreachable")
        pytest.importorskip("OCP")
        model = load_geometry(box_step)
        assert any("Imported in" in note for note in model.loader_notes)
