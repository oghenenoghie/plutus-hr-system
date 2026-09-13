"""approval workflow engine

Revision ID: 899b1d0ab7f7
Revises: a6ce2b4a560d
Create Date: 2026-09-13 00:53:35.380386

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '899b1d0ab7f7'
down_revision: Union[str, Sequence[str], None] = 'a6ce2b4a560d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'approval_workflow_templates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_approval_workflow_templates_org_entity',
        'approval_workflow_templates',
        ['org_id', 'entity_type'],
    )

    op.create_table(
        'approval_workflow_steps',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('template_id', sa.UUID(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column(
            'approver_role',
            sa.Enum('admin', 'payroll_manager', 'manager', 'employee', name='approval_step_approver_role'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['template_id'], ['approval_workflow_templates.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('template_id', 'sequence', name='uq_workflow_step_sequence'),
    )

    op.create_table(
        'approval_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('template_id', sa.UUID(), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('current_step', sa.Integer(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'approved', 'rejected', name='approval_request_status'),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['template_id'], ['approval_workflow_templates.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'entity_id', name='uq_approval_request_entity'),
    )

    op.create_table(
        'approval_step_decisions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('approval_request_id', sa.UUID(), nullable=False),
        sa.Column('step_sequence', sa.Integer(), nullable=False),
        sa.Column(
            'decision',
            sa.Enum('approved', 'rejected', name='approval_step_decision'),
            nullable=False,
        ),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('comments', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approval_request_id'], ['approval_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_approval_step_decisions_request_id',
        'approval_step_decisions',
        ['approval_request_id'],
    )

    for table in (
        'approval_workflow_templates',
        'approval_workflow_steps',
        'approval_requests',
        'approval_step_decisions',
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )

    # Append-only: the permanent record of who decided what and when.
    op.execute(
        "CREATE TRIGGER trg_approval_step_decisions_append_only "
        "BEFORE UPDATE OR DELETE ON approval_step_decisions "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_approval_step_decisions_request_id', table_name='approval_step_decisions')
    op.drop_table('approval_step_decisions')
    op.drop_table('approval_requests')
    op.drop_table('approval_workflow_steps')
    op.drop_index(
        'ix_approval_workflow_templates_org_entity', table_name='approval_workflow_templates'
    )
    op.drop_table('approval_workflow_templates')
    sa.Enum(name='approval_step_decision').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='approval_request_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='approval_step_approver_role').drop(op.get_bind(), checkfirst=False)
