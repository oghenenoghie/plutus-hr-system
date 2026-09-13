"""attendance records

Revision ID: a6ce2b4a560d
Revises: c96b68f63e64
Create Date: 2026-09-13 00:48:50.787344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6ce2b4a560d'
down_revision: Union[str, Sequence[str], None] = 'c96b68f63e64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'attendance_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('clock_in_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('clock_out_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'work_date', name='uq_attendance_employee_date'),
    )
    op.create_index('ix_attendance_records_employee_id', 'attendance_records', ['employee_id'])

    op.execute("ALTER TABLE attendance_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE attendance_records FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY attendance_records_tenant_isolation ON attendance_records "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_attendance_records_employee_id', table_name='attendance_records')
    op.drop_table('attendance_records')
