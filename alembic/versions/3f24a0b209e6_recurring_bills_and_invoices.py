"""recurring bills and invoices

Revision ID: 3f24a0b209e6
Revises: 8582d3552f1c
Create Date: 2026-09-13 01:31:14.763371

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f24a0b209e6'
down_revision: Union[str, Sequence[str], None] = '8582d3552f1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Two distinct Postgres enum types (rather than one shared type) — the
    # simpler, more robust option: RecurringBill.frequency and
    # RecurringInvoice.frequency both map to the same Python
    # RecurrenceFrequency, but there's no need for them to share a single
    # DB-level type, and Alembic's op.create_table doesn't reliably honor
    # create_type=False for a type created ahead of a table that needs it.
    op.create_table(
        'recurring_bills',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('bill_number_prefix', sa.String(length=64), nullable=False),
        sa.Column('expense_account_code', sa.String(length=64), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('vat_minor', sa.BigInteger(), nullable=False),
        sa.Column('wht_category', sa.String(length=64), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('due_in_days', sa.Integer(), nullable=False),
        sa.Column(
            'frequency',
            sa.Enum('monthly', 'quarterly', 'annually', name='recurring_bill_frequency'),
            nullable=False,
        ),
        sa.Column('next_run_date', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'recurring_invoices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('invoice_number_prefix', sa.String(length=64), nullable=False),
        sa.Column('revenue_account_code', sa.String(length=64), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('due_in_days', sa.Integer(), nullable=False),
        sa.Column(
            'frequency',
            sa.Enum('monthly', 'quarterly', 'annually', name='recurring_invoice_frequency'),
            nullable=False,
        ),
        sa.Column('next_run_date', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    for table in ('recurring_bills', 'recurring_invoices'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('recurring_invoices')
    op.drop_table('recurring_bills')
    sa.Enum(name='recurring_invoice_frequency').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='recurring_bill_frequency').drop(op.get_bind(), checkfirst=False)
