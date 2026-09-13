"""contractor invoicing and richer onboarding

Revision ID: b6ea32f8e106
Revises: 608ff82fccfb
Create Date: 2026-09-13 11:35:57.465576

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6ea32f8e106'
down_revision: Union[str, Sequence[str], None] = '608ff82fccfb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('contractor_invoices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('contractor_id', sa.UUID(), nullable=False),
    sa.Column('wht_payment_id', sa.UUID(), nullable=True),
    sa.Column('invoice_number', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('invoice_date', sa.Date(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('status', sa.Enum('draft', 'submitted', 'paid', name='contractor_invoice_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['contractor_id'], ['contractors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['wht_payment_id'], ['wht_payments.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'contractor_id', 'invoice_number', name='uq_contractor_invoice_number')
    )
    op.add_column('contractors', sa.Column('email', sa.String(length=320), nullable=True))
    op.add_column('contractors', sa.Column('phone', sa.String(length=32), nullable=True))
    op.add_column('contractors', sa.Column('engagement_start_date', sa.Date(), nullable=True))
    op.add_column('contractors', sa.Column('engagement_end_date', sa.Date(), nullable=True))

    # Tenant isolation, same ENABLE + FORCE + policy pattern as every other
    # business table.
    op.execute("ALTER TABLE contractor_invoices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE contractor_invoices FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY contractor_invoices_tenant_isolation ON contractor_invoices "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('contractors', 'engagement_end_date')
    op.drop_column('contractors', 'engagement_start_date')
    op.drop_column('contractors', 'phone')
    op.drop_column('contractors', 'email')
    op.drop_table('contractor_invoices')
