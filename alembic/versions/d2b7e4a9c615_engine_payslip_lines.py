"""engine payslip lines

Revision ID: d2b7e4a9c615
Revises: c4e8b2d6f913
Create Date: 2026-10-26 14:00:00.000000

Stage 2 of the country-neutral payroll engine
(docs/architecture/multicountry-tax.md, Part 3): what a pay run in a country
on the engine records. Nothing here changes Nigeria, whose payslips keep
their own columns.

- payslip_statutory_lines: each payslip's statutory lines as the engine
  worked them out, in calculation order (code, kind, authority, base, rate, amount, accounts, due
  date, the source it cites and the rule set it came from). Tenant-isolated
  and append-only, like payslips.
- statutory_liabilities: a 'country' scheme for an obligation from a
  country's own rule set, naming its line codes and the payable account its
  remittance clears.
- employees: the two figures some countries' rules need and Plutus didn't
  hold: family shares counted in halves, and whether the employee is an
  expatriate. Both null until recorded; a rule that needs one refuses to
  calculate without it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2b7e4a9c615"
down_revision: Union[str, Sequence[str], None] = "c4e8b2d6f913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payslip_statutory_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payslip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pay_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_set_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("authority", sa.String(length=255), nullable=False),
        sa.Column("base_minor", sa.BigInteger(), nullable=False),
        sa.Column("rate_ppm", sa.Integer(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("liability_account", sa.String(length=64), nullable=False),
        sa.Column("expense_account", sa.String(length=64), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('employee_contribution', 'employer_contribution', 'income_tax')",
            name="ck_payslip_statutory_lines_kind",
        ),
        sa.CheckConstraint(
            "base_minor >= 0 AND amount_minor >= 0", name="ck_payslip_statutory_lines_amounts"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payslip_id"], ["payslips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pay_run_id"], ["pay_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payslip_statutory_lines_payslip_id", "payslip_statutory_lines", ["payslip_id"]
    )
    op.create_index(
        "ix_payslip_statutory_lines_pay_run_id", "payslip_statutory_lines", ["pay_run_id"]
    )
    op.execute("ALTER TABLE payslip_statutory_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payslip_statutory_lines FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY payslip_statutory_lines_tenant_isolation ON payslip_statutory_lines "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )
    # Append-only, like the payslip it belongs to.
    op.execute(
        "CREATE TRIGGER trg_payslip_statutory_lines_append_only "
        "BEFORE UPDATE OR DELETE ON payslip_statutory_lines "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )

    # The new value can't be used in this transaction, so the check below
    # compares the column as text rather than against the enum literal.
    op.execute("ALTER TYPE liability_scheme ADD VALUE IF NOT EXISTS 'country'")
    op.add_column("statutory_liabilities", sa.Column("line_code", sa.String(length=255)))
    op.add_column("statutory_liabilities", sa.Column("liability_account", sa.String(length=64)))
    op.create_check_constraint(
        "ck_statutory_liabilities_country_line",
        "statutory_liabilities",
        "(scheme::text = 'country') = (line_code IS NOT NULL AND liability_account IS NOT NULL)",
    )

    op.add_column("employees", sa.Column("tax_half_shares", sa.Integer()))
    op.add_column("employees", sa.Column("is_expatriate", sa.Boolean()))
    op.create_check_constraint("ck_employees_tax_half_shares", "employees", "tax_half_shares >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_employees_tax_half_shares", "employees", type_="check")
    op.drop_column("employees", "is_expatriate")
    op.drop_column("employees", "tax_half_shares")

    # Postgres can't drop an enum value; 'country' stays on the type, unused.
    op.drop_constraint(
        "ck_statutory_liabilities_country_line", "statutory_liabilities", type_="check"
    )
    op.execute("DELETE FROM statutory_liabilities WHERE scheme::text = 'country'")
    op.drop_column("statutory_liabilities", "liability_account")
    op.drop_column("statutory_liabilities", "line_code")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_payslip_statutory_lines_append_only ON payslip_statutory_lines"
    )
    op.drop_index("ix_payslip_statutory_lines_pay_run_id", table_name="payslip_statutory_lines")
    op.drop_index("ix_payslip_statutory_lines_payslip_id", table_name="payslip_statutory_lines")
    op.drop_table("payslip_statutory_lines")
