"""public holidays

Revision ID: 51264e94191e
Revises: 2136f113f575
Create Date: 2026-09-13 10:59:53.481486

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51264e94191e'
down_revision: Union[str, Sequence[str], None] = '2136f113f575'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('public_holidays',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('holiday_date', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'holiday_date', name='uq_public_holiday_org_date')
    )

    # Tenant isolation, same ENABLE + FORCE + policy pattern as every other
    # business table.
    op.execute("ALTER TABLE public_holidays ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public_holidays FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY public_holidays_tenant_isolation ON public_holidays "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('public_holidays')
