"""pay run reversal

Revision ID: 10de38077c13
Revises: 6f429c27b8a9
Create Date: 2026-09-08 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10de38077c13'
down_revision: Union[str, Sequence[str], None] = '6f429c27b8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # New enum member for an already-completed run that's been reversed.
    # Not usable in the same transaction it's added in (a Postgres
    # restriction on ALTER TYPE ... ADD VALUE) — fine, since this migration
    # never inserts a row using it.
    op.execute("ALTER TYPE pay_run_status ADD VALUE IF NOT EXISTS 'reversed'")
    op.add_column('pay_runs', sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no ALTER TYPE ... DROP VALUE — downgrading the enum
    # itself would require rebuilding the type, which risks data loss if
    # any row is actually 'reversed' by then. Out of scope for this
    # additive migration: only the column is reversed here.
    op.drop_column('pay_runs', 'reversed_at')
