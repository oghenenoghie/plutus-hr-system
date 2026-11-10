"""Account numbers and categories for the chart of accounts.

An account's `code` (the slug every ledger line is posted to, e.g. `cash`)
never changes: history is written against it. Accountants work with the
account *number* instead ("1000 Cash and Bank"), which sits in a range by
category, and the category says where the account is reported: which
section of the balance sheet, or of the profit and loss account
(ACCOUNTING_IMPLEMENTATION_AUDIT.md §15.3, §16).

Ranges, four digits as §16.3 proposes, with the profit and loss side split
into revenue, cost of sales and overheads as the reviewing accountant asked:

    1000-1499  current assets          2000-2499  current liabilities
    1500-1999  non-current assets      2500-2999  non-current liabilities
    3000-3999  equity (capital and reserves)
    4000-4799  revenue                 4800-4999  other income
    5000-5999  cost of sales           6000-7999  overheads (operating expenses)
"""

import enum
from collections.abc import Iterable

# The chart account types (app.models.chart_account.AccountType values),
# kept as plain strings so this module stays free of the ORM; AccountType
# is a str enum, so its members compare equal to these.
ASSET = "asset"
LIABILITY = "liability"
EQUITY = "equity"
REVENUE = "revenue"
EXPENSE = "expense"


class AccountCategory(str, enum.Enum):
    CURRENT_ASSET = "current_asset"
    NON_CURRENT_ASSET = "non_current_asset"
    CURRENT_LIABILITY = "current_liability"
    NON_CURRENT_LIABILITY = "non_current_liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    OTHER_INCOME = "other_income"
    COST_OF_SALES = "cost_of_sales"
    OPERATING_EXPENSE = "operating_expense"


CATEGORY_TYPE: dict[AccountCategory, str] = {
    AccountCategory.CURRENT_ASSET: ASSET,
    AccountCategory.NON_CURRENT_ASSET: ASSET,
    AccountCategory.CURRENT_LIABILITY: LIABILITY,
    AccountCategory.NON_CURRENT_LIABILITY: LIABILITY,
    AccountCategory.EQUITY: EQUITY,
    AccountCategory.REVENUE: REVENUE,
    AccountCategory.OTHER_INCOME: REVENUE,
    AccountCategory.COST_OF_SALES: EXPENSE,
    AccountCategory.OPERATING_EXPENSE: EXPENSE,
}

CATEGORY_RANGES: dict[AccountCategory, tuple[int, int]] = {
    AccountCategory.CURRENT_ASSET: (1000, 1499),
    AccountCategory.NON_CURRENT_ASSET: (1500, 1999),
    AccountCategory.CURRENT_LIABILITY: (2000, 2499),
    AccountCategory.NON_CURRENT_LIABILITY: (2500, 2999),
    AccountCategory.EQUITY: (3000, 3999),
    AccountCategory.REVENUE: (4000, 4799),
    AccountCategory.OTHER_INCOME: (4800, 4999),
    AccountCategory.COST_OF_SALES: (5000, 5999),
    AccountCategory.OPERATING_EXPENSE: (6000, 7999),
}

CATEGORY_LABELS: dict[AccountCategory, str] = {
    AccountCategory.CURRENT_ASSET: "Current assets",
    AccountCategory.NON_CURRENT_ASSET: "Non-current assets",
    AccountCategory.CURRENT_LIABILITY: "Current liabilities",
    AccountCategory.NON_CURRENT_LIABILITY: "Non-current liabilities",
    AccountCategory.EQUITY: "Capital and reserves",
    AccountCategory.REVENUE: "Revenue",
    AccountCategory.OTHER_INCOME: "Other income",
    AccountCategory.COST_OF_SALES: "Cost of sales",
    AccountCategory.OPERATING_EXPENSE: "Overheads",
}

# Where an account of each type goes when nothing more specific is known
# (a custom account, or a country payroll account like ssnit_payable).
DEFAULT_CATEGORY: dict[str, AccountCategory] = {
    ASSET: AccountCategory.CURRENT_ASSET,
    LIABILITY: AccountCategory.CURRENT_LIABILITY,
    EQUITY: AccountCategory.EQUITY,
    REVENUE: AccountCategory.REVENUE,
    EXPENSE: AccountCategory.OPERATING_EXPENSE,
}

_CA = AccountCategory.CURRENT_ASSET
_NCA = AccountCategory.NON_CURRENT_ASSET
_CL = AccountCategory.CURRENT_LIABILITY
_NCL = AccountCategory.NON_CURRENT_LIABILITY
_EQ = AccountCategory.EQUITY
_REV = AccountCategory.REVENUE
_OI = AccountCategory.OTHER_INCOME
_COS = AccountCategory.COST_OF_SALES
_OPEX = AccountCategory.OPERATING_EXPENSE

