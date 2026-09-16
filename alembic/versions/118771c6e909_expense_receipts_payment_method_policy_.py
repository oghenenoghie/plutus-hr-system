"""expense receipts, payment method, policy limits

Revision ID: 118771c6e909
Revises: 58b1634331a9
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '118771c6e909'
down_revision: Union[str, Sequence[str], None] = '58b1634331a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('expenses', sa.Column('receipt_url', sa.String(length=2048), nullable=True))

    payment_method = postgresql.ENUM(
        'reimbursement', 'direct_payment', name='expense_payment_method'
    )
    payment_method.create(op.get_bind())
    op.add_column(
        'expenses',
        sa.Column(
            'payment_method', payment_method, nullable=False, server_default='reimbursement'
        ),
    )

    op.create_table(
        'expense_policy_limits',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('max_amount_minor', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'category', name='uq_expense_policy_limit'),
    )
    op.execute("ALTER TABLE expense_policy_limits ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE expense_policy_limits FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY expense_policy_limits_tenant_isolation ON expense_policy_limits "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('expense_policy_limits')
    op.drop_column('expenses', 'payment_method')
    postgresql.ENUM(name='expense_payment_method').drop(op.get_bind())
    op.drop_column('expenses', 'receipt_url')
