"""subscriptions

Revision ID: 70d21c04a0f8
Revises: 19cacf95c5bd
Create Date: 2026-09-13 01:58:43.963546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70d21c04a0f8'
down_revision: Union[str, Sequence[str], None] = '19cacf95c5bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column(
            'plan_code',
            sa.Enum('free', 'starter', 'professional', 'enterprise', name='subscription_plan_code'),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.Enum('active', 'past_due', 'canceled', name='subscription_status'),
            nullable=False,
        ),
        sa.Column('current_period_end', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', name='uq_subscription_org'),
    )

    op.execute("ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY subscriptions_tenant_isolation ON subscriptions "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('subscriptions')
    sa.Enum(name='subscription_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='subscription_plan_code').drop(op.get_bind(), checkfirst=False)
