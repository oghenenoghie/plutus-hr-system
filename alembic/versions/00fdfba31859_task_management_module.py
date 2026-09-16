"""task management module

Revision ID: 00fdfba31859
Revises: 9c6db0cbfa01
Create Date: 2026-09-16 04:05:12.482693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00fdfba31859'
down_revision: Union[str, Sequence[str], None] = '9c6db0cbfa01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('tasks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.String(length=2000), nullable=True),
    sa.Column('assigned_to_account_id', sa.UUID(), nullable=False),
    sa.Column('created_by_account_id', sa.UUID(), nullable=False),
    sa.Column('related_employee_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Enum('todo', 'in_progress', 'done', 'cancelled', name='task_status'), nullable=False),
    sa.Column('priority', sa.Enum('low', 'medium', 'high', name='task_priority'), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assigned_to_account_id'], ['accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_account_id'], ['accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['related_employee_id'], ['employees.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_assigned_to_account_id'), 'tasks', ['assigned_to_account_id'], unique=False)
    op.create_index(op.f('ix_tasks_org_id'), 'tasks', ['org_id'], unique=False)

    # Tenant isolation, same ENABLE + FORCE + policy pattern as every other
    # business table.
    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tasks_tenant_isolation ON tasks "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_tasks_org_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_assigned_to_account_id'), table_name='tasks')
    op.drop_table('tasks')
