import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.budget import Budget, BudgetLine
from app.models.chart_account import AccountType, ChartAccount
from app.models.ledger import LedgerEntry
from app.schemas.budgets import (
    BudgetLineActualOut,
    BudgetLineCreate,
    BudgetLineOut,
    BudgetOut,
    BudgetVsActualOut,
)

_BUDGETABLE_TYPES = (AccountType.REVENUE, AccountType.EXPENSE)


def _accounts_by_code(db: Session, *, org_id: uuid.UUID) -> dict[str, ChartAccount]:
    accounts = db.scalars(select(ChartAccount).where(ChartAccount.org_id == org_id))
    return {account.code: account for account in accounts}


def _validate_lines(
    lines: list[BudgetLineCreate], *, accounts_by_code: dict[str, ChartAccount]
) -> None:
    if not lines:
        raise ValueError("a budget needs at least one line")
    seen_codes: set[str] = set()
    for line in lines:
        if line.account_code in seen_codes:
            raise ValueError(f"duplicate account code in budget lines: {line.account_code}")
        seen_codes.add(line.account_code)
        if line.amount_minor <= 0:
            raise ValueError("amount_minor must be positive")
        account = accounts_by_code.get(line.account_code)
        if account is None or account.type not in _BUDGETABLE_TYPES:
            raise ValueError(f"{line.account_code!r} is not a known revenue/expense account")


def _budget_out(db: Session, budget: Budget) -> BudgetOut:
    accounts_by_code = _accounts_by_code(db, org_id=budget.org_id)
    lines = list(
        db.scalars(
            select(BudgetLine)
            .where(BudgetLine.budget_id == budget.id)
            .order_by(BudgetLine.account_code)
        )
    )
    line_outs = [
        BudgetLineOut(
            account_code=line.account_code,
            account_name=accounts_by_code[line.account_code].name,
            amount_minor=line.amount_minor,
        )
        for line in lines
    ]
    return BudgetOut(
        id=budget.id,
        org_id=budget.org_id,
        department_id=budget.department_id,
        name=budget.name,
        period_start=budget.period_start,
        period_end=budget.period_end,
        lines=line_outs,
        total_budgeted_minor=sum(line.amount_minor for line in line_outs),
        created_at=budget.created_at,
    )


def create_budget(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    period_start: date,
    period_end: date,
    lines: list[BudgetLineCreate],
    department_id: uuid.UUID | None = None,
) -> BudgetOut:
    if period_end < period_start:
        raise ValueError("period_end cannot be before period_start")
    accounts_by_code = _accounts_by_code(db, org_id=org_id)
    _validate_lines(lines, accounts_by_code=accounts_by_code)

    budget = Budget(
        org_id=org_id,
        department_id=department_id,
        name=name,
        period_start=period_start,
        period_end=period_end,
    )
    db.add(budget)
    db.flush()
    for line in lines:
        db.add(
            BudgetLine(
                org_id=org_id,
                budget_id=budget.id,
                account_code=line.account_code,
                amount_minor=line.amount_minor,
            )
        )
    db.flush()
    return _budget_out(db, budget)


def update_budget(
    db: Session,
    budget: Budget,
    *,
    name: str,
    period_start: date,
    period_end: date,
    lines: list[BudgetLineCreate],
    department_id: uuid.UUID | None = None,
) -> BudgetOut:
    if period_end < period_start:
        raise ValueError("period_end cannot be before period_start")
    accounts_by_code = _accounts_by_code(db, org_id=budget.org_id)
    _validate_lines(lines, accounts_by_code=accounts_by_code)

    budget.name = name
    budget.department_id = department_id
    budget.period_start = period_start
    budget.period_end = period_end
    db.add(budget)

    db.execute(delete(BudgetLine).where(BudgetLine.budget_id == budget.id))
    for line in lines:
        db.add(
            BudgetLine(
                org_id=budget.org_id,
                budget_id=budget.id,
                account_code=line.account_code,
                amount_minor=line.amount_minor,
            )
        )
    db.flush()
    return _budget_out(db, budget)


def delete_budget(db: Session, budget: Budget) -> None:
    db.execute(delete(BudgetLine).where(BudgetLine.budget_id == budget.id))
    db.delete(budget)
    db.flush()


def list_budgets(db: Session, *, org_id: uuid.UUID) -> list[BudgetOut]:
    budgets = db.scalars(
        select(Budget).where(Budget.org_id == org_id).order_by(Budget.period_start.desc())
    )
    return [_budget_out(db, budget) for budget in budgets]


def get_budget(db: Session, budget: Budget) -> BudgetOut:
    return _budget_out(db, budget)


def budget_vs_actual(db: Session, budget: Budget) -> BudgetVsActualOut:
    """Compares each budget line's amount against actual ledger activity
    for that account within [period_start, period_end]. Sign follows the
    same debit/credit convention as income_statement: revenue actuals are
    credit-debit, expense actuals are debit-credit, so both read as a
    positive number when there's actual revenue/expense to report.
    variance_minor is actual-minus-budgeted for both types: for expenses a
    positive variance means over budget, for revenue it means ahead of
    target.
    """
    accounts_by_code = _accounts_by_code(db, org_id=budget.org_id)
    lines = list(
        db.scalars(
            select(BudgetLine)
            .where(BudgetLine.budget_id == budget.id)
            .order_by(BudgetLine.account_code)
        )
    )

    stmt = select(LedgerEntry).where(
        LedgerEntry.created_at >= budget.period_start,
        LedgerEntry.created_at < budget.period_end + timedelta(days=1),
    )
    totals: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for entry in db.scalars(stmt):
        debit, credit = totals[entry.account]
        totals[entry.account] = (debit + entry.debit_minor, credit + entry.credit_minor)

    line_outs = []
    total_budgeted = total_actual = 0
    for line in lines:
        account = accounts_by_code[line.account_code]
        debit, credit = totals.get(line.account_code, (0, 0))
        actual = (credit - debit) if account.type == AccountType.REVENUE else (debit - credit)
        line_outs.append(
            BudgetLineActualOut(
                account_code=line.account_code,
                account_name=account.name,
                account_type=account.type,
                budgeted_minor=line.amount_minor,
                actual_minor=actual,
                variance_minor=actual - line.amount_minor,
            )
        )
        total_budgeted += line.amount_minor
        total_actual += actual

    return BudgetVsActualOut(
        budget_id=budget.id,
        name=budget.name,
        period_start=budget.period_start,
        period_end=budget.period_end,
        lines=line_outs,
        total_budgeted_minor=total_budgeted,
        total_actual_minor=total_actual,
        total_variance_minor=total_actual - total_budgeted,
    )
