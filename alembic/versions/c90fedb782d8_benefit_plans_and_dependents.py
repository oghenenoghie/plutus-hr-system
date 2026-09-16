"""benefit plan catalogue and dependents

Revision ID: c90fedb782d8
Revises: 118771c6e909
Create Date: 2026-09-15 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c90fedb782d8'
down_revision: Union[str, Sequence[str], None] = '118771c6e909'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # benefit_frequency already exists (created for benefits.frequency) —
    # postgresql.ENUM with create_type=False reuses it without re-issuing
    # CREATE TYPE, unlike a plain sa.Enum(...) here.
    benefit_frequency = postgresql.ENUM(
        'one_time', 'monthly', 'annual', name='benefit_frequency', create_type=False
    )
    op.create_table(
        'benefit_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('frequency', benefit_frequency, nullable=False),
        sa.Column('default_employee_cost_minor', sa.BigInteger(), nullable=True),
        sa.Column('employer_cost_minor', sa.BigInteger(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_benefit_plan_org_name'),
    )
    op.execute("ALTER TABLE benefit_plans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE benefit_plans FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY benefit_plans_tenant_isolation ON benefit_plans "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    op.add_column('benefits', sa.Column('plan_id', sa.UUID(), nullable=True))
    op.add_column('benefits', sa.Column('employer_cost_minor', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'benefits_plan_id_fkey', 'benefits', 'benefit_plans', ['plan_id'], ['id'], ondelete='SET NULL'
    )

    op.create_table(
        'benefit_dependents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('relationship', sa.String(length=64), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("ALTER TABLE benefit_dependents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE benefit_dependents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY benefit_dependents_tenant_isolation ON benefit_dependents "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('benefit_dependents')
    op.drop_constraint('benefits_plan_id_fkey', 'benefits', type_='foreignkey')
    op.drop_column('benefits', 'employer_cost_minor')
    op.drop_column('benefits', 'plan_id')
    op.drop_table('benefit_plans')
