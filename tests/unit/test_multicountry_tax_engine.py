import pytest

from app.compliance.multicountry import (
    COUNTRY_PROFILES,
    TaxConfigurationError,
    TaxStatus,
    get_country_profile,
    require_configured_country,
)
from tests.unit.tax_engine_fixtures import mark_country

# The catalogue and its fail-closed guard. The calculations are tested in
# tests/unit/test_tax_engine_*.py and tests/unit/test_indirect_tax.py.


def test_country_catalog_contains_requested_jurisdictions_and_currencies() -> None:
    expected = {"NG": "NGN", "GM": "GMD", "RW": "RWF", "KE": "KES", "GH": "GHS", "CI": "XOF"}
    assert {p.code: p.currency for p in COUNTRY_PROFILES} == expected


def test_every_catalogued_country_is_active() -> None:
    # Nigeria on its rule versions; the other five on the engine, approved
    # by Plutus Technologies (app/compliance/engine/countries/).
    assert {p.code for p in COUNTRY_PROFILES if p.status is TaxStatus.ACTIVE} == {
        "NG",
        "GM",
        "RW",
        "KE",
        "GH",
        "CI",
    }
    assert require_configured_country(" ke ", tax_type="payroll").code == "KE"


@pytest.mark.parametrize(
    "status", [TaxStatus.DRAFT, TaxStatus.IN_REVIEW, TaxStatus.CONFIGURATION_REQUIRED]
)
def test_a_country_not_marked_active_is_refused_for_every_tax(
    monkeypatch: pytest.MonkeyPatch, status: TaxStatus
) -> None:
    mark_country(monkeypatch, "KE", status)
    for tax_type in ("vat", "withholding_tax", "corporate_tax", "employment_tax", "statutory"):
        with pytest.raises(TaxConfigurationError, match="not production-enabled"):
            require_configured_country("KE", tax_type=tax_type)


def test_unknown_country_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported country code"):
        get_country_profile("ZA")
