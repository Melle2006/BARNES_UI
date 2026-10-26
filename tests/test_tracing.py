"""Path-following centreline tracing tests.

Validated against the generated meander, whose centreline is known analytically. This
is the only place in the project where the true answer is available exactly, which makes
it the right place to establish how accurate the extraction actually is.
"""

from __future__ import annotations

import numpy as np
import pytest

from barnes_ui.core.flexure.centerline import CenterlineError, extract_members
from barnes_ui.core.flexure.templates.meander import MeanderParameters, build_meander
from barnes_ui.core.flexure.tracing import (
    TraceError,
    seed_from_extreme_point,
    trace_centerline,
)

from conftest import requires_kernel

PARAMS = MeanderParameters(
    run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
)


@pytest.fixture(scope="module")
def meander():
    pytest.importorskip("OCP")
    return build_meander(PARAMS)


def _trace(shape, step: float = 0.1):
    return trace_centerline(
        shape,
        seed_point=(0.3, 0.0, PARAMS.thickness / 2.0),
        seed_direction=(1.0, 0.0, 0.0),
        bending_axis=(1.0, 0.0, 0.0),
        step=step,
    )


def _deviation_from_truth(positions: np.ndarray) -> np.ndarray:
    truth = np.array(PARAMS.centreline_points(per_run=800, per_turn=800))
    return np.linalg.norm(
        positions[:, None, :] - truth[None, :, :], axis=2
    ).min(axis=1)


@requires_kernel
class TestTracingAccuracy:
    def test_follows_the_analytical_centreline_closely(self, meander) -> None:
        """Every traced station must sit on the true centreline.

        0.02 mm is 2 per cent of the 1 mm strap width, which is the tolerance that
        matters -- a station off the centreline takes its section with it.
        """
        deviation = _deviation_from_truth(_trace(meander).positions())
        assert deviation.max() < 0.02

    def test_arc_length_matches_the_analytical_value(self, meander) -> None:
        """Within the length the trace can actually reach.

        The seed is inset 0.3 mm from the start and the march stops up to one step
        short of the far end, so those are subtracted rather than counted as error.
        """
        step = 0.1
        member = _trace(meander, step=step)
        reachable = PARAMS.centreline_length - 0.3 - step
        assert member.arc_length == pytest.approx(reachable, rel=0.005)

    def test_section_area_matches_the_true_section(self, meander) -> None:
        areas = _trace(meander).area_profile()
        true_area = PARAMS.width * PARAMS.thickness
        assert areas.mean() == pytest.approx(true_area, rel=0.01)
        assert areas.min() == pytest.approx(true_area, rel=0.01)

    def test_accuracy_improves_with_a_smaller_step(self, meander) -> None:
        coarse = _deviation_from_truth(_trace(meander, step=0.4).positions()).max()
        fine = _deviation_from_truth(_trace(meander, step=0.1).positions()).max()
        assert fine <= coarse

    def test_traverses_every_run(self, meander) -> None:
        """All four runs, so the trace went round every turn rather than stopping."""
        positions = _trace(meander).positions()
        for run in range(PARAMS.n_runs):
            y = run * PARAMS.pitch
            assert np.any(np.abs(positions[:, 1] - y) < 0.1), f"run at y={y} missed"

    def test_reaches_the_turn_extremes(self, meander) -> None:
        """Turn centrelines bulge one turn_radius beyond the straight runs."""
        positions = _trace(meander).positions()
        assert positions[:, 0].min() == pytest.approx(
            -PARAMS.turn_radius, abs=0.05
        )
        assert positions[:, 0].max() == pytest.approx(
            PARAMS.run_length + PARAMS.turn_radius, abs=0.05
        )

    def test_sections_carry_an_inertia_tensor(self, meander) -> None:
        """Required by the spatial model; absence would fail only much later."""
        for station in _trace(meander, step=0.4).stations:
            assert station.section.inertia_tensor is not None


@requires_kernel
class TestTracingGuards:
    def test_continuity_guard_stops_a_jump_to_a_neighbouring_run(self, meander) -> None:
        """Regression for the one bad step at the far end.

        Without this guard the march jumped 3.0133 mm -- exactly one pitch -- onto the
        adjacent run at station 308 of 310, travelling 28.8 mm backwards along the true
        centreline and inflating the reported arc length by over 4 per cent.
        """
        member = _trace(meander, step=0.2)
        assert any("different part of the member" in note for note in member.notes)

    def test_no_station_jumps_further_than_the_step_allows(self, meander) -> None:
        step = 0.2
        positions = _trace(meander, step=step).positions()
        advances = np.linalg.norm(np.diff(positions, axis=0), axis=1)
        assert advances.max() <= 2.0 * step

    def test_seed_off_the_solid_raises(self, meander) -> None:
        with pytest.raises(TraceError, match="No cross-section at the seed"):
            trace_centerline(
                meander, seed_point=(500.0, 500.0, 500.0),
                seed_direction=(1.0, 0.0, 0.0), bending_axis=(1.0, 0.0, 0.0),
            )

    def test_step_limit_raises_rather_than_returning_a_partial_trace(
        self, meander
    ) -> None:
        """A trace that does not terminate has gone somewhere unintended."""
        with pytest.raises(TraceError, match="did not terminate"):
            trace_centerline(
                meander, seed_point=(0.3, 0.0, PARAMS.thickness / 2.0),
                seed_direction=(1.0, 0.0, 0.0), bending_axis=(1.0, 0.0, 0.0),
                step=0.05, max_steps=20,
            )

    def test_seed_helper_lands_on_the_solid(self, meander) -> None:
        point, direction = seed_from_extreme_point(meander, (1.0, 0.0, 0.0), inset=0.5)
        assert direction == pytest.approx(np.array([1.0, 0.0, 0.0]))
        assert np.isfinite(point).all()


@requires_kernel
class TestAxisSweepRefusesMeanders:
    """The guard added after the axis sweep silently produced nonsense on a meander."""

    def test_axis_sweep_is_refused(self, meander) -> None:
        """It used to return no error while overstating I by 4x.

        Reported section area overstated 3.1x, second moment 4x, and an arc length of
        1.61 mm against a true centreline of 62.14 mm -- with nothing flagged. The
        region count never varies on a meander, so the original guard never fired.
        """
        with pytest.raises(CenterlineError):
            extract_members(
                meander, sweep_axis=(0, 1, 0), bending_axis=(1, 0, 0),
                start=0.0, end=9.5, samples=40,
            )

    def test_refusal_points_at_the_tracer(self, meander) -> None:
        with pytest.raises(CenterlineError, match="trace_centerline"):
            extract_members(
                meander, sweep_axis=(0, 1, 0), bending_axis=(1, 0, 0),
                start=0.0, end=9.5, samples=40,
            )

    def test_axis_sweep_still_works_on_a_simple_bar(self) -> None:
        """The new guard must not block the geometry it was always correct for."""
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt

        bar = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 2.0, 30.0, 1.0).Shape()
        members = extract_members(
            bar, sweep_axis=(0, 1, 0), bending_axis=(1, 0, 0),
            start=2.0, end=28.0, samples=30,
        )
        assert len(members) == 1
        assert members[0].arc_length == pytest.approx(26.0, rel=1e-3)
