from datetime import date

import pytest

from app.compliance.multicountry import (
    COUNTRY_PROFILES,
    EffectiveRate,
    TaxConfigurationError,
    TaxStatus,
    calculate_percentage_tax,
    get_country_profile,
    require_configured_country,
)

# The rates below are fixtures that exercise the arithmetic, not statutory
# figures: no new country's rules are approved yet.


def _rate(
    country: str,
    tax_type: str,
    rate_ppm: int,
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = None,
) -> EffectiveRate:
    return EffectiveRate(
        country=country,
        tax_type=tax_type,
        rate_ppm=rate_ppm,
        effective_from=effective_from,
        effective_to=effective_to,
        rule_version=f"{country}-{tax_type.upper()}-TEST.1",
        source_reference="test fixture",
        approved_by="reviewer@example.test",
    )


def test_country_catalog_contains_requested_jurisdictions_and_currencies() -> None:
    expected = {"NG": "NGN", "GM": "GMD", "RW": "RWF", "KE": "KES", "GH": "GHS", "CI": "XOF"}
    assert {p.code: p.currency for p in COUNTRY_PROFILES} == expected


def test_only_nigeria_is_active() -> None:
    active = {p.code for p in COUNTRY_PROFILES if p.status is TaxStatus.ACTIVE}
    assert active == {"NG"}
    assert require_configured_country("ng", tax_type="vat").code == "NG"


def test_new_country_fails_closed_until_rules_are_approved() -> None:
    assert get_country_profile(" ke ").status is TaxStatus.CONFIGURATION_REQUIRED
    with pytest.raises(TaxConfigurationError, match="not production-enabled"):
        require_configured_country("KE", tax_type="vat")


def test_unknown_country_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported country code"):
        get_country_profile("ZA")


def test_tax_exclusive_calculation_uses_minor_units_and_version() -> None:
    result = calculate_percentage_tax(
        country="KE",
        tax_type="vat",
        taxable_base_minor=10_000,
        rate=_rate("KE", "vat", 160_000),
        on=date(2026, 4, 1),
    )
    assert result.taxable_base_minor == 10_000
    assert result.tax_minor == 1_600
    assert result.total_minor == 11_600
    assert result.currency == "KES"
    assert result.rule_version == "KE-VAT-TEST.1"
    assert result.effective_date == date(2026, 4, 1)


def test_tax_inclusive_calculation_extracts_tax() -> None:
    result = calculate_percentage_tax(
        country="GH",
        tax_type="vat",
        taxable_base_minor=11_500,
        rate=_rate("GH", "vat", 150_000),
        on=date(2026, 5, 1),
        inclusive=True,
    )
    assert result.tax_minor == 1_500
    assert result.taxable_base_minor == 10_000
    assert result.total_minor == 11_500


@pytest.mark.parametrize(
    ("inclusive", "base_minor", "expected_tax_minor"),
    [
        # 5 * 10% = 0.5 -> 1, and 4 * 10% = 0.4 -> 0
        (False, 5, 1),
        (False, 4, 0),
        # 11 * 0.1 / 1.1 = 1 exactly; 6 * 0.1 / 1.1 = 0.545... -> 1; 5 -> 0.4545... -> 0
        (True, 11, 1),
        (True, 6, 1),
        (True, 5, 0),
    ],
)
def test_rounding_is_half_up(inclusive: bool, base_minor: int, expected_tax_minor: int) -> None:
    result = calculate_percentage_tax(
        country="RW",
        tax_type="vat",
        taxable_base_minor=base_minor,
        rate=_rate("RW", "vat", 100_000),
        on=date(2026, 3, 1),
        inclusive=inclusive,
    )
    assert result.tax_minor == expected_tax_minor


def test_rate_cannot_be_used_outside_effective_window() -> None:
    rate = _rate("CI", "wht", 50_000, effective_to=date(2026, 7, 1))
    assert rate.applies_on(date(2026, 6, 30))
    for on in (date(2025, 12, 31), date(2026, 7, 1)):
        with pytest.raises(TaxConfigurationError, match="No effective approved rate"):
            calculate_percentage_tax(
                country="CI", tax_type="wht", taxable_base_minor=100_000, rate=rate, on=on
            )


def test_mismatched_country_or_tax_type_is_rejected() -> None:
    with pytest.raises(TaxConfigurationError, match="does not match"):
        calculate_percentage_tax(
            country="KE",
            tax_type="vat",
            taxable_base_minor=1_000,
            rate=_rate("RW", "vat", 180_000),
            on=date(2026, 3, 1),
        )
    with pytest.raises(TaxConfigurationError, match="does not match"):
        calculate_percentage_tax(
            country="KE",
            tax_type="wht",
            taxable_base_minor=1_000,
            rate=_rate("KE", "vat", 160_000),
            on=date(2026, 3, 1),
        )


def test_negative_base_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        calculate_percentage_tax(
            country="KE",
            tax_type="vat",
            taxable_base_minor=-1,
            rate=_rate("KE", "vat", 160_000),
            on=date(2026, 3, 1),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"rate_ppm": -1}, "rate_ppm"),
        ({"rate_ppm": 1_000_001}, "rate_ppm"),
        ({"effective_to": date(2026, 1, 1)}, "effective_to"),
        ({"source_reference": "  "}, "required"),
        ({"approved_by": ""}, "required"),
    ],
)
def test_effective_rate_validates_its_fields(changes: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "country": "KE",
        "tax_type": "vat",
        "rate_ppm": 160_000,
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
        "rule_version": "KE-VAT-TEST.1",
        "source_reference": "test fixture",
        "approved_by": "reviewer@example.test",
    }
    with pytest.raises(ValueError, match=message):
        EffectiveRate(**(fields | changes))  # type: ignore[arg-type]
