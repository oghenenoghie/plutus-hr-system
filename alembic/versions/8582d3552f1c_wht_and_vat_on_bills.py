"""wht and vat on bills

Revision ID: 8582d3552f1c
Revises: 8cae37cb5b5e
Create Date: 2026-09-13 01:25:42.749196

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8582d3552f1c'
down_revision: Union[str, Sequence[str], None] = '8cae37cb5b5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'bills', sa.Column('vat_minor', sa.BigInteger(), nullable=False, server_default='0')
    )
    op.add_column('bills', sa.Column('wht_category', sa.String(length=64), nullable=True))
    op.add_column(
        'bills',
        sa.Column('wht_amount_minor', sa.BigInteger(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('bills', 'wht_amount_minor')
    op.drop_column('bills', 'wht_category')
    op.drop_column('bills', 'vat_minor')
