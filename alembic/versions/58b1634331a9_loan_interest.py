"""loan interest (flat rate, employer policy, default interest-free)

Revision ID: 58b1634331a9
Revises: 739cd8ef384b
Create Date: 2026-09-15 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58b1634331a9'
down_revision: Union[str, Sequence[str], None] = '739cd8ef384b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'loans', sa.Column('interest_rate_bps', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'loans', sa.Column('total_repayable_minor', sa.BigInteger(), nullable=True)
    )
    # Existing loans are interest-free (they predate interest_rate_bps),
    # so total_repayable_minor starts out equal to principal_minor for
    # every row already in the table — this is a backfill, not a default,
    # since it depends on each row's own principal.
    op.execute("UPDATE loans SET total_repayable_minor = principal_minor")
    op.alter_column('loans', 'total_repayable_minor', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('loans', 'total_repayable_minor')
    op.drop_column('loans', 'interest_rate_bps')
