"""shift roster entries

Revision ID: c96b68f63e64
Revises: 3c5a87d64254
Create Date: 2026-09-13 00:44:47.592446

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c96b68f63e64'
down_revision: Union[str, Sequence[str], None] = '3c5a87d64254'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'shift_roster_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('shift_id', sa.UUID(), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'work_date', name='uq_roster_employee_date'),
    )
    op.create_index('ix_shift_roster_entries_employee_id', 'shift_roster_entries', ['employee_id'])

    op.execute("ALTER TABLE shift_roster_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE shift_roster_entries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY shift_roster_entries_tenant_isolation ON shift_roster_entries "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_shift_roster_entries_employee_id', table_name='shift_roster_entries')
    op.drop_table('shift_roster_entries')
