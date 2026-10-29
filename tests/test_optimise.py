"""Phase 7: sweeps, Pareto fronts, sensitivity and experimental validation.

Criterion 1 is tested by running the same design through the individual path and the
sweep path and comparing value for value -- the usual way that equivalence breaks is
a default applied on one path and not the other, which a comparison of outputs
catches and a reading of the code does not.

Criterion 5 cannot be met here: it needs a physical measurement, and no specimen has
been tested. What is tested is the machinery that will close it, including that the
gate refuses to issue the validated tag without agreement.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from barnes_ui.core.flexure.templates.meander import MeanderParameters
from barnes_ui.core.material.calibration import (
    CalibrationError,
    MeasurementSeries,
    compare_with_measurement,
)
from barnes_ui.core.optimise.objectives import (
    DesignPoint,
    InvalidDesignError,
    OptimisationError,
    STANDARD_OBJECTIVES,
    centreline_length,
    evaluate_design,
    material_volume,
    require_valid,
    stiffness_from,
)
from barnes_ui.core.optimise.pareto import dominates, pareto_front
from barnes_ui.core.optimise.sensitivity import (
    MaterialRange,
    modulus_sensitivity,
)
from barnes_ui.core.optimise.sweep import SweepAxis, run_sweep
from barnes_ui.core.provenance import Provenance, TaggedValue


BASE = MeanderParameters(
    run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
)


def rom_stiffness(modulus: float = 12.0):
    """A stand-in reduced-order stiffness: linear in E and in the section's I.

    Not the real curved-beam solver -- that needs CAD geometry -- but it has the
    property the sensitivity analysis turns on, namely exact linearity in the
    modulus, so it is the right object to test that reasoning with.
    """

    def evaluate(parameters: MeanderParameters) -> TaggedValue:
        inertia = parameters.thickness * parameters.width ** 3 / 12.0
        value = modulus * inertia / parameters.centreline_length
        return TaggedValue(
            value, "N.mm/rad", Provenance.REDUCED_ORDER_PREDICTION,
            label="stand-in reduced-order stiffness",
        )

    return evaluate


# ------------------------------------------------------------------- sweeps


class TestSweep:
    def test_a_sweep_reproduces_the_individual_analysis(self) -> None:
        """Phase 7 criterion 1, compared value for value rather than by eye."""
        objectives = list(STANDARD_OBJECTIVES)
        axis = SweepAxis("width", (0.8, 1.0, 1.2))

        swept = run_sweep(BASE, [axis], objectives)
        from dataclasses import replace

        for width in axis.values:
            individually = evaluate_design(
                DesignPoint(replace(BASE, width=width)), objectives
            )
            match = next(
                e for e in swept.evaluations
                if e.design.parameters.width == width
            )
            assert match.is_valid == individually.is_valid
            for objective in objectives:
                assert match.value(objective.name) == pytest.approx(
                    individually.value(objective.name), rel=0.0, abs=0.0
                )

    def test_the_grid_is_the_full_product(self) -> None:
        result = run_sweep(
            BASE,
            [SweepAxis("width", (0.8, 1.0)), SweepAxis("n_runs", (4, 6, 8))],
            list(STANDARD_OBJECTIVES),
        )
        assert len(result.evaluations) + len(result.rejected) == 6

    def test_unbuildable_combinations_are_reported_not_raised(self) -> None:
        """A pitch below the width is the edge of the design space, not a crash."""
        result = run_sweep(
            BASE,
            [SweepAxis("pitch", (0.5, 3.0, 5.0))],
            list(STANDARD_OBJECTIVES),
        )
        assert result.rejected
        assert len(result.evaluations) == 2

    def test_inadmissible_points_are_kept_and_excluded_from_ranking(self) -> None:
        result = run_sweep(
            BASE,
            [SweepAxis("width", (0.2, 1.0, 1.4))],
            list(STANDARD_OBJECTIVES),
            minimum_feature_size=0.4,
        )
        assert len(result.invalid) == 1
        assert len(result.valid) == 2
        assert "inadmissible" in result.summary()

    def test_the_sweep_reports_the_weakest_provenance_it_contains(self) -> None:
        objectives = list(STANDARD_OBJECTIVES) + [
            stiffness_from(rom_stiffness())
        ]
        result = run_sweep(BASE, [SweepAxis("width", (0.9, 1.0))], objectives)
        assert result.provenance is Provenance.REDUCED_ORDER_PREDICTION

    def test_a_geometry_only_sweep_stays_a_measurement(self) -> None:
        result = run_sweep(
            BASE, [SweepAxis("width", (0.9, 1.0))], list(STANDARD_OBJECTIVES)
        )
        assert result.provenance is Provenance.GEOMETRIC_MEASUREMENT

    def test_single_objective_best_picks_the_valid_extremum(self) -> None:
        objective = material_volume()
        result = run_sweep(BASE, [SweepAxis("width", (0.8, 1.0, 1.2))], [objective])
        assert result.best(objective).design.parameters.width == 0.8

    def test_an_unsweepable_parameter_is_refused(self) -> None:
        with pytest.raises(OptimisationError, match="not a sweepable"):
            SweepAxis("turn_radius", (1.0, 2.0))

    def test_a_sweep_with_no_objectives_is_refused(self) -> None:
        with pytest.raises(OptimisationError, match="at least one objective"):
            run_sweep(BASE, [SweepAxis("width", (1.0,))], [])

    def test_two_axes_on_one_parameter_are_refused(self) -> None:
        with pytest.raises(OptimisationError, match="same parameter"):
            run_sweep(
                BASE,
                [SweepAxis("width", (1.0,)), SweepAxis("width", (1.2,))],
                list(STANDARD_OBJECTIVES),
            )


# ------------------------------------------------------------- validity gate


class TestValidityGate:
    def test_an_inadmissible_design_will_not_be_optimised_over(self) -> None:
        """Phase 7 criterion 2."""
        thin = DesignPoint(
            MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0,
                              width=0.2, thickness=1.2)
        )
        evaluation = evaluate_design(thin, list(STANDARD_OBJECTIVES))
        assert not evaluation.is_valid
        with pytest.raises(InvalidDesignError, match="has no ranking"):
            require_valid(evaluation)

    def test_a_valid_design_passes_the_gate_unchanged(self) -> None:
        evaluation = evaluate_design(DesignPoint(BASE), list(STANDARD_OBJECTIVES))
        assert require_valid(evaluation) is evaluation

    def test_objectives_are_still_computed_for_an_invalid_design(self) -> None:
        """The numbers explain *why* a region is inadmissible; the flag stops it
        being ranked."""
        thin = DesignPoint(
            MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0,
                              width=0.2, thickness=1.2)
        )
        evaluation = evaluate_design(thin, list(STANDARD_OBJECTIVES))
        assert evaluation.value("material_volume") > 0.0


# ------------------------------------------------------------- Pareto fronts


class TestParetoFront:
    def _sweep(self):
        # Volume (minimise) and centreline length (maximise) conflict directly:
        # a longer centreline is more material.
        return run_sweep(
            BASE,
            [SweepAxis("n_runs", (4, 5, 6, 7, 8))],
            [material_volume(), centreline_length()],
        )

    def test_conflicting_objectives_give_a_front_not_a_winner(self) -> None:
        """Phase 7 criterion 3."""
        front = pareto_front(
            self._sweep().evaluations, [material_volume(), centreline_length()]
        )
        assert front.size > 1
        assert front.objectives_conflict
        with pytest.raises(OptimisationError, match="no best one"):
            front.winner()

    def test_a_single_objective_does_have_a_winner(self) -> None:
        objective = material_volume()
        result = run_sweep(BASE, [SweepAxis("n_runs", (4, 5, 6))], [objective])
        front = pareto_front(result.evaluations, [objective])
        assert front.size == 1
        assert front.winner().design.parameters.n_runs == 4

    def test_weights_must_be_given_for_every_objective(self) -> None:
        objectives = [material_volume(), centreline_length()]
        front = pareto_front(self._sweep().evaluations, objectives)
        with pytest.raises(OptimisationError, match="implicit zero"):
            front.best_by_weights({"material_volume": 1.0})

    def test_explicit_weights_do_choose_a_member(self) -> None:
        objectives = [material_volume(), centreline_length()]
        front = pareto_front(self._sweep().evaluations, objectives)
        light = front.best_by_weights(
            {"material_volume": 1.0, "centreline_length": 0.0}
        )
        compliant = front.best_by_weights(
            {"material_volume": 0.0, "centreline_length": 1.0}
        )
        assert light.design.parameters.n_runs < compliant.design.parameters.n_runs

    def test_dominance_is_strict(self) -> None:
        objectives = [material_volume()]
        evaluations = run_sweep(
            BASE, [SweepAxis("n_runs", (4, 6))], objectives
        ).evaluations
        small, large = sorted(
            evaluations, key=lambda e: e.value("material_volume")
        )
        assert dominates(small, large, objectives)
        assert not dominates(large, small, objectives)
        assert not dominates(small, small, objectives)

    def test_invalid_designs_are_excluded_before_ranking(self) -> None:
        result = run_sweep(
            BASE, [SweepAxis("width", (0.2, 1.0, 1.4))], [material_volume()]
        )
        front = pareto_front(result.evaluations, [material_volume()])
        assert front.excluded_invalid == 1
        # The 0.2 mm design has the smallest volume and must not win anyway.
        assert front.winner().design.parameters.width == 1.0

    def test_an_empty_front_refuses_to_name_a_winner(self) -> None:
        front = pareto_front([], [material_volume()])
        with pytest.raises(OptimisationError, match="empty"):
            front.winner()


# -------------------------------------------------------------- sensitivity


class TestSensitivity:
    def _search(self, objectives):
        def search(modulus: float):
            local = list(objectives) + [stiffness_from(rom_stiffness(modulus))]
            return run_sweep(
                BASE, [SweepAxis("n_runs", (4, 6, 8))], local
            ).evaluations
        return search

    def test_a_range_needs_a_stated_source(self) -> None:
        with pytest.raises(OptimisationError, match="stated source"):
            MaterialRange(low=8.0, nominal=12.0, high=18.0, source="  ")

    def test_an_out_of_order_range_is_refused(self) -> None:
        with pytest.raises(OptimisationError, match="low < nominal < high"):
            MaterialRange(low=14.0, nominal=12.0, high=18.0, source="x")

    def test_the_front_is_invariant_under_modulus_uncertainty(self) -> None:
        """The finding the whole module exists to make quantitative.

        Every objective here is either purely geometric or linear in the modulus, so
        a modulus change scales one axis uniformly and cannot reorder anything.
        Design selection is therefore available before the material is calibrated.
        """
        objectives = [material_volume(), centreline_length()]
        report = modulus_sensitivity(
            self._search(objectives),
            objectives + [stiffness_from(rom_stiffness())],
            MaterialRange(low=8.0, nominal=12.0, high=18.0,
                          source="supplier range for TPU 90A filaments"),
        )
        assert report.front_is_invariant
        assert "IDENTICAL at every modulus" in report.summary()

    def test_geometric_objectives_do_not_move_at_all(self) -> None:
        objectives = [material_volume(), centreline_length()]
        report = modulus_sensitivity(
            self._search(objectives), objectives,
            MaterialRange(low=8.0, nominal=12.0, high=18.0, source="supplier range"),
        )
        shifts = report.optimum_shift()
        assert shifts["material_volume"] == pytest.approx(0.0)
        assert shifts["centreline_length"] == pytest.approx(0.0)

    def test_a_modulus_dependent_objective_moves_with_the_modulus(self) -> None:
        """Criterion 4's number: how far the chosen design's value shifts.

        For a quantity linear in E, over 8 to 18 MPa about a nominal 12, the
        half-spread is (18 - 8) / (2 * 13) = 38 per cent of the mean -- not of the
        nominal, since the three cases are averaged. The point of the assertion is
        that the shift is large and reported, not that it is any particular figure.
        """
        objectives = [material_volume()]
        stiffness = stiffness_from(rom_stiffness())
        report = modulus_sensitivity(
            self._search(objectives), objectives + [stiffness],
            MaterialRange(low=8.0, nominal=12.0, high=18.0, source="supplier range"),
        )
        shifts = report.optimum_shift()
        assert shifts["rotational_stiffness"] > 0.3
        assert shifts["material_volume"] == pytest.approx(0.0)

    def test_the_report_carries_its_own_caveat(self) -> None:
        objectives = [material_volume()]
        report = modulus_sensitivity(
            self._search(objectives), objectives,
            MaterialRange(low=8.0, nominal=12.0, high=18.0, source="supplier range"),
        )
        assert "itself an assumption" in report.summary()


# ------------------------------------------------- experimental validation


class TestMeasurementSeries:
    def _series(self, **changes):
        angles = np.linspace(0.0, math.radians(60.0), 13)
        defaults = dict(
            angles=angles, torques=6.1 * angles + 3.0 * angles ** 3,
            specimen_id="A3-print-004", uncertainty=0.05,
            method="Instron 3345, 10 N load cell, 5 mm/min, custom PIP fixture",
            measured_on=date(2026, 10, 27),
        )
        defaults.update(changes)
        return MeasurementSeries(**defaults)

    def test_a_series_without_a_specimen_id_is_refused(self) -> None:
        with pytest.raises(CalibrationError, match="specimen identifier"):
            self._series(specimen_id="  ")

    def test_a_series_without_a_method_is_refused(self) -> None:
        with pytest.raises(CalibrationError, match="how it was taken"):
            self._series(method="")

    def test_a_series_without_an_uncertainty_is_refused(self) -> None:
        with pytest.raises(CalibrationError, match="cannot be agreed with"):
            self._series(uncertainty=0.0)

    def test_unsorted_angles_are_refused_with_the_hysteresis_explanation(self) -> None:
        angles = np.array([0.0, 0.5, 0.3, 0.9])
        with pytest.raises(CalibrationError, match="hysteresis"):
            self._series(angles=angles, torques=np.array([0.0, 3.0, 2.0, 6.0]))

    def test_it_will_not_report_outside_its_own_range(self) -> None:
        series = self._series()
        with pytest.raises(CalibrationError, match="cannot report a torque"):
            series.torque_at(math.radians(90.0))


class TestValidationGate:
    def _measured(self):
        angles = np.linspace(0.0, math.radians(60.0), 13)
        return MeasurementSeries(
            angles=angles, torques=6.1 * angles + 3.0 * angles ** 3,
            specimen_id="A3-print-004", uncertainty=0.05,
            method="Instron 3345, 10 N load cell, 5 mm/min",
        )

    def test_an_agreeing_prediction_can_be_retagged(self) -> None:
        """Phase 7 criterion 6: this is the one route to the tag."""
        measurement = self._measured()
        angles = measurement.angles
        report = compare_with_measurement(
            angles, 1.01 * measurement.torques, measurement,
            tolerance=0.05, prediction_label="FEA at 0.5 mm elements",
            prediction_provenance=Provenance.FEA_RESULT,
        )
        assert report.agrees
        validated = report.validated(
            TaggedValue(6.1, "N.mm/rad", Provenance.FEA_RESULT), angles[-1]
        )
        assert validated.provenance is Provenance.EXPERIMENTALLY_VALIDATED
        assert any(c.key == "single_specimen" for c in validated.caveats)

    def test_a_disagreeing_prediction_cannot_be_retagged(self) -> None:
        measurement = self._measured()
        report = compare_with_measurement(
            measurement.angles, 1.4 * measurement.torques, measurement,
            tolerance=0.05, prediction_label="reduced-order",
        )
        assert not report.agrees
        assert report.bias > 0.0
        assert "systematically stiff" in report.summary()
        with pytest.raises(CalibrationError, match="is not a validation"):
            report.validated(
                TaggedValue(7.5, "N.mm/rad", Provenance.REDUCED_ORDER_PREDICTION),
                measurement.angles[-1],
            )

    def test_the_tag_cannot_travel_past_the_measured_range(self) -> None:
        measurement = self._measured()
        report = compare_with_measurement(
            measurement.angles, measurement.torques, measurement,
            tolerance=0.05, prediction_label="exact",
        )
        with pytest.raises(CalibrationError, match="beyond its own evidence"):
            report.validated(
                TaggedValue(20.0, "N.mm", Provenance.FEA_RESULT),
                math.radians(90.0),
            )

    def test_agreement_inside_the_rig_uncertainty_is_said_out_loud(self) -> None:
        measurement = self._measured()
        report = compare_with_measurement(
            measurement.angles, 1.01 * measurement.torques, measurement,
            tolerance=0.1, prediction_label="FEA",
        )
        assert report.within_measurement_uncertainty
        assert "cannot distinguish the model from the part" in report.summary()

    def test_points_outside_the_measured_range_are_dropped_not_extrapolated(
        self
    ) -> None:
        measurement = self._measured()
        angles = np.linspace(0.0, math.radians(90.0), 19)
        report = compare_with_measurement(
            angles, 6.1 * angles, measurement, tolerance=0.5,
            prediction_label="over-wide prediction",
        )
        assert report.angles.max() <= measurement.range[1] + 1e-12
        assert "excluded from the comparison" in report.summary()

    def test_a_tolerance_must_be_stated(self) -> None:
        measurement = self._measured()
        with pytest.raises(CalibrationError, match="between 0 and 1"):
            compare_with_measurement(
                measurement.angles, measurement.torques, measurement,
                tolerance=0.0, prediction_label="x",
            )

    def test_a_non_overlapping_prediction_has_nothing_to_compare(self) -> None:
        measurement = self._measured()
        angles = np.linspace(math.radians(80.0), math.radians(90.0), 5)
        with pytest.raises(CalibrationError, match="nothing to compare"):
            compare_with_measurement(
                angles, 6.1 * angles, measurement, tolerance=0.05,
                prediction_label="out of range",
            )
