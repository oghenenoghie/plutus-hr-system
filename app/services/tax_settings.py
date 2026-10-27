"""An organisation's Tax Settings: the figures it enters itself for its
country's payroll rules, where the sources behind them didn't settle a figure
(app/compliance/engine/settings.py).

Each value applies from a date until a later one replaces it; a pay run uses
the latest value on or before its period's end. Values are only ever added
(org_tax_settings is append-only), and none may take effect on or before the
end of a locked pay run: a locked payslip keeps the figures it was worked out
with, and is never recalculated.
"""

import uuid
from collections.abc import Mapping
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance.engine.registry import registered_templates
from app.compliance.engine.rules import structural_problems
from app.compliance.engine.settings import (
    RuleSetTemplate,
    SettingError,
    missing_settings,
    parse_setting,
)
from app.compliance.multicountry import get_country_profile
from app.models.org_tax_setting import OrgTaxSetting
from app.models.pay_run import PayRun, PayRunStatus


class TaxSettingsError(ValueError):
    """Tax Settings that can't be entered as asked."""


def template_for(country_code: str, on: date) -> RuleSetTemplate | None:
    """The country's rules that take Tax Settings and are in force on the
    date, or else the next to come into force; None for a country whose
    rules take none (Nigeria) or have all ended."""
    templates = registered_templates(country_code)
    in_force = [template for template in templates if template.applies_on(on)]
    if in_force:
        return in_force[0]
    upcoming = [template for template in templates if template.effective_from > on]
    return upcoming[0] if upcoming else None


def rows_on(
    db: Session, *, org_id: uuid.UUID, country_code: str, on: date
) -> dict[str, OrgTaxSetting]:
    """Each setting's row in effect on the date: the latest from on or
    before it, a correction entered later winning over the same date."""
    rows = db.scalars(
        select(OrgTaxSetting)
        .where(
            OrgTaxSetting.org_id == org_id,
            OrgTaxSetting.country_code == country_code,
            OrgTaxSetting.effective_from <= on,
        )
        .order_by(OrgTaxSetting.effective_from, OrgTaxSetting.created_at, OrgTaxSetting.id)
    ).all()
    latest: dict[str, OrgTaxSetting] = {}
    for row in rows:
        latest[row.key] = row
    return latest


def settings_on(db: Session, *, org_id: uuid.UUID, country_code: str, on: date) -> dict[str, str]:
    """The organisation's values in effect on the date, in stored form."""
    return {
        key: row.value
        for key, row in rows_on(db, org_id=org_id, country_code=country_code, on=on).items()
    }


def history(db: Session, *, org_id: uuid.UUID, country_code: str) -> list[OrgTaxSetting]:
    """Every value the organisation has entered for the country, newest
    first."""
    return list(
        db.scalars(
            select(OrgTaxSetting)
            .where(OrgTaxSetting.org_id == org_id, OrgTaxSetting.country_code == country_code)
            .order_by(OrgTaxSetting.created_at.desc(), OrgTaxSetting.key)
        ).all()
    )


def last_locked_period_end(db: Session, *, org_id: uuid.UUID) -> date | None:
    period_end: date | None = db.scalar(
        select(func.max(PayRun.period_end)).where(
            PayRun.org_id == org_id, PayRun.status == PayRunStatus.LOCKED
        )
    )
    return period_end


def enter_settings(
    db: Session,
    *,
    org_id: uuid.UUID,
    country_code: str,
    account_id: uuid.UUID | None,
    effective_from: date,
    entered: Mapping[str, str],
    note: str | None = None,
) -> list[OrgTaxSetting]:
    """Record the values (as a person enters them: "5.75", "1,500.00",
    "15", or an option's value) from `effective_from`. Refuses
    (TaxSettingsError) a setting the country's rules don't ask for, a value
    that isn't valid for it, a date a locked pay run already covers, and
    figures that, with the others in effect then, don't make usable rules."""
    profile = get_country_profile(country_code)
    template = next(
        (t for t in registered_templates(profile.code) if t.applies_on(effective_from)), None
    )
    if template is None:
        raise TaxSettingsError(
            f"No {profile.name} payroll rules that take Tax Settings are in force on "
            f"{effective_from.isoformat()}."
        )
    if not entered:
        raise TaxSettingsError("Enter at least one figure.")

    locked_to = last_locked_period_end(db, org_id=org_id)
    if locked_to is not None and effective_from <= locked_to:
        raise TaxSettingsError(
            f"Pay runs up to {locked_to.isoformat()} are locked, and their payslips keep the "
            "figures they were worked out with. Choose a date from "
            f"{(locked_to + timedelta(days=1)).isoformat()}."
        )

    stored: dict[str, str] = {}
    for key, value in entered.items():
        spec = template.spec(key)
        if spec is None:
            raise TaxSettingsError(f"{profile.name}'s payroll rules don't ask for {key!r}.")
        try:
            stored[key] = parse_setting(spec, value, currency=profile.currency)
        except SettingError as exc:
            raise TaxSettingsError(str(exc)) from exc

    merged = settings_on(db, org_id=org_id, country_code=profile.code, on=effective_from)
    merged.update(stored)
    if not missing_settings(template.settings, merged):
        problems = structural_problems(template.build(merged))
        if problems:
            raise TaxSettingsError(
                "With your other Tax Settings, these figures don't make usable payroll rules: "
                + "; ".join(problems)
            )

    rows = [
        OrgTaxSetting(
            org_id=org_id,
            country_code=profile.code,
            key=key,
            value=value,
            effective_from=effective_from,
            note=note,
            entered_by=account_id,
        )
        for key, value in stored.items()
    ]
    db.add_all(rows)
    db.flush()
    return rows
