"""merge bank reconciliation and audit log

Revision ID: e52ca61f91c7
Revises: 9bc9cac6e200, a63e6cc2a60b
Create Date: 2026-09-07 23:19:32.798456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e52ca61f91c7'
down_revision: Union[str, Sequence[str], None] = ('9bc9cac6e200', 'a63e6cc2a60b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
