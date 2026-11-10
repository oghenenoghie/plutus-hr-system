"""chart account numbers and categories

Revision ID: a7c4e9d2b1f3
Revises: f1a2b3c4d5e6
Create Date: 2026-11-10 23:00:00.000000

Every chart account gets a four-digit number in its category's range
(app/domain/accounting/numbering.py) and a category that says where it's
reported: which section of the balance sheet or the profit and loss
account. `code` stays the key ledger lines are posted to. The accounts the
system posts to get their standard numbers; any other account gets the next
free number in its type's default range. "Cash" is renamed "Cash and Bank".

The numbering below is a copy, not an import, so this migration keeps doing
what it did when it was written.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c4e9d2b1f3"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RANGES = {
    "current_asset": (1000, 1499),
    "non_current_asset": (1500, 1999),
    "current_liability": (2000, 2499),
    "non_current_liability": (2500, 2999),
    "equity": (3000, 3999),
    "revenue": (4000, 4799),
    "other_income": (4800, 4999),
    "cost_of_sales": (5000, 5999),
    "operating_expense": (6000, 7999),
}
_DEFAULT = {
    "asset": "current_asset",
    "liability": "current_liability",
    "equity": "equity",
    "revenue": "revenue",
    "expense": "operating_expense",
}
_SYSTEM = {
    "cash": ("1000", "current_asset"),
    "accounts_receivable": ("1200", "current_asset"),
    "employee_loan_receivable": ("1210", "current_asset"),
    "vat_receivable": ("1300", "current_asset"),
    "wht_receivable": ("1310", "current_asset"),
    "inventory": ("1400", "current_asset"),
    "fixed_assets": ("1500", "non_current_asset"),
    "accumulated_depreciation": ("1590", "non_current_asset"),
    "right_of_use_assets": ("1600", "non_current_asset"),
    "accumulated_amortisation": ("1690", "non_current_asset"),
    "accounts_payable": ("2000", "current_liability"),
    "grni": ("2010", "current_liability"),
    "net_pay_payable": ("2110", "current_liability"),
    "paye_payable": ("2120", "current_liability"),
    "pension_payable": ("2130", "current_liability"),
    "nhf_payable": ("2140", "current_liability"),
    "nsitf_payable": ("2150", "current_liability"),
    "itf_payable": ("2160", "current_liability"),
    "union_dues_payable": ("2170", "current_liability"),
    "employee_reimbursements_payable": ("2180", "current_liability"),
    "vat_payable": ("2210", "current_liability"),
    "wht_payable": ("2220", "current_liability"),
    "customer_credits": ("2300", "current_liability"),
    "lease_liability": ("2500", "non_current_liability"),
    "share_capital": ("3000", "equity"),
    "retained_earnings": ("3100", "equity"),
    "revaluation_surplus": ("3300", "equity"),
    "opening_balance_equity": ("3900", "equity"),
    "inventory_opening_balance": ("3910", "equity"),
    "revenue": ("4000", "revenue"),
    "service_revenue": ("4100", "revenue"),
    "other_income": ("4800", "other_income"),
    "inventory_consumption": ("5000", "cost_of_sales"),
    "payroll_expense_gross": ("6010", "operating_expense"),
    "payroll_expense_employer_pension": ("6020", "operating_expense"),
    "payroll_expense_nsitf": ("6030", "operating_expense"),
    "payroll_expense_itf": ("6040", "operating_expense"),
    "benefit_deductions_recovered": ("6050", "operating_expense"),
    "contractor_expense": ("6100", "operating_expense"),
    "depreciation_expense": ("6800", "operating_expense"),
    "amortisation_expense": ("6810", "operating_expense"),
    "revaluation_loss": ("6820", "operating_expense"),
    "disposal_gain_loss": ("6830", "operating_expense"),
    "inventory_adjustment": ("6900", "operating_expense"),
}
_TYPE_OF = {
    "current_asset": "asset",
    "non_current_asset": "asset",
    "current_liability": "liability",
    "non_current_liability": "liability",
    "equity": "equity",
    "revenue": "revenue",
    "other_income": "revenue",
    "cost_of_sales": "expense",
    "operating_expense": "expense",
}


def _next_free(category: str, used: set[int]) -> str:
    low, high = _RANGES[category]
    for step in (10, 1):
        for candidate in range(low, high + 1, step):
            if candidate not in used:
                return str(candidate)
    raise RuntimeError(f"no free account number left in {low}-{high}")


def upgrade() -> None:
    op.add_column("chart_accounts", sa.Column("account_number", sa.String(length=20), nullable=True))
    op.add_column("chart_accounts", sa.Column("category", sa.String(length=32), nullable=True))

    connection = op.get_bind()
    org_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM organisations"))]
    for org_id in org_ids:
        # chart_accounts forces row-level security: read and write as the org.
        connection.execute(
            sa.text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)}
        )
        rows = connection.execute(
            sa.text(
                "SELECT id, code, type::text FROM chart_accounts "
                "WHERE org_id = :org ORDER BY created_at, code"
            ),
            {"org": org_id},
        ).all()
        used: set[int] = set()
        assigned: dict[object, tuple[str, str]] = {}
        later = []
        for account_id, code, account_type in rows:
            known = _SYSTEM.get(code)
            if known is not None and _TYPE_OF[known[1]] == account_type:
                assigned[account_id] = known
                used.add(int(known[0]))
            else:
                later.append((account_id, account_type))
        for account_id, account_type in later:
            category = _DEFAULT[account_type]
            number = _next_free(category, used)
            used.add(int(number))
            assigned[account_id] = (number, category)
        for account_id, (number, category) in assigned.items():
            connection.execute(
                sa.text(
                    "UPDATE chart_accounts SET account_number = :number, category = :category "
                    "WHERE id = :id"
                ),
                {"number": number, "category": category, "id": account_id},
            )
        connection.execute(
            sa.text(
                "UPDATE chart_accounts SET name = 'Cash and Bank' "
                "WHERE org_id = :org AND code = 'cash' AND name = 'Cash'"
            ),
            {"org": org_id},
        )
    connection.execute(sa.text("SELECT set_config('app.current_org', '', true)"))

    op.alter_column("chart_accounts", "account_number", nullable=False)
    op.alter_column("chart_accounts", "category", nullable=False)
    op.create_unique_constraint(
        "uq_chart_account_org_number", "chart_accounts", ["org_id", "account_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_chart_account_org_number", "chart_accounts", type_="unique")
    op.drop_column("chart_accounts", "category")
    op.drop_column("chart_accounts", "account_number")
