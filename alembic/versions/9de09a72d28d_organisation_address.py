"""organisation address

Revision ID: 9de09a72d28d
Revises: de798b342bdb
Create Date: 2026-10-04 11:00:00.000000

Adds the company's address alongside its RC number and TIN. Nullable, so
existing organisations are unaffected until an admin fills it in.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9de09a72d28d"
down_revision: Union[str, Sequence[str], None] = "de798b342bdb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("organisations", sa.Column("address", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("organisations", "address")
