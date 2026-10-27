"""Flexure adaptation tests.

Phase 4 criteria 2, 3, 5 and 6 live here. The strong one is criterion 2: regenerating
at the original parameters must reproduce the original volume, which is what proves the
template actually describes the design before the template is used to change it.

Because the meander template's volume is analytically exact -- ``width * thickness *
centreline_length`` -- these tests assert against arithmetic rather than against
recorded output.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from barnes_ui.core.cad.inspect import inspect_solid
from barnes_ui.core.flexure.adaptation import (
    AdaptationError,
    adapt_to_span,
    manufacturability_issues,
    required_peak_strain,
    verify_regeneration,
)
from barnes_ui.core.flexure.templates.meander import MeanderParameters, build_meander
from barnes_ui.core.provenance import Provenance

from conftest import requires_kernel


BASE = MeanderParameters(
    run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
)


class TestSpanAdaptation:
    def test_pitch_strategy_hits_the_target_span_exactly(self) -> None:
        report = adapt_to_span(BASE, target_span=16.0, strategy="pitch")
        assert report.adapted.envelope[1] == pytest.approx(16.0, abs=1e-12)
        assert report.adapted.n_runs == BASE.n_runs

    def test_runs_strategy_keeps_the_pitch_close_and_changes_the_count(self) -> None:
        report = adapt_to_span(BASE, target_span=22.0, strategy="runs")
        assert report.adapted.envelope[1] == pytest.approx(22.0, abs=1e-12)
        assert report.adapted.n_runs != BASE.n_runs
        # "approximately constant pitch" means within one run's worth.
        assert abs(report.adapted.pitch - BASE.pitch) < BASE.pitch

    def test_thickness_and_width_are_preserved_exactly(self) -> None:
        """Phase 4 criterion 3. Exact equality, not a tolerance.

        Stiffness goes as width cubed, so "nearly the same width" is not the same
        design. The function asserts this internally too; this test is the external
        statement of the contract.
        """
        for strategy in ("pitch", "runs"):
            report = adapt_to_span(BASE, target_span=19.0, strategy=strategy)
            assert report.adapted.thickness == BASE.thickness
            assert report.adapted.width == BASE.width
            assert not report.changed("thickness")
            assert not report.changed("width")

    def test_every_change_is_reported_and_attributed(self) -> None:
        """Phase 4 criterion 6.

        23 mm does not divide into whole runs at the base 3.0 mm pitch, so both the
        count and the pitch have to move and both must appear in the report.
        """
        report = adapt_to_span(BASE, target_span=23.0, strategy="runs")
        names = {c.name for c in report.changes}
        assert names == {"n_runs", "pitch"}
        assert all(c.intended for c in report.changes)
        assert report.unintended_changes == []
        assert "n_runs" in report.summary()

    def test_a_span_that_fits_whole_runs_leaves_the_pitch_alone(self) -> None:
        """22 mm is exactly 8 runs at 3.0 mm pitch plus one width, so only the count
        changes. A report listing a pitch change here would be noise."""
        report = adapt_to_span(BASE, target_span=22.0, strategy="runs")
        assert report.adapted.pitch == BASE.pitch
        assert {c.name for c in report.changes} == {"n_runs"}

    def test_run_length_is_untouched_by_a_span_change(self) -> None:
        report = adapt_to_span(BASE, target_span=16.0)
        assert report.adapted.run_length == BASE.run_length

    def test_refuses_a_span_that_would_merge_adjacent_runs(self) -> None:
        with pytest.raises(AdaptationError, match="merge into a solid block"):
            adapt_to_span(BASE, target_span=4.0, strategy="pitch")

    def test_refuses_a_non_positive_span(self) -> None:
        with pytest.raises(AdaptationError, match="must be positive"):
            adapt_to_span(BASE, target_span=0.0)

    def test_refuses_an_unknown_strategy(self) -> None:
        with pytest.raises(AdaptationError, match="Unknown strategy"):
            adapt_to_span(BASE, target_span=16.0, strategy="stretch")


class TestSafetyChecks:
    def test_a_sub_manufacturable_width_blocks_approval(self) -> None:
        """Phase 4 criterion 5: flagged, and NOT auto-approved."""
        thin = MeanderParameters(
            run_length=12.0, n_runs=4, pitch=3.0, width=0.2, thickness=1.2
        )
        issues = manufacturability_issues(thin, minimum_feature_size=0.4)
        assert any(i.key == "width_below_minimum" and i.blocking for i in issues)

        report = adapt_to_span(thin, target_span=16.0)
        assert not report.is_auto_approvable
        assert report.blocking_issues

    def test_a_tight_inner_radius_blocks_approval(self) -> None:
        tight = MeanderParameters(
            run_length=12.0, n_runs=4, pitch=1.5, width=1.0, thickness=1.2
        )
        # inner radius = 0.75 - 0.5 = 0.25 mm, below a 0.4 mm nozzle.
        issues = manufacturability_issues(tight, minimum_feature_size=0.4)
        assert any(i.key == "inner_radius_below_minimum" for i in issues)

    def test_a_manufacturable_design_is_auto_approvable(self) -> None:
        report = adapt_to_span(BASE, target_span=16.0, strain_limit=1.0)
        assert report.is_auto_approvable
        assert report.blocking_issues == []

    def test_excessive_strain_blocks_approval(self) -> None:
        report = adapt_to_span(
            BASE, target_span=16.0, joint_angle=math.radians(100.0),
            strain_limit=0.001,
        )
        assert not report.is_auto_approvable
        assert any(i.key == "excessive_strain" for i in report.blocking_issues)

    def test_tight_turn_warning_is_not_blocking(self) -> None:
        issues = manufacturability_issues(
            BASE, minimum_feature_size=0.4, minimum_turn_radius_ratio=5.0
        )
        warnings = [i for i in issues if i.key == "tight_turn_stress_concentration"]
        assert warnings and not warnings[0].blocking


class TestStrainEstimate:
    def test_strain_scales_with_angle_and_width(self) -> None:
        at_50 = required_peak_strain(BASE, math.radians(50.0)).value
        at_100 = required_peak_strain(BASE, math.radians(100.0)).value
        assert at_100 == pytest.approx(2.0 * at_50, rel=1e-12)

        wider = replace(BASE, width=2.0)
        assert required_peak_strain(wider, math.radians(50.0)).value == pytest.approx(
            2.0 * at_50, rel=1e-12
        )

    def test_it_is_tagged_as_an_estimate_with_its_caveat(self) -> None:
        """It must not be mistaken for the FEA peak strain."""
        value = required_peak_strain(BASE, math.radians(90.0))
        assert value.provenance is Provenance.ANALYTICAL_ESTIMATE
        assert any(c.key == "uniform_curvature" for c in value.caveats)

    def test_matches_the_closed_form(self) -> None:
        angle = math.radians(90.0)
        expected = (angle / BASE.centreline_length) * BASE.width / 2.0
        assert required_peak_strain(BASE, angle).value == pytest.approx(expected)


class TestRegenerationFidelity:
    def test_an_exact_volume_passes(self) -> None:
        assert verify_regeneration(BASE, BASE.expected_volume) is None

    def test_a_deficit_is_reported_as_probable_overlap(self) -> None:
        issue = verify_regeneration(BASE, BASE.expected_volume * 0.9)
        assert issue is not None and issue.blocking
        assert "overlapping and fusing" in issue.message

    def test_a_surplus_is_reported_differently(self) -> None:
        issue = verify_regeneration(BASE, BASE.expected_volume * 1.1)
        assert issue is not None
        assert "tabs or another body" in issue.message


@requires_kernel
class TestRegenerationAgainstBuiltSolids:
    """Phase 4 criterion 2, against solids actually built by the template."""

    @pytest.mark.parametrize(
        "parameters",
        [
            BASE,
            replace(BASE, n_runs=3),
            replace(BASE, n_runs=6, pitch=2.5),
            replace(BASE, width=1.4, pitch=4.0),
        ],
        ids=["base", "three-run", "six-run-fine-pitch", "wide-strap"],
    )
    def test_regenerating_reproduces_the_expected_volume(self, parameters) -> None:
        solid = inspect_solid(build_meander(parameters), index=0)
        issue = verify_regeneration(parameters, solid.volume, tolerance=0.005)
        assert issue is None, issue

    def test_an_adapted_design_also_regenerates_cleanly(self) -> None:
        """The adaptation is only trustworthy if its output still builds exactly."""
        report = adapt_to_span(BASE, target_span=20.0, strategy="pitch")
        solid = inspect_solid(build_meander(report.adapted), index=0)
        assert verify_regeneration(report.adapted, solid.volume) is None
        assert solid.is_valid

    def test_the_adapted_solid_really_spans_the_requested_distance(self) -> None:
        """The envelope formula is a prediction; the built solid is the measurement."""
        report = adapt_to_span(BASE, target_span=20.0, strategy="pitch")
        solid = inspect_solid(build_meander(report.adapted), index=0)
        _, measured_y, _ = solid.bounding_box.size
        assert measured_y == pytest.approx(20.0, abs=1e-6)
