"""Parametric meander template tests.

The template's value is that its properties are analytically known, so the generated
solid can be checked against arithmetic rather than against previously recorded output.
The volume identity is the strong one: for constant width and butting segments, volume
is exactly ``width * thickness * centreline_length``, because an annular sector of
constant width has area equal to its centreline arc times the width.
"""

from __future__ import annotations

import math

import pytest

from barnes_ui.core.cad.inspect import inspect_solid
from barnes_ui.core.flexure.templates.meander import (
    MeanderError,
    MeanderParameters,
    build_meander,
)

from conftest import requires_kernel


class TestParameterValidation:
    def test_rejects_fewer_than_two_runs(self) -> None:
        with pytest.raises(MeanderError, match="at least 2 runs"):
            MeanderParameters(n_runs=1)

    def test_rejects_width_not_less_than_pitch(self) -> None:
        """Width >= pitch merges adjacent runs into a block, not a meander."""
        with pytest.raises(MeanderError, match="must exceed width"):
            MeanderParameters(pitch=1.0, width=1.0)

    def test_rejects_non_positive_dimensions(self) -> None:
        with pytest.raises(MeanderError, match="must be positive"):
            MeanderParameters(width=0.0)
        with pytest.raises(MeanderError, match="must be positive"):
            MeanderParameters(thickness=-1.0)

    def test_inner_radius_must_be_positive(self) -> None:
        # pitch barely above width leaves a vanishing inner radius.
        with pytest.raises(MeanderError):
            MeanderParameters(pitch=1.0000001, width=1.0)


class TestDerivedGeometry:
    def test_turn_count_is_one_fewer_than_runs(self) -> None:
        assert MeanderParameters(n_runs=4).n_turns == 3

    def test_radii_follow_from_pitch_and_width(self) -> None:
        p = MeanderParameters(pitch=3.0, width=1.0)
        assert p.turn_radius == pytest.approx(1.5)
        assert p.inner_radius == pytest.approx(1.0)
        assert p.outer_radius == pytest.approx(2.0)

    def test_centreline_length_is_runs_plus_semicircles(self) -> None:
        p = MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0, width=1.0)
        expected = 4 * 12.0 + 3 * math.pi * 1.5
        assert p.centreline_length == pytest.approx(expected)

    def test_minimum_feature_is_the_tighter_of_width_and_inner_radius(self) -> None:
        wide = MeanderParameters(pitch=10.0, width=1.0)   # inner radius 4.5
        assert wide.minimum_feature_size == pytest.approx(1.0)
        tight = MeanderParameters(pitch=3.0, width=2.0)   # inner radius 0.5
        assert tight.minimum_feature_size == pytest.approx(0.5)


@requires_kernel
class TestBuiltSolid:
    @pytest.mark.parametrize("n_runs", [2, 3, 4, 6])
    def test_volume_matches_the_analytical_identity(self, n_runs: int) -> None:
        """volume == width * thickness * centreline_length, exactly."""
        p = MeanderParameters(
            run_length=12.0, n_runs=n_runs, pitch=3.0, width=1.0, thickness=1.2
        )
        info = inspect_solid(build_meander(p), 0, "meander")
        assert info.volume == pytest.approx(p.expected_volume, rel=1e-6)

    @pytest.mark.parametrize("width", [0.8, 1.0, 1.5])
    def test_volume_identity_holds_across_widths(self, width: float) -> None:
        p = MeanderParameters(
            run_length=12.0, n_runs=4, pitch=3.0, width=width, thickness=1.2
        )
        info = inspect_solid(build_meander(p), 0, "meander")
        assert info.volume == pytest.approx(p.expected_volume, rel=1e-6)

    def test_envelope_matches_the_predicted_bounding_box(self) -> None:
        """Regression: the first envelope formula used width where it needed
        outer_radius, predicting 13.0 mm where the solid measured 16.0 mm."""
        p = MeanderParameters(
            run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
        )
        info = inspect_solid(build_meander(p), 0, "meander")
        measured = info.bounding_box.size
        for got, expected in zip(measured, p.envelope):
            assert got == pytest.approx(expected, abs=1e-6)

    def test_solid_is_topologically_valid(self) -> None:
        p = MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0, width=1.0)
        assert inspect_solid(build_meander(p), 0, "meander").is_valid

    def test_is_a_single_fused_body(self) -> None:
        """A meander that came out as several bodies did not fuse properly."""
        p = MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0, width=1.0)
        assert inspect_solid(build_meander(p), 0, "meander").counts.solids == 1

    def test_more_turns_means_more_volume(self) -> None:
        base = MeanderParameters(run_length=12.0, n_runs=3, pitch=3.0, width=1.0)
        more = MeanderParameters(run_length=12.0, n_runs=6, pitch=3.0, width=1.0)
        assert more.expected_volume > base.expected_volume
        a = inspect_solid(build_meander(base), 0, "a").volume
        b = inspect_solid(build_meander(more), 0, "b").volume
        assert b > a

    def test_tabs_add_material(self) -> None:
        without = MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0, width=1.0)
        with_tabs = MeanderParameters(
            run_length=12.0, n_runs=4, pitch=3.0, width=1.0,
            tab_length=3.0, tab_width=4.0,
        )
        plain = inspect_solid(build_meander(without), 0, "a").volume
        tabbed = inspect_solid(build_meander(with_tabs), 0, "b").volume
        assert tabbed > plain


class TestAnalyticalCentreline:
    def test_polyline_starts_and_ends_on_the_runs(self) -> None:
        p = MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0, width=1.0)
        points = p.centreline_points()
        assert points[0] == pytest.approx((0.0, 0.0, p.thickness / 2.0))
        # Four runs: the last is index 3, which runs backwards, ending at x = 0.
        assert points[-1][0] == pytest.approx(0.0, abs=1e-9)
        assert points[-1][1] == pytest.approx(3 * p.pitch)

    def test_polyline_length_approaches_the_analytical_value(self) -> None:
        """A dense sample of the analytical path must reproduce its own length."""
        import numpy as np

        p = MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0, width=1.0)
        points = np.array(p.centreline_points(per_run=400, per_turn=400))
        length = float(np.sum(np.linalg.norm(np.diff(points, axis=0), axis=1)))
        assert length == pytest.approx(p.centreline_length, rel=1e-4)
