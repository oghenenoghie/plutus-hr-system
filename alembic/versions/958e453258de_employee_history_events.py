"""employee history events

Revision ID: 958e453258de
Revises: e5ff44a6862d
Create Date: 2026-09-13 00:22:43.715497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '958e453258de'
down_revision: Union[str, Sequence[str], None] = 'e5ff44a6862d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'employee_history_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column(
            'event_type',
            sa.Enum('status_change', 'compensation_change', name='employee_history_event_type'),
            nullable=False,
        ),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('recorded_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recorded_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_employee_history_events_employee_id', 'employee_history_events', ['employee_id']
    )

    op.execute("ALTER TABLE employee_history_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_history_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY employee_history_events_tenant_isolation ON employee_history_events "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    # Append-only: a correction is a new event, never an edit to a prior one.
    op.execute(
        "CREATE TRIGGER trg_employee_history_events_append_only "
        "BEFORE UPDATE OR DELETE ON employee_history_events "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_employee_history_events_employee_id', table_name='employee_history_events')
    op.drop_table('employee_history_events')
    sa.Enum(name='employee_history_event_type').drop(op.get_bind(), checkfirst=False)
