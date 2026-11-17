"""VAT treatment on vendor bills

Revision ID: b8d4f0a6c2e9
Revises: a6c2d8e4b1f7
Create Date: 2026-11-17 09:30:00.000000

A bill records how VAT applies to it, as an invoice does: standard, exempt,
zero-rated, or a rate the user names, with the rate's name and the rate.
Existing bills keep the VAT amount entered on them, with no treatment.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d4f0a6c2e9"
down_revision: Union[str, Sequence[str], None] = "a6c2d8e4b1f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bills", sa.Column("vat_treatment", sa.String(length=16), nullable=True))
    op.add_column("bills", sa.Column("vat_rate_name", sa.String(length=64), nullable=True))
    op.add_column(
        "bills", sa.Column("vat_rate_ppm", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_check_constraint(
        "ck_bills_vat_treatment",
        "bills",
        "vat_treatment IS NULL OR vat_treatment IN ('standard', 'exempt', 'zero_rated', 'other')",
    )
    op.create_check_constraint(
        "ck_bills_vat_figures", "bills", "vat_rate_ppm BETWEEN 0 AND 1000000 AND vat_minor >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_bills_vat_figures", "bills", type_="check")
    op.drop_constraint("ck_bills_vat_treatment", "bills", type_="check")
    op.drop_column("bills", "vat_rate_ppm")
    op.drop_column("bills", "vat_rate_name")
    op.drop_column("bills", "vat_treatment")
