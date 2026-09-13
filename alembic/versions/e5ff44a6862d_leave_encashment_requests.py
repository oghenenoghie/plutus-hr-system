"""leave encashment requests

Revision ID: e5ff44a6862d
Revises: 295b600fb515
Create Date: 2026-09-13 00:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5ff44a6862d'
down_revision: Union[str, Sequence[str], None] = '295b600fb515'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'leave_encashment_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('requested_date', sa.Date(), nullable=False),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'paid', name='leave_encashment_status'), nullable=False),
        sa.Column('pay_run_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pay_run_id'], ['pay_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_leave_encashment_requests_employee_id', 'leave_encashment_requests', ['employee_id']
    )

    op.execute("ALTER TABLE leave_encashment_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leave_encashment_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY leave_encashment_requests_tenant_isolation ON leave_encashment_requests "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_leave_encashment_requests_employee_id', table_name='leave_encashment_requests'
    )
    op.drop_table('leave_encashment_requests')
    sa.Enum(name='leave_encashment_status').drop(op.get_bind(), checkfirst=False)
