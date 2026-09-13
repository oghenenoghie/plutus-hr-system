"""overtime entries

Revision ID: 295b600fb515
Revises: d87c25a074c9
Create Date: 2026-09-13 00:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '295b600fb515'
down_revision: Union[str, Sequence[str], None] = 'd87c25a074c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'overtime_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('hours', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('rate_multiplier', sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'paid', name='overtime_status'), nullable=False),
        sa.Column('pay_run_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pay_run_id'], ['pay_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_overtime_entries_employee_id', 'overtime_entries', ['employee_id'])

    op.execute("ALTER TABLE overtime_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE overtime_entries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY overtime_entries_tenant_isolation ON overtime_entries "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_overtime_entries_employee_id', table_name='overtime_entries')
    op.drop_table('overtime_entries')
    sa.Enum(name='overtime_status').drop(op.get_bind(), checkfirst=False)
