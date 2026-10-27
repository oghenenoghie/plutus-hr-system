"""What every country's rule set here shares: the approval record, the
source that stands for an organisation's own Tax Settings, and small
helpers for writing figures as published."""

from datetime import date
from decimal import Decimal

from app.compliance.engine.rules import (
    PPM,
    Approval,
    ApprovalBasis,
    DueDayOfFollowingMonth,
    EarningCategory,
    Rounding,
    RoundingMode,
    SourceReference,
)
from app.compliance.engine.settings import SettingOption, SettingValues
from app.domain.money import minor_units_exponent

# Approved by the product owner from the drafts in docs/countries, without a
# local tax adviser's review (docs/architecture/multicountry-tax.md, Part 3).
APPROVAL = Approval(
    prepared_by="Plutus engineering, from docs/countries (25 and 26 October 2026)",
    approved_by="Plutus Technologies",
    approved_on=date(2026, 10, 27),
    basis=ApprovalBasis.OWNER_APPROVED,
)

# Cited by a rule whose figure comes from the organisation's Tax Settings.
COMPANY_SETTINGS = SourceReference(
    id="company-settings",
    title="Entered by your organisation under Tax Settings",
    reference="Plutus Tax Settings",
    official=False,
    captured_on=date(2026, 10, 27),
)

RESEARCHED = date(2026, 10, 25)  # when the drafts' sources were captured

ALL_CASH = frozenset(EarningCategory)
BASIC_ONLY = frozenset({EarningCategory.BASIC})
# Basic pay and every recurring allowance: what sources call "basic plus
# fixed allowances". Overtime and one-off pay are left out.
FIXED_PAY = frozenset(
    {
        EarningCategory.BASIC,
        EarningCategory.HOUSING,
        EarningCategory.TRANSPORT,
        EarningCategory.FIXED_ALLOWANCE,
    }
)

HALF_UP = Rounding(RoundingMode.HALF_UP)


def due(day: int) -> DueDayOfFollowingMonth:
    return DueDayOfFollowingMonth(day)


def ppm(percent: str) -> int:
    """A published percentage ("2.75") in parts per million."""
    value = Decimal(percent) * PPM / 100
    if value != value.to_integral_value():
        raise ValueError(f"{percent}% isn't a whole number of parts per million")
    return int(value)


def money(amount: str, currency: str) -> int:
    """A published amount ("24,000") in the currency's minor units."""
    value = Decimal(amount.replace(",", "")).scaleb(minor_units_exponent(currency))
    if value != value.to_integral_value():
        raise ValueError(f"{amount} {currency} has more decimals than {currency} allows")
    return int(value)


def yes(values: SettingValues, key: str) -> bool:
    return values.get(key) == "yes"


def option(value: str, label: str, source: str) -> SettingOption:
    return SettingOption(value=value, label=label, source=source)
