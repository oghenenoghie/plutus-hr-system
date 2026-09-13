"""probation periods

Revision ID: 0414eddb3643
Revises: c7b433c8f9bc
Create Date: 2026-09-13 00:32:41.054146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0414eddb3643'
down_revision: Union[str, Sequence[str], None] = 'c7b433c8f9bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'probation_periods',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('in_progress', 'confirmed', 'failed', name='probation_status'),
            nullable=False,
        ),
        sa.Column('decided_date', sa.Date(), nullable=True),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_probation_periods_employee_id', 'probation_periods', ['employee_id'])

    op.execute("ALTER TABLE probation_periods ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE probation_periods FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY probation_periods_tenant_isolation ON probation_periods "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_probation_periods_employee_id', table_name='probation_periods')
    op.drop_table('probation_periods')
    sa.Enum(name='probation_status').drop(op.get_bind(), checkfirst=False)
