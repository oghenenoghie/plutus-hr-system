"""Tax Settings: the figures an organisation enters itself for its country's
payroll rules (app/services/tax_settings.py). Anyone who works with payroll
or the books can read them; only an admin can enter them, and every entry is
audited."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.engine.registry import resolve_rule_set
from app.compliance.engine.rules import (
    Applicability,
    ContributionKind,
    CountryRuleSet,
    DueDayOfFollowingMonth,
    DueRule,
    EarningCategory,
    EarningsBase,
    FixedCredit,
)
from app.compliance.engine.settings import (
    RuleSetTemplate,
    SettingSpec,
    display_setting,
    entry_text,
    is_required,
    missing_settings,
)
from app.compliance.multicountry import CountryProfile, TaxConfigurationError, get_country_profile
from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.account import Account
from app.models.membership import Role
from app.models.org_tax_setting import OrgTaxSetting
from app.schemas.tax_settings import (
    CountryRulesOut,
    IncomeTaxOut,
    RuleLineOut,
    SourceOut,
    TaxBandOut,
    TaxSettingEntryOut,
    TaxSettingOptionOut,
    TaxSettingOut,
    TaxSettingsOut,
    TaxSettingsUpdate,
)
from app.services.audit import record_audit_event
from app.services.jurisdiction import organisation_country
from app.services.tax_settings import (
    TaxSettingsError,
    enter_settings,
    history,
    last_locked_period_end,
    rows_on,
    template_for,
)

router = APIRouter(prefix="/compliance", tags=["compliance"])

_VIEW = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT, Role.AUDITOR)
_CHANGE = require_roles(Role.ADMIN)


def _paragraphs(text: str) -> list[str]:
    return [" ".join(block.split()) for block in text.strip().split("\n\n") if block.strip()]


def _bound(spec: SettingSpec, value: int | None, currency: str) -> str | None:
    if value is None:
        return None
    return entry_text(spec, str(value), currency=currency)


def _setting_out(
    spec: SettingSpec,
    row: OrgTaxSetting | None,
    *,
    values: dict[str, str],
    currency: str,
    emails: dict[uuid.UUID, str],
) -> TaxSettingOut:
    required_key, required_value = spec.required_when or (None, None)
    return TaxSettingOut(
        key=spec.key,
        label=spec.label,
        help=spec.help,
        kind=spec.kind.value,
        options=[
            TaxSettingOptionOut(
                value=option.value,
                label=option.label,
                source=option.source,
                entry=entry_text(spec, option.value, currency=currency),
                display=display_setting(spec, option.value, currency=currency),
            )
            for option in spec.options
        ],
        minimum=_bound(spec, spec.minimum, currency),
        maximum=_bound(spec, spec.maximum, currency),
        required_when_key=required_key,
        required_when_value=required_value,
        required=is_required(spec, values),
        value=row.value if row else None,
        entry=entry_text(spec, row.value, currency=currency) if row else None,
        display=display_setting(spec, row.value, currency=currency) if row else None,
        effective_from=row.effective_from if row else None,
        entered_by=emails.get(row.entered_by) if row and row.entered_by else None,
        entered_at=row.created_at if row else None,
    )


_BASE_NAMES = {
    frozenset(EarningCategory): "Gross pay",
    frozenset({EarningCategory.BASIC}): "Basic salary",
    frozenset(
        {
            EarningCategory.BASIC,
            EarningCategory.HOUSING,
            EarningCategory.TRANSPORT,
            EarningCategory.FIXED_ALLOWANCE,
        }
    ): "Basic salary plus fixed allowances",
}


def _base(categories: frozenset[EarningCategory]) -> str:
    return _BASE_NAMES.get(categories) or ", ".join(sorted(c.value for c in categories))


def _due(rule: DueRule) -> str:
    if isinstance(rule, DueDayOfFollowingMonth):
        return f"Day {rule.day} of the following month"
    return f"{rule.days} days after the period ends"


def _rules_out(rule_set: CountryRuleSet) -> CountryRulesOut:
    tax = rule_set.income_tax
    deductible = {cap.group for cap in tax.deduction_caps}
    lines: list[RuleLineOut] = [
        RuleLineOut(
            code=rule.code,
            name=rule.name,
            kind=(
                "employee_contribution"
                if rule.kind is ContributionKind.EMPLOYEE
                else "employer_contribution"
            ),
            authority=rule.authority,
            base=_base(rule.base.categories) if isinstance(rule.base, EarningsBase) else "Net pay",
            rate_ppm=rule.rate_ppm,
            amount_minor=rule.flat_amount_minor,
            base_ceiling_minor=rule.base_ceiling_minor,
            amount_floor_minor=rule.amount_floor_minor,
            amount_cap_minor=rule.amount_cap_minor,
            applies_to=rule.applies_to.value,
            tax_deductible=rule.tax_deduction_group in deductible,
            due=_due(rule.due),
            source=rule.source,
        )
        for rule in rule_set.contributions
    ]
    lines += [
        RuleLineOut(
            code=levy.code,
            name=levy.name,
            kind="payroll_levy",
            authority=levy.authority,
            base=_base(levy.base_categories),
            rate_ppm=levy.rate_ppm,
            amount_minor=None,
            base_ceiling_minor=None,
            amount_floor_minor=None,
            amount_cap_minor=None,
            applies_to=Applicability.ALL.value,
            tax_deductible=False,
            due=_due(levy.due),
            source=levy.source,
        )
        for levy in rule_set.payroll_levies
    ]
    for credit in tax.credits:
        if isinstance(credit, FixedCredit):
            amount, per = credit.amount_minor, "a month"
        else:
            amount, per = credit.amount_per_half_share_minor, "per half-share"
        lines.append(
            RuleLineOut(
                code=credit.code,
                name=f"Off {tax.name}, {per}",
                kind="tax_credit",
                authority=tax.authority,
                base=_base(tax.taxable_categories),
                rate_ppm=None,
                amount_minor=amount,
                base_ceiling_minor=None,
                amount_floor_minor=None,
                amount_cap_minor=None,
                applies_to=Applicability.ALL.value,
                tax_deductible=False,
                due=_due(tax.due),
                source=credit.source,
            )
        )
    return CountryRulesOut(
        rule_set_id=rule_set.id,
        income_tax=IncomeTaxOut(
            code=tax.code,
            name=tax.name,
            authority=tax.authority,
            method=tax.method.value,
            bands=[TaxBandOut(up_to_minor=b.up_to_minor, rate_ppm=b.rate_ppm) for b in tax.bands],
            due=_due(tax.due),
            source=tax.source,
        ),
        lines=lines,
    )


def _not_applicable(profile: CountryProfile, locked_through: date | None) -> TaxSettingsOut:
    return TaxSettingsOut(
        country_code=profile.code,
        country_name=profile.name,
        currency=profile.currency,
        applies=False,
        rule_set_id=None,
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_on=None,
        approval_basis=None,
        summary=[],
        settings=[],
        missing=[],
        history=[],
        sources=[],
        locked_through=locked_through,
        rules=None,
        rules_problem=None,
    )


def describe(db: Session, org_id: uuid.UUID, today: date) -> TaxSettingsOut:
    profile = get_country_profile(organisation_country(db, org_id))
    locked_through = last_locked_period_end(db, org_id=org_id)
    template: RuleSetTemplate | None = template_for(profile.code, today)
    if template is None:
        return _not_applicable(profile, locked_through)

    # The settings in effect today, or on the day the rules start if that's
    # later.
    on = max(today, template.effective_from)
    rows = rows_on(db, org_id=org_id, country_code=profile.code, on=on)
    values = {key: row.value for key, row in rows.items()}
    entries = history(db, org_id=org_id, country_code=profile.code)
    account_ids = {row.entered_by for row in entries if row.entered_by is not None}
    emails: dict[uuid.UUID, str] = {}
    if account_ids:
        found = db.execute(select(Account.id, Account.email).where(Account.id.in_(account_ids)))
        emails = {account_id: email for account_id, email in found}
    missing = missing_settings(template.settings, values)

    rules = rules_problem = None
    if not missing:
        try:
            rules = _rules_out(resolve_rule_set(profile.code, on, settings=values))
        except TaxConfigurationError as exc:
            rules_problem = str(exc)

    # The rules' own description and sources don't depend on the settings.
    preview = template.build(template.preview_values())
    approval = preview.approval
    labels = {spec.key: spec for spec in template.settings}
    return TaxSettingsOut(
        country_code=profile.code,
        country_name=profile.name,
        currency=profile.currency,
        applies=True,
        rule_set_id=template.id,
        effective_from=template.effective_from,
        effective_to=template.effective_to,
        approved_by=approval.approved_by,
        approved_on=approval.approved_on,
        approval_basis=approval.basis.value,
        summary=_paragraphs(template.summary),
        settings=[
            _setting_out(
                spec, rows.get(spec.key), values=values, currency=profile.currency, emails=emails
            )
            for spec in template.settings
        ],
        missing=[spec.key for spec in missing],
        history=[
            TaxSettingEntryOut(
                id=row.id,
                key=row.key,
                label=labels[row.key].label if row.key in labels else row.key,
                display=(
                    display_setting(labels[row.key], row.value, currency=profile.currency)
                    if row.key in labels
                    else row.value
                ),
                effective_from=row.effective_from,
                note=row.note,
                entered_by=emails.get(row.entered_by) if row.entered_by else None,
                entered_at=row.created_at,
            )
            for row in entries
        ],
        sources=[
            SourceOut(
                id=source.id,
                title=source.title,
                reference=source.reference,
                official=source.official,
            )
            for source in preview.sources
        ],
        locked_through=locked_through,
        rules=rules,
        rules_problem=rules_problem,
    )


@router.get("/tax-settings", response_model=TaxSettingsOut)
def read_tax_settings(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW)
) -> TaxSettingsOut:
    """The organisation's country rules that take Tax Settings: what's built
    in, what the organisation has entered and when, what's still missing,
    and the rules as they stand today."""
    return describe(db, claims.org_id, datetime.now(UTC).date())


@router.post("/tax-settings", response_model=TaxSettingsOut)
def change_tax_settings(
    body: TaxSettingsUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_CHANGE),
) -> TaxSettingsOut:
    """Enter figures from a date. Pay runs whose period ends on or after it
    use them; locked pay runs keep what they used."""
    country = organisation_country(db, claims.org_id)
    try:
        rows = enter_settings(
            db,
            org_id=claims.org_id,
            country_code=country,
            account_id=claims.account_id,
            effective_from=body.effective_from,
            entered=body.values,
            note=body.note,
        )
    except TaxSettingsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="tax_settings.update",
        entity_type="org_tax_settings",
        entity_id=claims.org_id,
        metadata={
            "country": country,
            "effective_from": body.effective_from.isoformat(),
            "values": {row.key: row.value for row in rows},
            "note": body.note,
        },
    )
    return describe(db, claims.org_id, datetime.now(UTC).date())