# The accounts the system posts to, at the numbers the audit's default chart
# (§15.3) gives them, with payroll and the other overheads moved to the
# 6000s so that 5000s are cost of sales.
SYSTEM_ACCOUNT_NUMBERS: dict[str, tuple[str, AccountCategory]] = {
    "cash": ("1000", _CA),
    "accounts_receivable": ("1200", _CA),
    "employee_loan_receivable": ("1210", _CA),
    "vat_receivable": ("1300", _CA),
    "wht_receivable": ("1310", _CA),
    "inventory": ("1400", _CA),
    "fixed_assets": ("1500", _NCA),
    "accumulated_depreciation": ("1590", _NCA),
    "right_of_use_assets": ("1600", _NCA),
    "accumulated_amortisation": ("1690", _NCA),
    "accounts_payable": ("2000", _CL),
    "grni": ("2010", _CL),
    "net_pay_payable": ("2110", _CL),
    "paye_payable": ("2120", _CL),
    "pension_payable": ("2130", _CL),
    "nhf_payable": ("2140", _CL),
    "nsitf_payable": ("2150", _CL),
    "itf_payable": ("2160", _CL),
    "union_dues_payable": ("2170", _CL),
    "employee_reimbursements_payable": ("2180", _CL),
    "vat_payable": ("2210", _CL),
    "wht_payable": ("2220", _CL),
    "customer_credits": ("2300", _CL),
    "lease_liability": ("2500", _NCL),
    "share_capital": ("3000", _EQ),
    "retained_earnings": ("3100", _EQ),
    "revaluation_surplus": ("3300", _EQ),
    "opening_balance_equity": ("3900", _EQ),
    "inventory_opening_balance": ("3910", _EQ),
    "revenue": ("4000", _REV),
    "service_revenue": ("4100", _REV),
    "other_income": ("4800", _OI),
    "inventory_consumption": ("5000", _COS),
    "payroll_expense_gross": ("6010", _OPEX),
    "payroll_expense_employer_pension": ("6020", _OPEX),
    "payroll_expense_nsitf": ("6030", _OPEX),
    "payroll_expense_itf": ("6040", _OPEX),
    "benefit_deductions_recovered": ("6050", _OPEX),
    "contractor_expense": ("6100", _OPEX),
    "depreciation_expense": ("6800", _OPEX),
    "amortisation_expense": ("6810", _OPEX),
    "revaluation_loss": ("6820", _OPEX),
    "disposal_gain_loss": ("6830", _OPEX),
    "inventory_adjustment": ("6900", _OPEX),
}


def _plain(account_type: str) -> str:
    # An AccountType member formats as "AccountType.ASSET"; its value is "asset".
    return str(getattr(account_type, "value", account_type))


def category_for(code: str, account_type: str) -> AccountCategory:
    """The system category for a code the system posts to, else the default
    for the account's type."""
    known = SYSTEM_ACCOUNT_NUMBERS.get(code)
    if known is not None and CATEGORY_TYPE[known[1]] == account_type:
        return known[1]
    return DEFAULT_CATEGORY[account_type]


def check_category(category: AccountCategory, account_type: str) -> None:
    if CATEGORY_TYPE[category] != account_type:
        raise ValueError(
            f"{CATEGORY_LABELS[category]} accounts are {CATEGORY_TYPE[category]} accounts, "
            f"not {_plain(account_type)}"
        )


def check_number(number: str, category: AccountCategory) -> None:
    """A number is four digits within its category's range."""
    low, high = CATEGORY_RANGES[category]
    if not number.isdigit() or len(number) != 4 or not low <= int(number) <= high:
        raise ValueError(
            f"{CATEGORY_LABELS[category]} accounts are numbered {low}–{high}; "
            f"{number!r} isn't in that range"
        )


def next_free_number(category: AccountCategory, taken: Iterable[str]) -> str:
    """The lowest unused number in the category's range, in steps of 10 when
    there's room (1010, 1020, ...) so related accounts can go in between,
    and otherwise the lowest unused number at all."""
    low, high = CATEGORY_RANGES[category]
    used = {int(number) for number in taken if number.isdigit()}
    for candidate in range(low, high + 1, 10):
        if candidate not in used:
            return str(candidate)
    for candidate in range(low, high + 1):
        if candidate not in used:
            return str(candidate)
    raise ValueError(f"every number from {low} to {high} is in use")


def number_for(code: str, account_type: str, taken: Iterable[str]) -> tuple[str, AccountCategory]:
    """The number and category a new account gets: the system number if it
    has one and that number is free, else the next free one in its range."""
    taken_set = set(taken)
    category = category_for(code, account_type)
    known = SYSTEM_ACCOUNT_NUMBERS.get(code)
    if known is not None and known[1] == category and known[0] not in taken_set:
        return known[0], category
    return next_free_number(category, taken_set), category
