"""merge bank reconciliation and payslip deliveries

Revision ID: 95d3395aed77
Revises: e52ca61f91c7, f10533e504a5
Create Date: 2026-09-07 23:27:12.057880

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95d3395aed77'
down_revision: Union[str, Sequence[str], None] = ('e52ca61f91c7', 'f10533e504a5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
