"""The country an organisation's statutory rules come from.

Every calculation that needs statutory rules (payroll, final settlement,
simulation, bill and contractor withholding, the current-rules endpoint)
resolves them here, from the organisation's own country. A country without
approved rules fails closed with TaxConfigurationError; nothing ever falls
back to Nigeria. See docs/architecture/multicountry-tax.md, Part 1.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def rules_for_organisation(db: Session, org_id: uuid.UUID, on: date) -> RuleVersion:
    """The approved rule version in force on `on` for the organisation's
    country. Raises TaxConfigurationError if that country's rules aren't
    approved, and ValueError (as resolve_rule_version always has) if no
    version covers the date."""
    country = organisation_country(db, org_id)
    require_configured_country(country, tax_type="statutory")
    return resolve_rule_version(country, on)


def is_selectable(profile: CountryProfile) -> bool:
    """An organisation may run on a country only once its rules are approved
    (status ACTIVE) and encoded as at least one rule version."""
    return profile.status is TaxStatus.ACTIVE and has_rule_version(profile.code)


def require_selectable_country(country_code: str) -> str:
    """Normalises a requested country code, refusing any country an
    organisation can't run on yet."""
    try:
        profile = get_country_profile(country_code)
    except ValueError as exc:
        raise TaxConfigurationError(f"Unknown country code {country_code!r}.") from exc
    if not is_selectable(profile):
        raise TaxConfigurationError(
            f"{profile.name} isn't available yet: its tax rules haven't been approved."
        )
    return profile.code


def selectable_countries() -> list[CountryProfile]:
    return [profile for profile in COUNTRY_PROFILES if is_selectable(profile)]
