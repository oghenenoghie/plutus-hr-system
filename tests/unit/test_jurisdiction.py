import pytest

from app.compliance.multicountry import (
    CountryProfile,
    TaxConfigurationError,
    TaxStatus,
    get_country_profile,
)
from app.domain.money import Money, minor_units_exponent
from app.services.jurisdiction import payroll_available, require_catalogued_country
from app.services.report_export import money


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


def test_payroll_runs_only_for_an_active_country_with_encoded_rules() -> None:
    nigeria = CountryProfile("NG", "Nigeria", "NGN", "NRS", TaxStatus.ACTIVE)
    assert payroll_available(nigeria)
    # The five engine countries have registered rules.
    for code in ("GM", "RW", "KE", "GH", "CI"):
        assert payroll_available(get_country_profile(code)), code
    # Approved on paper but no rules encoded: still no payroll.
    assert not payroll_available(CountryProfile("ZZ", "Nowhere", "KES", "None", TaxStatus.ACTIVE))
    for status in (TaxStatus.IN_REVIEW, TaxStatus.DRAFT, TaxStatus.CONFIGURATION_REQUIRED):
        assert not payroll_available(CountryProfile("NG", "Nigeria", "NGN", "NRS", status))
        assert not payroll_available(CountryProfile("KE", "Kenya", "KES", "KRA", status))


def test_any_catalogued_country_can_be_chosen_and_an_unknown_one_cannot() -> None:
    assert require_catalogued_country("ng").code == "NG"
    assert require_catalogued_country(" ke ").code == "KE"
    with pytest.raises(TaxConfigurationError, match="Unknown country code"):
        require_catalogued_country("ZZ")


@pytest.mark.parametrize(
    ("minor", "currency", "written"),
    [
        (150_000, "NGN", "1,500.00"),
        (-150_005, "KES", "-1,500.05"),
        (1_500, "RWF", "1,500"),
        (2_500_000, "XOF", "2,500,000"),
        (None, "GHS", ""),
    ],
)
def test_exports_write_amounts_in_the_currency_s_own_decimal_places(
    minor: int | None, currency: str, written: str
) -> None:
    assert money(minor, currency) == written
