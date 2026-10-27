"""The country an organisation's statutory rules come from.

Every calculation that needs statutory rules (payroll, final settlement,
simulation, bill and contractor withholding, the current-rules endpoint)
resolves them here, from the organisation's own country. A country without
approved rules fails closed with TaxConfigurationError; nothing ever falls
back to Nigeria. See docs/architecture/multicountry-tax.md, Part 1.

An organisation may choose any catalogued country: it then runs in that
country's currency straight away, and everything that doesn't need statutory
rules works. Payroll and statutory tax wait until payroll_available.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.engine import registry
from app.compliance.models import RuleVersion
from app.compliance.multicountry import (
    COUNTRY_PROFILES,
    CountryProfile,
    TaxConfigurationError,
    TaxStatus,
    get_country_profile,
    require_configured_country,
)
from app.compliance.resolver import has_rule_version, resolve_rule_version
from app.models.organisation import Organisation


def organisation_country(db: Session, org_id: uuid.UUID) -> str:
    country = db.scalar(select(Organisation.country_code).where(Organisation.id == org_id))
    if country is None:
        raise LookupError(f"organisation {org_id} not found")
    return country


def organisation_currency(db: Session, org_id: uuid.UUID) -> str:
    return get_country_profile(organisation_country(db, org_id)).currency


def require_approved_rules(db: Session, org_id: uuid.UUID, *, tax_type: str) -> str:
    """The organisation's country, refusing (TaxConfigurationError) one whose
    rules aren't approved. A cheap early check for flows that calculate
    later, so they stop with a clear reason up front."""
    country = organisation_country(db, org_id)
    require_configured_country(country, tax_type=tax_type)
    return country


NIGERIA = "NG"


def uses_engine(country_code: str) -> bool:
    """Every country but Nigeria runs payroll on the country-neutral engine
    (app.compliance.engine). Nigeria keeps its RuleVersion path until it is
    moved onto the engine as a separate, deliberate step."""
    return country_code != NIGERIA


def rules_for_organisation(db: Session, org_id: uuid.UUID, on: date) -> RuleVersion:
    """Nigeria's approved rule version in force on `on`, for the features
    that still run only on it (simulation, gross-up, withholding tax, the
    current-rules endpoint). Raises TaxConfigurationError for a country
    whose rules aren't approved, or whose rules run on the engine, and
    ValueError (as resolve_rule_version always has) if no version covers the
    date."""
    country = organisation_country(db, org_id)
    profile = require_configured_country(country, tax_type="statutory")
    if uses_engine(country):
        raise TaxConfigurationError(
            f"{profile.name}'s statutory rules run on the country rule engine, which this "
            "feature doesn't use yet."
        )
    return resolve_rule_version(country, on)


def payroll_available(profile: CountryProfile) -> bool:
    """Whether payroll and statutory tax can run for the country: its rules
    are approved (status ACTIVE) and encoded, as a Nigerian rule version or
    an active engine rule set. An engine country's payroll also needs the
    organisation's Tax Settings (app.services.tax_settings), which each run
    checks for."""
    if profile.status is not TaxStatus.ACTIVE:
        return False
    if uses_engine(profile.code):
        return any(
            entry.country == profile.code and registry.is_active(entry)
            for entry in registry.REGISTERED_RULE_SETS
        )
    return has_rule_version(profile.code)


def organisation_payroll_available(db: Session, org_id: uuid.UUID) -> bool:
    return payroll_available(get_country_profile(organisation_country(db, org_id)))


def require_catalogued_country(country_code: str) -> CountryProfile:
    """The catalogued country a requested code names (any case), refusing
    one Plutus doesn't list. Any catalogued country may be chosen."""
    try:
        return get_country_profile(country_code)
    except ValueError as exc:
        known = ", ".join(profile.code for profile in COUNTRY_PROFILES)
        raise TaxConfigurationError(
            f"Unknown country code {country_code!r}. Choose one of {known}."
        ) from exc
