"""approval workflow engine

Revision ID: 5f5b845b6b6d
Revises: 95d3395aed77
Create Date: 2026-09-08 06:53:45.710494

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5f5b845b6b6d'
down_revision: Union[str, Sequence[str], None] = '95d3395aed77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # Create each new enum type exactly once up front, then reference it
    # with create_type=False on every column below — approval_request_type
    # is used by two different tables in this same migration, so letting
    # each op.create_table call implicitly CREATE TYPE would fail the
    # second time it's seen.
    approval_request_type = postgresql.ENUM(
        "leave_request", "expense", "bill", name="approval_request_type"
    )
    approval_step_eligibility_type = postgresql.ENUM(
        "role", "direct_manager", "department_head", "specific_person",
        name="approval_step_eligibility_type",
    )
    approval_instance_status = postgresql.ENUM(
        "pending", "approved", "rejected", name="approval_instance_status"
    )
    approval_decision_type = postgresql.ENUM("approve", "reject", name="approval_decision_type")
    for enum_type in (
        approval_request_type,
        approval_step_eligibility_type,
        approval_instance_status,
        approval_decision_type,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        'approval_workflow_steps',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column(
            'request_type',
            postgresql.ENUM(
                "leave_request", "expense", "bill",
                name="approval_request_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column(
            'eligibility_type',
            postgresql.ENUM(
                "role", "direct_manager", "department_head", "specific_person",
                name="approval_step_eligibility_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            'eligible_role',
            postgresql.ENUM(
                "admin", "payroll_manager", "manager", "employee",
                name="membership_role", create_type=False,
            ),
            nullable=True,
        ),
        sa.Column('eligible_account_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['eligible_account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'request_type', 'step_order', name='uq_approval_step_org_type_order'),
    )
    op.execute(
        "ALTER TABLE approval_workflow_steps ADD CONSTRAINT "
        "ck_approval_workflow_steps_eligibility_fields CHECK ("
        "(eligibility_type = 'role' AND eligible_role IS NOT NULL AND eligible_account_id IS NULL) "
        "OR (eligibility_type IN ('direct_manager', 'department_head') "
        "AND eligible_role IS NULL AND eligible_account_id IS NULL) "
        "OR (eligibility_type = 'specific_person' AND eligible_account_id IS NOT NULL "
        "AND eligible_role IS NULL)"
        ")"
    )

    op.create_table(
        'approval_instances',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column(
            'request_type',
            postgresql.ENUM(
                "leave_request", "expense", "bill",
                name="approval_request_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('request_id', sa.UUID(), nullable=False),
        sa.Column('requester_employee_id', sa.UUID(), nullable=True),
        sa.Column('current_step', sa.Integer(), nullable=False),
        sa.Column(
            'status',
            postgresql.ENUM(
                "pending", "approved", "rejected",
                name="approval_instance_status", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requester_employee_id'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('request_type', 'request_id', name='uq_approval_instance_request'),
    )
    op.create_index('ix_approval_instances_org_status', 'approval_instances', ['org_id', 'status'])

    op.create_table(
        'approval_instance_decisions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('approval_instance_id', sa.UUID(), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column(
            'decision',
            postgresql.ENUM(
                "approve", "reject", name="approval_decision_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('decided_by_account_id', sa.UUID(), nullable=True),
        sa.Column('decided_by_role', sa.String(length=32), nullable=True),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['approval_instance_id'], ['approval_instances.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by_account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_approval_instance_decisions_instance_created',
        'approval_instance_decisions',
        ['approval_instance_id', 'created_at'],
    )

    # Tenant isolation, same ENABLE + FORCE + policy pattern as every other
    # business table.
    for table in ("approval_workflow_steps", "approval_instances", "approval_instance_decisions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )

    # The decision trail is append-only, same trigger function
    # payslips/ledger_entries/audit_logs already use. approval_instances
    # itself stays mutable (current_step/status advance over its life), so
    # it deliberately gets RLS above but no such trigger.
    op.execute(
        "CREATE TRIGGER trg_approval_instance_decisions_append_only "
        "BEFORE UPDATE OR DELETE ON approval_instance_decisions "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_approval_instance_decisions_append_only "
        "ON approval_instance_decisions"
    )
    op.drop_index(
        'ix_approval_instance_decisions_instance_created', table_name='approval_instance_decisions'
    )
    op.drop_table('approval_instance_decisions')
    op.drop_index('ix_approval_instances_org_status', table_name='approval_instances')
    op.drop_table('approval_instances')
    op.execute(
        "ALTER TABLE approval_workflow_steps DROP CONSTRAINT "
        "ck_approval_workflow_steps_eligibility_fields"
    )
    op.drop_table('approval_workflow_steps')

    bind = op.get_bind()
    for name in (
        "approval_decision_type",
        "approval_instance_status",
        "approval_step_eligibility_type",
        "approval_request_type",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
