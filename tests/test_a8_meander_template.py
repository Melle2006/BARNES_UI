"""A8 meander family template tests.

The A8 strip's section is a fixed rectangle on every y-plane, so its volume is exactly
``width_x * height_z * span`` whatever the plan path or spine -- the analytical check
the generated solid is held to. The path functions are checked against closed forms.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from barnes_ui.core.fea.results import parse_dat_reaction_history
from barnes_ui.core.flexure.templates.a8_meander import (
    A8_PLAN_2TURN,
    A8_PLAN_3TURN,
    A8MeanderError,
    A8MeanderParameters,
    build_a8_meander,
    sine_plan,
)

from conftest import requires_kernel


def _params(**overrides) -> A8MeanderParameters:
    base = dict(plan=sine_plan(3, 4.0), sagitta=1.0, n_turns=3)
    base.update(overrides)
    return A8MeanderParameters(**base)


class TestParameters:
    def test_rejects_negative_sagitta(self) -> None:
        with pytest.raises(A8MeanderError, match="into the finger"):
            _params(sagitta=-0.5)

    def test_rejects_more_than_a_semicircle(self) -> None:
        with pytest.raises(A8MeanderError, match="semicircle"):
            _params(sagitta=20.0)

    def test_sine_plan_lobe_count_follows_the_export_naming(self) -> None:
        """2-turn has three lobes and 3-turn five, so n turns is harmonic 2n - 1."""
        plan = sine_plan(4, 4.0)
        assert plan[2 + 7 - 1] == 4.0
        assert sum(abs(c) for c in plan[2:]) == 4.0

    def test_spine_passes_through_both_ends(self) -> None:
        p = _params(sagitta=2.0)
        z = p.spine_z(np.array([p.y_start, p.y_end]))
        assert z == pytest.approx([p.z_start, p.z_end], abs=1e-9)

    def test_spine_sagitta_is_the_peak_offset_from_the_chord(self) -> None:
        p = _params(sagitta=2.0)
        y = np.linspace(p.y_start, p.y_end, 20001)
        z = p.spine_z(y)
        dy, dz = p.span, p.z_end - p.z_start
        # Perpendicular distance of each spine point from the chord.
        offset = ((y - p.y_start) * dz - (z - p.z_start) * dy) / p.chord_length
        assert np.abs(offset).max() == pytest.approx(2.0, abs=1e-6)

    def test_spine_radius_matches_the_sagitta_formula(self) -> None:
        p = _params(sagitta=1.5)
        half = p.chord_length / 2
        assert p.spine_radius == pytest.approx((1.5 ** 2 + half ** 2) / 3.0)
        assert math.isinf(_params(sagitta=0.0).spine_radius)

    def test_min_true_width_is_width_times_cos_of_steepest_angle(self) -> None:
        """For a pure sine the steepest slope is A * n * pi / span, at the ends."""
        p = _params(plan=sine_plan(3, 4.0))
        slope = 4.0 * 5 * math.pi / p.span
        expected = 2.0 * math.cos(math.atan(slope))
        assert p.path_metrics()["min_true_width_mm"] == pytest.approx(expected, rel=1e-6)

    def test_more_turns_narrow_the_strip(self) -> None:
        widths = [_params(plan=sine_plan(n, 4.0), n_turns=n)
                  .path_metrics()["min_true_width_mm"] for n in (2, 3, 4)]
        assert widths[0] > widths[1] > widths[2]


@requires_kernel
class TestBuiltSolid:
    @pytest.mark.parametrize("plan, n_turns, sagitta", [
        (A8_PLAN_2TURN, 2, 0.751),
        (A8_PLAN_3TURN, 3, 2.173),
        (sine_plan(4, 4.0), 4, 0.0),
    ])
    def test_every_y_slice_is_the_drawn_rectangle(self, plan, n_turns, sagitta) -> None:
        from barnes_ui.core.flexure.section import section_solid

        p = A8MeanderParameters(plan=plan, sagitta=sagitta, n_turns=n_turns)
        shape = build_a8_meander(p)
        for y in np.linspace(p.y_start + 0.2, p.y_end - 0.2, 7):
            sections = section_solid(shape, (0, y, 0), (0, 1, 0), u_hint=(1, 0, 0))
            assert len(sections) == 1
            assert sections[0].area == pytest.approx(p.width_x * p.height_z, rel=2e-3)
            assert sections[0].centroid[0] == pytest.approx(float(p.plan_x(y)), abs=5e-3)
            assert sections[0].centroid[2] == pytest.approx(float(p.spine_z(y)), abs=5e-3)


class TestReactionHistory:
    def test_reads_every_increment_with_its_time(self, tmp_path) -> None:
        dat = tmp_path / "job.dat"
        dat.write_text(
            "\n                        S T E P       1\n\n"
            "                                INCREMENT     1\n\n\n"
            " total force (fx,fy,fz) for set DISTAL_ROT and time  0.1000000E+00\n\n"
            "       -2.000000E-01  1.0E-09  2.0E-07\n\n"
            "                                INCREMENT     2\n\n\n"
            " total force (fx,fy,fz) for set DISTAL_ROT and time  0.2500000E+00\n\n"
            "       -5.500000E-01  1.0E-09  2.0E-07\n",
            encoding="utf-8",
        )
        history = parse_dat_reaction_history(dat)["DISTAL_ROT"]
        assert [t for t, _ in history] == [0.1, 0.25]
        assert [v[0] for _, v in history] == [-0.2, -0.55]

    def test_missing_file_is_empty(self, tmp_path) -> None:
        assert parse_dat_reaction_history(tmp_path / "absent.dat") == {}


class TestPathNormalSection:
    """The printable variant: constant true width, drawn square to the path."""

    def _p(self, **overrides) -> A8MeanderParameters:
        base = dict(plan=sine_plan(3, 3.5), sagitta=3.0, n_turns=3, true_width=1.2,
                    height_z=1.8, y_start=24.0, y_end=53.0, z_start=4.6, z_end=4.25,
                    stations_per_lobe=40)
        base.update(overrides)
        return A8MeanderParameters(**base)

    def test_true_width_is_constant(self) -> None:
        metrics = self._p().path_metrics()
        assert metrics["min_true_width_mm"] == pytest.approx(1.2)
        assert metrics["mean_true_width_mm"] == pytest.approx(1.2)

    def test_refuses_a_width_the_lobe_tip_cannot_hold(self) -> None:
        """A sine of amplitude A over n lobes has tip radius (L / n pi)^2 / A."""
        tip = (29.0 / (5 * math.pi)) ** 2 / 3.5
        with pytest.raises(A8MeanderError, match="fold over itself"):
            self._p(true_width=2.0 * tip + 0.05)

    @requires_kernel
    def test_volume_is_width_times_height_times_length(self) -> None:
        from barnes_ui.core.cad.inspect import volume_properties

        p = self._p(plan=sine_plan(2, 4.4), n_turns=2)
        volume = volume_properties(build_a8_meander(p))[0]
        assert volume == pytest.approx(p.expected_volume, rel=2e-3)

    @requires_kernel
    def test_section_normal_to_the_path_is_the_true_rectangle(self) -> None:
        from barnes_ui.core.flexure.section import section_solid

        p = self._p()
        shape = build_a8_meander(p)
        for y in (30.0, 38.5, 47.0):
            yy = np.array([y])
            tangent = np.array([float(p.plan_slope(yy)[0]), 1.0, float(p.spine_slope(yy)[0])])
            tangent /= np.linalg.norm(tangent)
            centre = np.array([float(p.plan_x(yy)[0]), y, float(p.spine_z(yy)[0])])
            sections = section_solid(shape, tuple(centre), tuple(tangent))
            nearest = min(sections, key=lambda c: np.linalg.norm(np.array(c.centroid) - centre))
            assert nearest.area == pytest.approx(1.2 * 1.8, rel=5e-3)

    @requires_kernel
    def test_end_caps_lie_in_the_collar_planes(self) -> None:
        from barnes_ui.core.cad.inspect import bounding_box

        box = bounding_box(build_a8_meander(self._p()))
        assert box.ymin == pytest.approx(24.0, abs=1e-6)
        assert box.ymax == pytest.approx(53.0, abs=1e-6)
