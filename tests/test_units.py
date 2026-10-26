"""Unit system tests.

Unit errors are risk R8: low likelihood, high severity, and cheap to eliminate with
round-trip tests.
"""

from __future__ import annotations

import math

import pytest

from barnes_ui.core.units import (
    CANONICAL_LENGTH,
    LengthUnit,
    UnitConfidence,
    UnitSystem,
    convert_length,
    deg_to_rad,
    format_quantity,
    rad_to_deg,
)


def test_canonical_length_is_millimetre() -> None:
    assert CANONICAL_LENGTH is LengthUnit.MILLIMETRE
    assert CANONICAL_LENGTH.millimetres == 1.0


@pytest.mark.parametrize(
    "unit,expected_mm",
    [
        (LengthUnit.MILLIMETRE, 1.0),
        (LengthUnit.CENTIMETRE, 10.0),
        (LengthUnit.METRE, 1000.0),
        (LengthUnit.INCH, 25.4),
        (LengthUnit.FOOT, 304.8),
        (LengthUnit.MICROMETRE, 1e-3),
    ],
)
def test_unit_sizes(unit: LengthUnit, expected_mm: float) -> None:
    assert unit.millimetres == pytest.approx(expected_mm)


def test_inch_to_millimetre() -> None:
    assert convert_length(1.0, LengthUnit.INCH, LengthUnit.MILLIMETRE) == pytest.approx(25.4)


def test_metre_to_millimetre() -> None:
    assert convert_length(2.5, LengthUnit.METRE, LengthUnit.MILLIMETRE) == pytest.approx(2500.0)


@pytest.mark.parametrize("unit", list(LengthUnit))
def test_conversion_round_trips(unit: LengthUnit) -> None:
    """Converting out and back must return the original value."""
    original = 123.456
    as_mm = convert_length(original, unit, LengthUnit.MILLIMETRE)
    back = convert_length(as_mm, LengthUnit.MILLIMETRE, unit)
    assert back == pytest.approx(original, rel=1e-12)


def test_from_symbol_accepts_aliases() -> None:
    assert LengthUnit.from_symbol("mm") is LengthUnit.MILLIMETRE
    assert LengthUnit.from_symbol("MM") is LengthUnit.MILLIMETRE
    assert LengthUnit.from_symbol("inch") is LengthUnit.INCH
    assert LengthUnit.from_symbol("Millimeter") is LengthUnit.MILLIMETRE


def test_from_symbol_rejects_unknown() -> None:
    """An unrecognised unit must raise rather than fall back to a default."""
    with pytest.raises(ValueError):
        LengthUnit.from_symbol("furlong")


def test_angle_round_trip() -> None:
    assert rad_to_deg(deg_to_rad(90.0)) == pytest.approx(90.0)
    assert deg_to_rad(180.0) == pytest.approx(math.pi)


class TestUnitConfidence:
    def test_assumed_is_not_trustworthy(self) -> None:
        assert not UnitConfidence.ASSUMED.is_trustworthy

    def test_declared_and_user_set_are_trustworthy(self) -> None:
        assert UnitConfidence.DECLARED.is_trustworthy
        assert UnitConfidence.USER_SET.is_trustworthy

    def test_assumed_description_asks_for_confirmation(self) -> None:
        assert "confirm" in UnitConfidence.ASSUMED.description.lower()


class TestUnitSystem:
    def test_derived_symbols_follow_the_length_unit(self) -> None:
        system = UnitSystem(length=LengthUnit.INCH)
        assert system.length_symbol == "in"
        assert system.area_symbol == "in^2"
        assert system.volume_symbol == "in^3"
        assert system.moment_symbol == "N.in"

    def test_force_and_stress_are_fixed(self) -> None:
        """Changing the length unit must not change the solver's unit set."""
        for unit in (LengthUnit.MILLIMETRE, LengthUnit.INCH, LengthUnit.METRE):
            system = UnitSystem(length=unit)
            assert system.force_symbol == "N"
            assert system.stress_symbol == "MPa"

    def test_volume_conversion_cubes_the_factor(self) -> None:
        system = UnitSystem(length=LengthUnit.CENTIMETRE)
        # 1000 mm^3 is 1 cm^3
        assert system.from_canonical_volume(1000.0) == pytest.approx(1.0)

    def test_area_conversion_squares_the_factor(self) -> None:
        system = UnitSystem(length=LengthUnit.CENTIMETRE)
        assert system.from_canonical_area(100.0) == pytest.approx(1.0)


class TestFormatQuantity:
    def test_unit_is_always_shown(self) -> None:
        assert format_quantity(12.5, "mm").endswith(" mm")

    def test_small_values_use_scientific_notation(self) -> None:
        assert "e" in format_quantity(1.2e-7, "mm")

    def test_large_values_use_scientific_notation(self) -> None:
        assert "e" in format_quantity(5.0e9, "mm^3")

    def test_ordinary_values_are_fixed_point(self) -> None:
        assert format_quantity(600.0, "mm^3") == "600 mm^3"

    def test_zero_is_handled(self) -> None:
        assert format_quantity(0.0, "mm") == "0 mm"
