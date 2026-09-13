"""employee checklist items

Revision ID: c7b433c8f9bc
Revises: 958e453258de
Create Date: 2026-09-13 00:29:27.031122

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7b433c8f9bc'
down_revision: Union[str, Sequence[str], None] = '958e453258de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'employee_checklist_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column(
            'checklist_type',
            sa.Enum('onboarding', 'offboarding', name='checklist_type'),
            nullable=False,
        ),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'done', name='checklist_item_status'),
            nullable=False,
        ),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['completed_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_employee_checklist_items_employee_id', 'employee_checklist_items', ['employee_id']
    )

    op.execute("ALTER TABLE employee_checklist_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_checklist_items FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY employee_checklist_items_tenant_isolation ON employee_checklist_items "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_employee_checklist_items_employee_id', table_name='employee_checklist_items'
    )
    op.drop_table('employee_checklist_items')
    sa.Enum(name='checklist_item_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='checklist_type').drop(op.get_bind(), checkfirst=False)
