import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chart_account import AccountType, ChartAccount

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


def seed_default_chart_of_accounts(db: Session, *, org_id: uuid.UUID) -> list[ChartAccount]:
    """Idempotent: only inserts codes the org doesn't already have, so it's
    safe to call against an org that has already customized its chart."""
    existing_codes = set(db.scalars(select(ChartAccount.code).where(ChartAccount.org_id == org_id)))
    created = []
    for code, name, account_type in DEFAULT_ACCOUNTS:
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
