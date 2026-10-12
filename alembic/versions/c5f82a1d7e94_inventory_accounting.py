"""inventory accounting: GL posting, lock date, GRN-linked bills

Revision ID: c5f82a1d7e94
Revises: b7e41c2d9a63
Create Date: 2026-10-12 16:00:00.000000

Phase 3 of docs/architecture/inventory-integration.md (§15). Additive DDL
only, no backfill:

- journal_source_type gains goods_receipt, stock_issue, stock_adjustment and
  stock_transfer. ALTER TYPE ... ADD VALUE runs inside the transaction
  (PostgreSQL 12+) and nothing here uses the new values. Downgrade leaves
  them: PostgreSQL cannot drop an enum value, and an unused one is harmless.
- accounting_settings.lock_date (D13): nothing may be posted on or before it.
- inventory_settings.post_to_gl and gl_started_at. Existing rows start with
  posting off, so an organisation that already moved stock without journals
  switches it on deliberately (which posts its opening balance); rows created
  from now on start with it on.
- inventory_categories.expense_account_code (D18).
- bills.goods_receipt_id, with a partial unique index so a goods receipt is
  billed by at most one bill that isn't void (D2).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c5f82a1d7e94"
down_revision: Union[str, Sequence[str], None] = "b7e41c2d9a63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JOURNAL_SOURCES = ("goods_receipt", "stock_issue", "stock_adjustment", "stock_transfer")


def upgrade() -> None:
    for value in _JOURNAL_SOURCES:
        op.execute(f"ALTER TYPE journal_source_type ADD VALUE IF NOT EXISTS '{value}'")

    op.add_column("accounting_settings", sa.Column("lock_date", sa.Date(), nullable=True))

    op.add_column(
        "inventory_settings",
        sa.Column("post_to_gl", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "inventory_settings",
        sa.Column("gl_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_inventory_gl_started",
        "inventory_settings",
        "NOT post_to_gl OR gl_started_at IS NOT NULL",
    )

    op.add_column(
        "inventory_categories",
        sa.Column("expense_account_code", sa.String(length=64), nullable=True),
    )

    op.add_column(
        "bills",
        sa.Column("goods_receipt_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bills_goods_receipt_id",
        "bills",
        "inventory_goods_receipts",
        ["goods_receipt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_bill_goods_receipt",
        "bills",
        ["goods_receipt_id"],
        unique=True,
        postgresql_where=sa.text("goods_receipt_id IS NOT NULL AND status <> 'void'"),
    )


def downgrade() -> None:
    op.drop_index("uq_bill_goods_receipt", table_name="bills")
    op.drop_constraint("fk_bills_goods_receipt_id", "bills", type_="foreignkey")
    op.drop_column("bills", "goods_receipt_id")
    op.drop_column("inventory_categories", "expense_account_code")
    op.drop_constraint("ck_inventory_gl_started", "inventory_settings", type_="check")
    op.drop_column("inventory_settings", "gl_started_at")
    op.drop_column("inventory_settings", "post_to_gl")
    op.drop_column("accounting_settings", "lock_date")
