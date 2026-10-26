import pytest

from app.compliance.multicountry import (
    COUNTRY_PROFILES,
    TaxConfigurationError,
    TaxStatus,
    get_country_profile,
    require_configured_country,
)

# The catalogue and its fail-closed guard. The calculations are tested in
# tests/unit/test_tax_engine_*.py and tests/unit/test_indirect_tax.py.


def test_country_catalog_contains_requested_jurisdictions_and_currencies() -> None:
    expected = {"NG": "NGN", "GM": "GMD", "RW": "RWF", "KE": "KES", "GH": "GHS", "CI": "XOF"}
    assert {p.code: p.currency for p in COUNTRY_PROFILES} == expected


def test_only_nigeria_is_active() -> None:
    active = {p.code for p in COUNTRY_PROFILES if p.status is TaxStatus.ACTIVE}
    assert active == {"NG"}
    assert require_configured_country("ng", tax_type="vat").code == "NG"


def test_new_country_fails_closed_until_rules_are_approved() -> None:
    assert get_country_profile(" ke ").status is TaxStatus.DRAFT
    with pytest.raises(TaxConfigurationError, match="not production-enabled"):
        require_configured_country("KE", tax_type="vat")


@pytest.mark.parametrize("code", ["GM", "RW", "KE", "GH", "CI"])
def test_a_drafted_country_is_still_refused_for_every_tax(code: str) -> None:
    # Drafted rules are documentation awaiting the adviser's review, never
    # something the engine may calculate, post or file with.
    assert get_country_profile(code).status is TaxStatus.DRAFT
    for tax_type in ("vat", "withholding_tax", "corporate_tax", "employment_tax", "statutory"):
        with pytest.raises(TaxConfigurationError, match="not production-enabled"):
            require_configured_country(code, tax_type=tax_type)


def test_unknown_country_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported country code"):
        get_country_profile("ZA")
