"""merge bank reconciliation rename and pay run reversal

Revision ID: 2136f113f575
Revises: 10de38077c13, 90595267d0ff
Create Date: 2026-09-13 08:59:35.410822

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2136f113f575'
down_revision: Union[str, Sequence[str], None] = ('10de38077c13', '90595267d0ff')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
