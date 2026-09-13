"""contract expiry alerting

Revision ID: 3203eefbd3d2
Revises: 51264e94191e
Create Date: 2026-09-13 11:16:43.357668

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3203eefbd3d2'
down_revision: Union[str, Sequence[str], None] = '51264e94191e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('employees', sa.Column('contract_end_date', sa.Date(), nullable=True))
    op.add_column(
        'employees',
        sa.Column(
            'contract_expiry_notified', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # Same as salary_masking's own migration: the server_default only
    # exists to backfill existing rows — new rows always pass an explicit
    # value via the ORM default, so drop it once the column is populated.
    op.alter_column('employees', 'contract_expiry_notified', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('employees', 'contract_expiry_notified')
    op.drop_column('employees', 'contract_end_date')
