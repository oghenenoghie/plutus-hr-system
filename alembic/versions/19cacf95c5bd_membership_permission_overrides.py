"""membership permission overrides

Revision ID: 19cacf95c5bd
Revises: e892ece863b5
Create Date: 2026-09-13 01:52:58.599384

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19cacf95c5bd'
down_revision: Union[str, Sequence[str], None] = 'e892ece863b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PERMISSIONS = (
    'employees.view', 'employees.manage', 'payroll.run', 'payroll.approve',
    'accounting.manage', 'recruitment.manage', 'performance.manage', 'reports.view',
    'settings.manage',
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'membership_permission_overrides',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('membership_id', sa.UUID(), nullable=False),
        sa.Column(
            'permission',
            sa.Enum(*_PERMISSIONS, name='membership_permission_override_permission'),
            nullable=False,
        ),
        sa.Column('granted', sa.Boolean(), nullable=False),
        sa.Column('granted_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['membership_id'], ['memberships.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('membership_id', 'permission', name='uq_membership_permission'),
    )

    op.execute("ALTER TABLE membership_permission_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE membership_permission_overrides FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY membership_permission_overrides_tenant_isolation "
        "ON membership_permission_overrides "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('membership_permission_overrides')
    sa.Enum(name='membership_permission_override_permission').drop(op.get_bind(), checkfirst=False)
