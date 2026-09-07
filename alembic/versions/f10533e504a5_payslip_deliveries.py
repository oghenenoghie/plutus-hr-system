"""payslip deliveries

Revision ID: f10533e504a5
Revises: a63e6cc2a60b
Create Date: 2026-09-07 23:00:41.175990

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f10533e504a5'
down_revision: Union[str, Sequence[str], None] = 'a63e6cc2a60b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payslip_deliveries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('payslip_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.Enum('sent', 'failed', name='payslip_delivery_status'), nullable=False),
        sa.Column('recipient_email', sa.String(length=320), nullable=False),
        sa.Column('provider_message_id', sa.String(length=255), nullable=True),
        sa.Column('error', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payslip_id'], ['payslips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_payslip_deliveries_payslip_id', 'payslip_deliveries', ['payslip_id']
    )

    op.execute("ALTER TABLE payslip_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payslip_deliveries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY payslip_deliveries_tenant_isolation ON payslip_deliveries "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    # Append-only, same discipline as payslips/ledger_entries/audit_logs: a
    # retry is a new delivery row, never an edit to a prior attempt.
    op.execute(
        "CREATE TRIGGER trg_payslip_deliveries_append_only "
        "BEFORE UPDATE OR DELETE ON payslip_deliveries "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_payslip_deliveries_payslip_id', table_name='payslip_deliveries')
    op.drop_table('payslip_deliveries')
    sa.Enum(name='payslip_delivery_status').drop(op.get_bind(), checkfirst=False)
