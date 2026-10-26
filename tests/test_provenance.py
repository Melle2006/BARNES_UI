"""Provenance tracking tests.

These guard risk R1 -- plausible but physically wrong results. The behaviour being
protected is that an assumption cannot be laundered into an apparent measurement by
passing through a calculation.
"""

from __future__ import annotations

import pytest

from barnes_ui.core.provenance import (
    CAVEAT_ASSUMED_MATERIAL,
    CAVEAT_SMALL_STRAIN,
    Caveat,
    Provenance,
    TaggedValue,
    combine_provenance,
    describe_caveats,
    weakest,
)


class TestProvenanceOrdering:
    def test_assumption_is_the_weakest(self) -> None:
        assert min(Provenance) is Provenance.UNVALIDATED_ASSUMPTION

    def test_experiment_is_the_strongest(self) -> None:
        assert max(Provenance) is Provenance.EXPERIMENTALLY_VALIDATED

    def test_reduced_order_is_weaker_than_fea(self) -> None:
        assert Provenance.REDUCED_ORDER_PREDICTION < Provenance.FEA_RESULT

    def test_reduced_order_is_not_quantitatively_trustworthy(self) -> None:
        """A screening tool must not be presented as a predictor."""
        assert not Provenance.REDUCED_ORDER_PREDICTION.is_quantitatively_trustworthy
        assert Provenance.FEA_RESULT.is_quantitatively_trustworthy

    def test_weak_tags_require_a_warning_banner(self) -> None:
        assert Provenance.UNVALIDATED_ASSUMPTION.requires_warning_banner
        assert Provenance.REDUCED_ORDER_PREDICTION.requires_warning_banner
        assert not Provenance.FEA_RESULT.requires_warning_banner

    def test_every_tag_has_a_label_and_description(self) -> None:
        for tag in Provenance:
            assert tag.label
            assert tag.description


class TestWeakest:
    def test_picks_the_lowest(self) -> None:
        assert weakest([
            Provenance.GEOMETRIC_MEASUREMENT,
            Provenance.UNVALIDATED_ASSUMPTION,
            Provenance.FEA_RESULT,
        ]) is Provenance.UNVALIDATED_ASSUMPTION

    def test_empty_raises_rather_than_defaulting(self) -> None:
        with pytest.raises(ValueError):
            weakest([])


