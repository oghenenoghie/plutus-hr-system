"""salary masking

Revision ID: 6f429c27b8a9
Revises: 5f5b845b6b6d
Create Date: 2026-09-08 11:17:16.103587

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f429c27b8a9'
down_revision: Union[str, Sequence[str], None] = '5f5b845b6b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default backfills existing rows to false at ADD COLUMN time —
    # required since this table can already hold data, unlike a create_table.
    op.add_column(
        'employees',
        sa.Column('salary_masked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('employees', 'salary_masked', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('employees', 'salary_masked')
