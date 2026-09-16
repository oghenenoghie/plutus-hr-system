"""employee hosted photos

Revision ID: 9c6db0cbfa01
Revises: 2ed05b300119
Create Date: 2026-09-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c6db0cbfa01'
down_revision: Union[str, Sequence[str], None] = '2ed05b300119'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'employees',
        sa.Column('photo_version', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'employees', sa.Column('photo_consent_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_column('employees', 'photo_url')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('employees', sa.Column('photo_url', sa.String(length=1000), nullable=True))
    op.drop_column('employees', 'photo_consent_at')
    op.drop_column('employees', 'photo_version')
