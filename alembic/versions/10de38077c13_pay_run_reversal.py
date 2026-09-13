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
    # IF NOT EXISTS: a separately-merged migration (pay run lock lifecycle,
    # on the other side of this branch merge) may have already added this
    # column via its own enum rename/rebuild — whichever of the two runs
    # second in a merged history must not fail on the other's work.
    op.execute("ALTER TABLE pay_runs ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMPTZ")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no ALTER TYPE ... DROP VALUE — downgrading the enum
    # itself would require rebuilding the type, which risks data loss if
    # any row is actually 'reversed' by then. Out of scope for this
    # additive migration: only the column is reversed here.
    op.execute("ALTER TABLE pay_runs DROP COLUMN IF EXISTS reversed_at")
