"""customer and vendor addresses

Revision ID: b8d5f0e3c2a4
Revises: a7c4e9d2b1f3
Create Date: 2026-11-10 23:30:00.000000

A postal address for each customer and vendor, printed on invoices and
bills.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d5f0e3c2a4"
down_revision: Union[str, Sequence[str], None] = "a7c4e9d2b1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("vendors", sa.Column("address", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("vendors", "address")
    op.drop_column("customers", "address")