class TestArithmetic:
    def test_multiplying_takes_the_weaker_tag(self) -> None:
        """The central guarantee: measurement x assumption is not a measurement."""
        length = TaggedValue(10.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        modulus = TaggedValue(
            12.0, "MPa", Provenance.UNVALIDATED_ASSUMPTION,
            caveats=(CAVEAT_ASSUMED_MATERIAL,),
        )
        result = length * modulus
        assert result.provenance is Provenance.UNVALIDATED_ASSUMPTION
        assert result.value == pytest.approx(120.0)
        assert CAVEAT_ASSUMED_MATERIAL in result.caveats

    def test_caveats_survive_a_chain_of_operations(self) -> None:
        """An assumption three calculations back must still be visible."""
        assumed = TaggedValue(
            2.0, "MPa", Provenance.UNVALIDATED_ASSUMPTION,
            caveats=(CAVEAT_ASSUMED_MATERIAL,),
        )
        measured = TaggedValue(3.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        result = ((assumed * measured) * 2.0) / TaggedValue(
            1.5, "mm", Provenance.GEOMETRIC_MEASUREMENT
        )
        assert result.provenance is Provenance.UNVALIDATED_ASSUMPTION
        assert CAVEAT_ASSUMED_MATERIAL in result.caveats

    def test_scalar_multiplication_does_not_weaken(self) -> None:
        """A plain number is exact, so it must not degrade the tag."""
        measured = TaggedValue(10.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        doubled = measured * 2.0
        assert doubled.provenance is Provenance.GEOMETRIC_MEASUREMENT
        assert doubled.value == pytest.approx(20.0)

    def test_units_compose_on_multiplication(self) -> None:
        a = TaggedValue(2.0, "N", Provenance.FEA_RESULT)
        b = TaggedValue(3.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        assert (a * b).unit == "N.mm"

    def test_units_compose_on_division(self) -> None:
        a = TaggedValue(6.0, "N", Provenance.FEA_RESULT)
        b = TaggedValue(3.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        result = a / b
        assert result.unit == "N/mm"
        assert result.value == pytest.approx(2.0)

    def test_adding_mismatched_units_raises(self) -> None:
        """Adding mm to MPa is a bug, so it must fail loudly."""
        a = TaggedValue(1.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        b = TaggedValue(1.0, "MPa", Provenance.FEA_RESULT)
        with pytest.raises(ValueError, match="Cannot add"):
            _ = a + b

    def test_adding_matching_units_works(self) -> None:
        a = TaggedValue(1.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        b = TaggedValue(2.0, "mm", Provenance.FEA_RESULT)
        total = a + b
        assert total.value == pytest.approx(3.0)
        assert total.provenance is Provenance.FEA_RESULT


class TestProvenanceCannotBeUpgraded:
    def test_downgrade_is_allowed(self) -> None:
        value = TaggedValue(1.0, "mm", Provenance.GEOMETRIC_MEASUREMENT)
        weaker = value.downgraded_to(Provenance.REDUCED_ORDER_PREDICTION)
        assert weaker.provenance is Provenance.REDUCED_ORDER_PREDICTION

    def test_upgrade_raises(self) -> None:
        """No calculation may promote its own inputs. This is the anti-laundering rule."""
        value = TaggedValue(1.0, "mm", Provenance.UNVALIDATED_ASSUMPTION)
        with pytest.raises(ValueError, match="Refusing to upgrade"):
            value.downgraded_to(Provenance.EXPERIMENTALLY_VALIDATED)

    def test_values_are_immutable(self) -> None:
        value = TaggedValue(1.0, "mm", Provenance.UNVALIDATED_ASSUMPTION)
        with pytest.raises(Exception):
            value.provenance = Provenance.FEA_RESULT  # type: ignore[misc]


class TestCaveats:
    def test_duplicates_are_removed(self) -> None:
        a = TaggedValue(1.0, "mm", Provenance.FEA_RESULT, caveats=(CAVEAT_SMALL_STRAIN,))
        b = TaggedValue(2.0, "mm", Provenance.FEA_RESULT, caveats=(CAVEAT_SMALL_STRAIN,))
        assert len((a + b).caveats) == 1

    def test_distinct_caveats_accumulate(self) -> None:
        a = TaggedValue(1.0, "mm", Provenance.FEA_RESULT, caveats=(CAVEAT_SMALL_STRAIN,))
        b = TaggedValue(2.0, "mm", Provenance.FEA_RESULT, caveats=(CAVEAT_ASSUMED_MATERIAL,))
        assert len((a + b).caveats) == 2

    def test_with_caveat_returns_a_new_value(self) -> None:
        original = TaggedValue(1.0, "mm", Provenance.FEA_RESULT)
        amended = original.with_caveat(Caveat("x", "something"))
        assert len(original.caveats) == 0
        assert len(amended.caveats) == 1

    def test_describe_caveats_deduplicates_across_values(self) -> None:
        values = [
            TaggedValue(1.0, "mm", Provenance.FEA_RESULT, caveats=(CAVEAT_SMALL_STRAIN,)),
            TaggedValue(2.0, "mm", Provenance.FEA_RESULT, caveats=(CAVEAT_SMALL_STRAIN,)),
            TaggedValue(3.0, "mm", Provenance.FEA_RESULT, caveats=(CAVEAT_ASSUMED_MATERIAL,)),
        ]
        assert len(describe_caveats(values)) == 2


class TestCombineProvenance:
    def test_returns_weakest_tag_and_union_of_caveats(self) -> None:
        values = [
            TaggedValue(1.0, "mm", Provenance.GEOMETRIC_MEASUREMENT),
            TaggedValue(2.0, "MPa", Provenance.UNVALIDATED_ASSUMPTION,
                        caveats=(CAVEAT_ASSUMED_MATERIAL,)),
        ]
        tag, caveats = combine_provenance(values)
        assert tag is Provenance.UNVALIDATED_ASSUMPTION
        assert CAVEAT_ASSUMED_MATERIAL in caveats

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            combine_provenance([])


def test_string_shows_value_unit_and_tag() -> None:
    value = TaggedValue(600.0, "mm^3", Provenance.GEOMETRIC_MEASUREMENT)
    text = str(value)
    assert "600" in text
    assert "mm^3" in text
    assert "Measured" in text
