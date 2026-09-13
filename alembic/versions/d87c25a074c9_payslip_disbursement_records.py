"""payslip disbursement records

Revision ID: d87c25a074c9
Revises: 03be04b1c06a
Create Date: 2026-09-12 23:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd87c25a074c9'
down_revision: Union[str, Sequence[str], None] = '03be04b1c06a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payslip_disbursement_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('payslip_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.Enum('settled', 'failed', name='payslip_disbursement_status'), nullable=False),
        sa.Column('reference', sa.String(length=255), nullable=True),
        sa.Column('note', sa.String(length=1000), nullable=True),
        sa.Column('recorded_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payslip_id'], ['payslips.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recorded_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_payslip_disbursement_records_payslip_id', 'payslip_disbursement_records', ['payslip_id']
    )

    op.execute("ALTER TABLE payslip_disbursement_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payslip_disbursement_records FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY payslip_disbursement_records_tenant_isolation ON payslip_disbursement_records "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    # Append-only, same discipline as payslip_deliveries: a retry after a
    # failed transfer is a new row, never an edit to a prior attempt.
    op.execute(
        "CREATE TRIGGER trg_payslip_disbursement_records_append_only "
        "BEFORE UPDATE OR DELETE ON payslip_disbursement_records "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_payslip_disbursement_records_payslip_id', table_name='payslip_disbursement_records'
    )
    op.drop_table('payslip_disbursement_records')
    sa.Enum(name='payslip_disbursement_status').drop(op.get_bind(), checkfirst=False)
