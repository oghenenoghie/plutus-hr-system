import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.engine.rules import CountryRuleSet
from app.domain.inventory.accounting import (
    ADJUSTMENT_ACCOUNT,
    CONSUMPTION_ACCOUNT,
    GRNI_ACCOUNT,
    INVENTORY_ACCOUNT,
    OPENING_BALANCE_ACCOUNT,
)
from app.models.chart_account import AccountType, ChartAccount
from app.services.jurisdiction import organisation_country

# The account codes payroll and WHT already write into ledger_entries.account
# (app/domain/payroll/postings.py, app/services/wht.py) — seeded so General
# Ledger has something to categorize those postings by from day one.
DEFAULT_ACCOUNTS: tuple[tuple[str, str, AccountType], ...] = (
    ("cash", "Cash", AccountType.ASSET),
    ("employee_loan_receivable", "Employee Loans Receivable", AccountType.ASSET),
    ("payroll_expense_gross", "Payroll Expense — Gross Pay", AccountType.EXPENSE),
    (
        "payroll_expense_employer_pension",
        "Payroll Expense — Employer Pension",
        AccountType.EXPENSE,
    ),
    ("payroll_expense_nsitf", "Payroll Expense — NSITF", AccountType.EXPENSE),
    ("contractor_expense", "Contractor Expense", AccountType.EXPENSE),
    ("paye_payable", "PAYE Payable", AccountType.LIABILITY),
    ("pension_payable", "Pension Payable", AccountType.LIABILITY),
    ("nhf_payable", "NHF Payable", AccountType.LIABILITY),
    ("nsitf_payable", "NSITF Payable", AccountType.LIABILITY),
    ("wht_payable", "WHT Payable", AccountType.LIABILITY),
    ("vat_receivable", "VAT Receivable", AccountType.ASSET),
    ("net_pay_payable", "Net Pay Payable", AccountType.LIABILITY),
    ("accounts_payable", "Accounts Payable", AccountType.LIABILITY),
    ("accounts_receivable", "Accounts Receivable", AccountType.ASSET),
    ("revenue", "Revenue", AccountType.REVENUE),
    ("fixed_assets", "Fixed Assets", AccountType.ASSET),
    (
        "accumulated_depreciation",
        "Accumulated Depreciation",
        AccountType.ASSET,
    ),
    ("depreciation_expense", "Depreciation Expense", AccountType.EXPENSE),
    ("disposal_gain_loss", "Gain/Loss on Disposal", AccountType.EXPENSE),
    ("revaluation_surplus", "Revaluation Surplus", AccountType.EQUITY),
    ("revaluation_loss", "Revaluation Loss", AccountType.EXPENSE),
)


# Statutory accounts only Nigerian payroll posts to; an organisation in
# another country doesn't get them, so its chart doesn't name schemes it
# doesn't have.
_NIGERIA_ONLY_ACCOUNTS = frozenset({"payroll_expense_nsitf", "nhf_payable", "nsitf_payable"})


# The accounts inventory posts to (docs/architecture/inventory-integration.md
# §15), seeded when an organisation's inventory accounting starts.
INVENTORY_ACCOUNTS: tuple[tuple[str, str, AccountType], ...] = (
    (INVENTORY_ACCOUNT, "Inventory", AccountType.ASSET),
    (GRNI_ACCOUNT, "Goods Received Not Invoiced", AccountType.LIABILITY),
    (CONSUMPTION_ACCOUNT, "Inventory Consumption", AccountType.EXPENSE),
    (ADJUSTMENT_ACCOUNT, "Inventory Adjustments and Write-offs", AccountType.EXPENSE),
    (OPENING_BALANCE_ACCOUNT, "Inventory Opening Balance", AccountType.EQUITY),
)


def seed_default_chart_of_accounts(db: Session, *, org_id: uuid.UUID) -> list[ChartAccount]:
    """Idempotent: only inserts codes the org doesn't already have, so it's
    safe to call against an org that has already customized its chart."""
    accounts = DEFAULT_ACCOUNTS
    if organisation_country(db, org_id) != "NG":
        accounts = tuple(a for a in DEFAULT_ACCOUNTS if a[0] not in _NIGERIA_ONLY_ACCOUNTS)
    return _seed(db, org_id=org_id, accounts=accounts)


# Accounts an engine payslip credits for what comes off the statutory net pay
# (Nigeria's payslip postings use the same three).
PAYROLL_DEDUCTION_ACCOUNTS: tuple[tuple[str, str, AccountType], ...] = (
    ("employee_loan_receivable", "Employee Loans Receivable", AccountType.ASSET),
    ("benefit_deductions_recovered", "Benefit Deductions Recovered", AccountType.EXPENSE),
    ("union_dues_payable", "Union Dues Payable", AccountType.LIABILITY),
)


def seed_rule_set_accounts(
    db: Session, *, org_id: uuid.UUID, rule_set: CountryRuleSet
) -> list[ChartAccount]:
    """Idempotent: the default chart, the payroll deduction accounts, and
    every payable and expense account the country's rule set names, so an
    engine pay run's postings can be checked against the chart. An account
    the org already has is left as it is."""
    created = seed_default_chart_of_accounts(db, org_id=org_id)
    accounts: dict[str, tuple[str, str, AccountType]] = {
        code: (code, name, kind) for code, name, kind in PAYROLL_DEDUCTION_ACCOUNTS
    }

    def add(code: str, name: str, kind: AccountType) -> None:
        accounts.setdefault(code, (code, name, kind))

    tax = rule_set.income_tax
    add(tax.liability_account, f"{tax.name} Payable", AccountType.LIABILITY)
    for rule in rule_set.contributions:
        add(rule.liability_account, f"{rule.name} Payable", AccountType.LIABILITY)
        if rule.expense_account:
            add(rule.expense_account, f"Payroll Expense — {rule.name}", AccountType.EXPENSE)
    for levy in rule_set.payroll_levies:
        add(levy.liability_account, f"{levy.name} Payable", AccountType.LIABILITY)
        add(levy.expense_account, f"Payroll Expense — {levy.name}", AccountType.EXPENSE)
    return created + _seed(db, org_id=org_id, accounts=tuple(accounts.values()))


def seed_inventory_accounts(db: Session, *, org_id: uuid.UUID) -> list[ChartAccount]:
    """Idempotent, like the default chart. An account the org already has is
    left alone, even if deactivated: posting to it then fails loudly rather
    than the seed quietly reviving it."""
    return _seed(db, org_id=org_id, accounts=INVENTORY_ACCOUNTS)


def _seed(
    db: Session, *, org_id: uuid.UUID, accounts: tuple[tuple[str, str, AccountType], ...]
) -> list[ChartAccount]:
    existing_codes = set(db.scalars(select(ChartAccount.code).where(ChartAccount.org_id == org_id)))
    created = []
    for code, name, account_type in accounts:
        if code in existing_codes:
            continue
        account = ChartAccount(
            org_id=org_id, code=code, name=name, type=account_type, is_system=True
        )
        db.add(account)
        created.append(account)
    if created:
        db.flush()
    return created


def register_chart_account(
    db: Session, *, org_id: uuid.UUID, code: str, name: str, type: AccountType
) -> ChartAccount:
    account = ChartAccount(org_id=org_id, code=code, name=name, type=type)
    db.add(account)
    db.flush()
    return account
