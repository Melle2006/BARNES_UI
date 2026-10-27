"""Comparing a prediction against a physical measurement, and the one way a value
becomes ``EXPERIMENTALLY_VALIDATED``.

Phase 7 criteria 5 and 6. This module is the only place in the codebase that produces
the ``EXPERIMENTALLY_VALIDATED`` tag, and ``tests/test_architecture.py`` asserts that
it stays the only place. Every other route into that tag is a bug, because the tag
means a human compared a prediction against a measured part and nothing a program does
by itself can make that true.

The gate
--------

:meth:`ValidationReport.validated` is the gate. It hands back a retagged value only
when

* a real :class:`MeasurementSeries` was supplied, with a specimen identifier and a
  description of how it was measured;
* the prediction agreed with it within the tolerance the caller stated *before*
  seeing the result; and
* the value being retagged lies inside the angular range the measurement covered.

The third condition is the one that is easy to forget. A prediction validated from 0
to 40 degrees is not validated at 90, and a tag that travelled past the end of its own
evidence would be worse than no tag at all.

Status as of this commit
------------------------

**Nothing in this project is experimentally validated.** No specimen has been tested;
item 7 of docs/06-required-inputs.md is still open. This module is the machinery that
closes criterion 5 when data arrives, and until then the honest state of criterion 5
is "not met, blocked on a physical measurement" -- which is what the development plan
says.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

import numpy as np

from ..provenance import Caveat, Provenance, TaggedValue

logger = logging.getLogger(__name__)

__all__ = [
    "MeasurementSeries",
    "ValidationReport",
    "CalibrationError",
    "compare_with_measurement",
    "CAVEAT_SINGLE_SPECIMEN",
]


CAVEAT_SINGLE_SPECIMEN = Caveat(
    "single_specimen",
    "Validated against a single specimen. Printed parts vary with orientation, "
    "layer adhesion and machine, so one agreement is evidence about one part, not "
    "about the design.",
)


class CalibrationError(ValueError):
    """Measurement data that cannot be used, or a validation that cannot be made."""


@dataclass
class MeasurementSeries:
    """A measured torque-angle curve from a physical specimen.

    Every field in the provenance block is required. A measurement with no specimen
    identifier cannot be re-measured, a measurement with no rig description cannot be
    judged, and a measurement with no uncertainty cannot be agreed or disagreed with
    -- "within 8 per cent" means nothing if the rig is worth 15.
    """

    angles: np.ndarray
    torques: np.ndarray
    #: Which physical part this is. A serial number, a print job, anything unique.
    specimen_id: str
    #: How it was measured: rig, fixture, load cell, rate.
    method: str
    #: Measurement uncertainty on the torque, as a fraction of reading.
    uncertainty: float
    measured_on: date | None = None
    operator: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.angles = np.asarray(self.angles, dtype=float)
        self.torques = np.asarray(self.torques, dtype=float)
        if self.angles.shape != self.torques.shape:
            raise CalibrationError(
                f"{self.angles.size} angles but {self.torques.size} torques."
            )
        if self.angles.size < 3:
            raise CalibrationError(
                "A measured curve needs at least three points to be compared "
                "against a prediction over a range."
            )
        if np.any(np.diff(self.angles) <= 0.0):
            raise CalibrationError(
                "Measured angles must be strictly increasing. Sort the series, or "
                "split a loading and unloading branch into two series -- they are "
                "different curves, and the difference between them is the hysteresis "
                "this project's purely hyperelastic model does not represent."
            )
        if not self.specimen_id.strip():
            raise CalibrationError(
                "A measurement needs a specimen identifier. Without one the result "
                "cannot be reproduced, and an irreproducible measurement cannot "
                "validate anything."
            )
        if not self.method.strip():
            raise CalibrationError(
                "A measurement needs a description of how it was taken: rig, "
                "fixture, load cell, rate."
            )
        if not 0.0 < self.uncertainty < 1.0:
            raise CalibrationError(
                f"Measurement uncertainty must be a fraction strictly between 0 and "
                f"1, got {self.uncertainty}. A measurement with no stated "
                "uncertainty cannot be agreed with."
            )

    @property
    def range(self) -> tuple[float, float]:
        return (float(self.angles[0]), float(self.angles[-1]))

    @property
    def range_degrees(self) -> tuple[float, float]:
        low, high = self.range
        return (math.degrees(low), math.degrees(high))

    def covers(self, angle: float, tolerance: float = 1.0e-9) -> bool:
        low, high = self.range
        return low - tolerance <= angle <= high + tolerance

    def torque_at(self, angle: float) -> float:
        if not self.covers(angle):
            low, high = self.range_degrees
            raise CalibrationError(
                f"Specimen {self.specimen_id} was measured from {low:.1f} to "
                f"{high:.1f} deg and cannot report a torque at "
                f"{math.degrees(angle):.1f} deg."
            )
        return float(np.interp(angle, self.angles, self.torques))

    def describe(self) -> str:
        low, high = self.range_degrees
        when = f" on {self.measured_on.isoformat()}" if self.measured_on else ""
        return (
            f"Specimen {self.specimen_id}{when}: {self.angles.size} points from "
            f"{low:.1f} to {high:.1f} deg, uncertainty "
            f"+/-{self.uncertainty * 100:.1f} % of reading. {self.method}"
        )


@dataclass
class ValidationReport:
    """A prediction set beside a measurement, and the verdict.

    A failing report is a result, not an error. "The model is 40 per cent stiff
    against the printed part" is the single most useful sentence this project could
    produce, and it has to be as easy to record as agreement is.
    """

    measurement: MeasurementSeries
    prediction_label: str
    #: Angles the comparison was made at, within the measured range.
    angles: np.ndarray
    predicted: np.ndarray
    measured: np.ndarray
    #: Agreement required, as a fraction of the measured full scale.
    tolerance: float
    #: Provenance of the prediction being checked, carried into the verdict.
    prediction_provenance: Provenance = Provenance.REDUCED_ORDER_PREDICTION
    notes: list[str] = field(default_factory=list)

    @property
    def full_scale(self) -> float:
        return float(np.max(np.abs(self.measured)))

    @property
    def residuals(self) -> np.ndarray:
        return self.predicted - self.measured

    @property
    def max_relative_error(self) -> float:
        """Worst disagreement, relative to measured full scale.

        Full scale rather than point by point, for the same reason the joint spring
        uses it: the curve passes through zero.
        """
        if self.full_scale <= 0.0:
            raise CalibrationError(
                "Every measured torque is zero, so there is no scale to compare "
                "against."
            )
        return float(np.max(np.abs(self.residuals)) / self.full_scale)

    @property
    def rms_relative_error(self) -> float:
        return float(
            np.sqrt(np.mean(self.residuals ** 2)) / self.full_scale
        )

    @property
    def bias(self) -> float:
        """Mean signed error as a fraction of full scale.

        Separated from the magnitude because the two mean different things. A large
        bias with small scatter says the model is systematically stiff or soft, which
        usually points at the material or a boundary condition. Small bias with large
        scatter points at the measurement.
        """
        return float(np.mean(self.residuals) / self.full_scale)

    @property
    def within_measurement_uncertainty(self) -> bool:
        """Whether the disagreement is smaller than the rig's own uncertainty.

        When it is, the comparison cannot distinguish the model from the part, and
        claiming agreement "to 2 per cent" on a rig worth 5 per cent would be
        inventing precision.
        """
        return self.max_relative_error <= self.measurement.uncertainty

    @property
    def agrees(self) -> bool:
        return self.max_relative_error <= self.tolerance

    def validated(self, value: TaggedValue, at_angle: float) -> TaggedValue:
        """Retag a predicted value as ``EXPERIMENTALLY_VALIDATED``.

        **The only route to that tag in the codebase.** Refuses when the comparison
        did not agree, and refuses when ``at_angle`` lies outside the range the
        specimen was actually measured over -- evidence does not extend past its own
        data.
        """
        if not self.agrees:
            raise CalibrationError(
                f"{self.prediction_label} disagrees with specimen "
                f"{self.measurement.specimen_id} by "
                f"{self.max_relative_error * 100:.2f} % of full scale, above the "
                f"{self.tolerance * 100:.1f} % the caller required. A disagreeing "
                "comparison is a result worth recording and is not a validation."
            )
        if not self.measurement.covers(at_angle):
            low, high = self.measurement.range_degrees
            raise CalibrationError(
                f"The measurement covers {low:.1f} to {high:.1f} deg, so it cannot "
                f"validate a value at {math.degrees(at_angle):.1f} deg. A tag that "
                "travels beyond its own evidence is worse than no tag."
            )
        caveats = tuple(value.caveats) + (CAVEAT_SINGLE_SPECIMEN,)
        return TaggedValue(
            value=value.value,
            unit=value.unit,
            provenance=Provenance.EXPERIMENTALLY_VALIDATED,
            caveats=caveats,
            label=(
                f"{value.label or self.prediction_label} "
                f"(validated against {self.measurement.specimen_id})"
            ),
        )

    def summary(self) -> str:
        low, high = self.measurement.range_degrees
        verdict = "AGREES" if self.agrees else "DISAGREES"
        lines = [
            f"{self.prediction_label} vs {self.measurement.specimen_id}: {verdict}",
            f"  compared at {self.angles.size} angles from {low:.1f} to "
            f"{high:.1f} deg, against {self.full_scale:.4g} N.mm full scale",
            f"  worst {self.max_relative_error * 100:+.2f} %, "
            f"RMS {self.rms_relative_error * 100:.2f} %, "
            f"bias {self.bias * 100:+.2f} % "
            f"(tolerance {self.tolerance * 100:.1f} %)",
            f"  measurement uncertainty "
            f"+/-{self.measurement.uncertainty * 100:.1f} % of reading",
        ]
        if self.agrees and self.within_measurement_uncertainty:
            lines.append(
                "  The disagreement is smaller than the rig's own uncertainty, so "
                "this comparison cannot distinguish the model from the part. That is "
                "the best outcome available and it is not the same as the model "
                "being right to that figure."
            )
        if not self.agrees:
            direction = "stiff" if self.bias > 0 else "soft"
            lines.append(
                f"  The prediction is systematically {direction}. Recording this is "
                "the point of the comparison; it is not a failure of the exercise."
            )
        lines.append(f"  {self.measurement.describe()}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


def compare_with_measurement(
    predicted_at: "Sequence[float] | np.ndarray",
    predicted_torques: "Sequence[float] | np.ndarray",
    measurement: MeasurementSeries,
    tolerance: float,
    prediction_label: str,
    prediction_provenance: Provenance = Provenance.REDUCED_ORDER_PREDICTION,
) -> ValidationReport:
    """Compare a predicted curve against a measured one over their shared range.

    ``tolerance`` must be stated by the caller. There is no default, because a
    default tolerance is one chosen after seeing the answer.
    """
    angles = np.asarray(predicted_at, dtype=float)
    torques = np.asarray(predicted_torques, dtype=float)
    if angles.shape != torques.shape:
        raise CalibrationError(
            f"{angles.size} predicted angles but {torques.size} torques."
        )
    if not 0.0 < tolerance < 1.0:
        raise CalibrationError(
            f"Tolerance must be a fraction strictly between 0 and 1, got {tolerance}."
        )

    inside = np.array([measurement.covers(a) for a in angles])
    if not inside.any():
        low, high = measurement.range_degrees
        raise CalibrationError(
            f"None of the predicted angles fall inside the measured range "
            f"{low:.1f} to {high:.1f} deg, so there is nothing to compare."
        )

    angles = angles[inside]
    torques = torques[inside]
    measured = np.array([measurement.torque_at(a) for a in angles])

    report = ValidationReport(
        measurement=measurement,
        prediction_label=prediction_label,
        angles=angles,
        predicted=torques,
        measured=measured,
        tolerance=float(tolerance),
        prediction_provenance=prediction_provenance,
    )
    dropped = int((~inside).sum())
    if dropped:
        report.notes.append(
            f"{dropped} predicted point(s) outside the measured range were excluded "
            "from the comparison rather than extrapolated onto it."
        )
    logger.info("Validation: %s", report.summary().splitlines()[0])
    return report
