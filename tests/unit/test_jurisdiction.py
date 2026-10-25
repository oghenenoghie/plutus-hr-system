import pytest

from app.compliance.multicountry import CountryProfile, TaxConfigurationError, TaxStatus
from app.domain.money import Money, minor_units_exponent
from app.services.jurisdiction import is_selectable, require_selectable_country


@pytest.mark.parametrize(
    ("currency", "exponent"),
    [("NGN", 2), ("GMD", 2), ("RWF", 0), ("KES", 2), ("GHS", 2), ("XOF", 0)],
)
def test_catalogued_currencies_use_their_iso_4217_minor_units(currency: str, exponent: int) -> None:
    assert minor_units_exponent(currency) == exponent


def test_a_currency_without_minor_units_displays_whole_amounts() -> None:
    assert Money(1_500, "RWF").display() == "1500 RWF"
    assert Money(1_500, "KES").display() == "15.00 KES"


def test_an_unknown_currency_is_still_refused() -> None:
    with pytest.raises(ValueError, match="unknown currency exponent"):
        minor_units_exponent("USD")


def test_only_an_active_country_with_a_rule_version_is_selectable() -> None:
    nigeria = CountryProfile("NG", "Nigeria", "NGN", "NRS", TaxStatus.ACTIVE)
    assert is_selectable(nigeria)
    # Approved on paper but no rule version encoded: still not usable.
    assert not is_selectable(CountryProfile("KE", "Kenya", "KES", "KRA", TaxStatus.ACTIVE))
    for status in (TaxStatus.IN_REVIEW, TaxStatus.DRAFT, TaxStatus.CONFIGURATION_REQUIRED):
        assert not is_selectable(CountryProfile("NG", "Nigeria", "NGN", "NRS", status))


def test_require_selectable_country_normalises_and_refuses() -> None:
    assert require_selectable_country("ng") == "NG"
    with pytest.raises(TaxConfigurationError, match="Kenya isn't available yet"):
        require_selectable_country("KE")
    with pytest.raises(TaxConfigurationError, match="Unknown country code"):
        require_selectable_country("ZZ")
