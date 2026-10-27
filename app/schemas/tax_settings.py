import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class TaxSettingOptionOut(BaseModel):
    value: str  # stored form
    label: str
    source: str  # the source that gives this value
    entry: str  # the value as it would be entered
    display: str


class TaxSettingOut(BaseModel):
    key: str
    label: str
    help: str
    kind: str  # percent, amount, day or choice
    options: list[TaxSettingOptionOut]
    minimum: str | None  # as it would be entered
    maximum: str | None
    # Asked only while another setting has this value.
    required_when_key: str | None
    required_when_value: str | None
    required: bool  # needed by the values in effect today
    # The value in effect today, if any, and who entered it.
    value: str | None
    entry: str | None
    display: str | None
    effective_from: date | None
    entered_by: str | None
    entered_at: datetime | None


class TaxSettingEntryOut(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    display: str
    effective_from: date
    note: str | None
    entered_by: str | None
    entered_at: datetime


class SourceOut(BaseModel):
    id: str
    title: str
    reference: str
    official: bool


class TaxBandOut(BaseModel):
    up_to_minor: int | None
    rate_ppm: int


class RuleLineOut(BaseModel):
    code: str
    name: str
    kind: str  # employee_contribution, employer_contribution, payroll_levy or tax_credit
    authority: str
    base: str
    rate_ppm: int | None
    amount_minor: int | None  # a flat amount, or a credit
    base_ceiling_minor: int | None
    amount_floor_minor: int | None
    amount_cap_minor: int | None
    applies_to: str
    tax_deductible: bool
    due: str
    source: str


class IncomeTaxOut(BaseModel):
    code: str
    name: str
    authority: str
    method: str
    bands: list[TaxBandOut]
    due: str
    source: str


class CountryRulesOut(BaseModel):
    """The rule set built from the organisation's settings in effect today."""

    rule_set_id: str
    income_tax: IncomeTaxOut
    lines: list[RuleLineOut]


class TaxSettingsOut(BaseModel):
    country_code: str
    country_name: str
    currency: str
    # False for a country whose rules take no Tax Settings (Nigeria).
    applies: bool
    rule_set_id: str | None
    effective_from: date | None
    effective_to: date | None
    approved_by: str | None
    approved_on: date | None
    approval_basis: str | None
    summary: list[str]  # paragraphs
    settings: list[TaxSettingOut]
    missing: list[str]  # keys of required settings with no value in effect today
    history: list[TaxSettingEntryOut]
    sources: list[SourceOut]
    # Settings may take effect only after this date.
    locked_through: date | None
    rules: CountryRulesOut | None  # once nothing is missing
    rules_problem: str | None  # why the rules couldn't be built, if they couldn't


class TaxSettingsUpdate(BaseModel):
    effective_from: date
    # Each value as a person enters it: "5.75" (a percentage), "1500.00"
    # (an amount in the organisation's currency), "15" (a day), or an
    # option's value.
    values: dict[str, str] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=500)
