"""department allocation on ledger entries

Revision ID: 608ff82fccfb
Revises: 975bffdadec3
Create Date: 2026-09-13 11:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '608ff82fccfb'
down_revision: Union[str, Sequence[str], None] = '975bffdadec3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ledger_entries', sa.Column('department_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_ledger_entries_department_id', 'ledger_entries', 'departments', ['department_id'],
        ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_ledger_entries_department_id', 'ledger_entries', type_='foreignkey')
    op.drop_column('ledger_entries', 'department_id')
