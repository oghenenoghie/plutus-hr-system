"""VAT on customer invoices

Revision ID: e5b9c3f7a2d1
Revises: d4a8b2e6f1c3
Create Date: 2026-11-16 14:00:00.000000

An invoice records how VAT applies to it (standard, exempt, zero-rated, or a
rate the user names), the rate, and the VAT charged; amount_minor stays the
net amount and total_minor is what the customer owes. Existing invoices
charged no VAT, so their total is their amount.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b9c3f7a2d1"
down_revision: Union[str, Sequence[str], None] = "d4a8b2e6f1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("vat_treatment", sa.String(length=16), nullable=True))
    op.add_column("invoices", sa.Column("vat_rate_name", sa.String(length=64), nullable=True))
    op.add_column(
        "invoices", sa.Column("vat_rate_ppm", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "invoices", sa.Column("vat_minor", sa.BigInteger(), nullable=False, server_default="0")
    )
    op.add_column("invoices", sa.Column("total_minor", sa.BigInteger(), nullable=True))
    op.execute("UPDATE invoices SET total_minor = amount_minor + vat_minor")
    op.alter_column("invoices", "total_minor", existing_type=sa.BigInteger(), nullable=False)
    op.create_check_constraint(
        "ck_invoices_vat_treatment",
        "invoices",
        "vat_treatment IS NULL OR vat_treatment IN ('standard', 'exempt', 'zero_rated', 'other')",
    )
    op.create_check_constraint(
        "ck_invoices_vat_figures",
        "invoices",
        "vat_rate_ppm BETWEEN 0 AND 1000000 AND vat_minor >= 0 "
        "AND total_minor = amount_minor + vat_minor",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoices_vat_figures", "invoices", type_="check")
    op.drop_constraint("ck_invoices_vat_treatment", "invoices", type_="check")
    op.drop_column("invoices", "total_minor")
    op.drop_column("invoices", "vat_minor")
    op.drop_column("invoices", "vat_rate_ppm")
    op.drop_column("invoices", "vat_rate_name")
    op.drop_column("invoices", "vat_treatment")
