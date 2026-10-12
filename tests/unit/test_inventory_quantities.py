from decimal import Decimal

import pytest

from app.domain.inventory.quantities import (
    MAX_QUANTITY,
    QuantityError,
    has_valid_precision,
    normalise,
    require_whole_if_needed,
    to_base_quantity,
)


def test_normalise_pads_to_four_places_without_rounding() -> None:
    assert str(normalise(Decimal("12.5"))) == "12.5000"
    assert str(normalise(Decimal(-3))) == "-3.0000"


def test_more_than_four_decimal_places_is_rejected_not_rounded() -> None:
    assert not has_valid_precision(Decimal("1.00001"))
    with pytest.raises(QuantityError, match="more than 4 decimal places"):
        normalise(Decimal("1.00001"))


def test_trailing_zeros_beyond_four_places_are_fine() -> None:
    assert normalise(Decimal("2.500000")) == Decimal("2.5")


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_quantities_are_rejected(value: Decimal) -> None:
    with pytest.raises(QuantityError, match="finite"):
        normalise(value)


def test_quantity_must_fit_numeric_18_4() -> None:
    assert normalise(MAX_QUANTITY) == MAX_QUANTITY
    with pytest.raises(QuantityError, match="too large"):
        normalise(MAX_QUANTITY + Decimal("0.0001"))


def test_to_base_quantity_converts_exactly() -> None:
    assert to_base_quantity(Decimal(2), Decimal(24)) == Decimal(48)
    assert to_base_quantity(Decimal("1.5"), Decimal("0.25")) == Decimal("0.375")


def test_to_base_quantity_rejects_a_result_needing_more_precision() -> None:
    with pytest.raises(QuantityError):
        to_base_quantity(Decimal("0.0001"), Decimal("0.5"))


def test_to_base_quantity_rejects_non_positive_factor() -> None:
    with pytest.raises(QuantityError):
        to_base_quantity(Decimal(1), Decimal(0))


def test_whole_number_units_reject_fractions() -> None:
    require_whole_if_needed(Decimal("3.0000"), allows_fraction=False, unit_code="PCS")
    require_whole_if_needed(Decimal("2.5"), allows_fraction=True, unit_code="KG")
    with pytest.raises(QuantityError, match="PCS does not allow fractional"):
        require_whole_if_needed(Decimal("2.5"), allows_fraction=False, unit_code="PCS")
