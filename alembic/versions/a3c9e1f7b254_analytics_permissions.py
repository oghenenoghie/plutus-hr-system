"""analytics permissions

Revision ID: a3c9e1f7b254
Revises: 7f6106c58e40
Create Date: 2026-10-24 12:00:00.000000

Analytics & Insights (docs/analytics-architecture.md, decision A3). Adds
the ten analytics.* permissions to the permission-override enum, so an
organisation can grant or revoke them per membership like any other
permission. Analytics itself reads existing tables only: no table, column
or data change.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3c9e1f7b254'
down_revision: Union[str, Sequence[str], None] = '7f6106c58e40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_PERMISSIONS = (
    'analytics.view',
    'analytics.workforce.view',
    'analytics.payroll.view',
    'analytics.attendance.view',
    'analytics.leave.view',
    'analytics.recruitment.view',
    'analytics.performance.view',
    'analytics.compliance.view',
    'analytics.financial.view',
    'analytics.reports.export',
)


def upgrade() -> None:
    """Upgrade schema."""
    for value in _NEW_PERMISSIONS:
        op.execute(
            f"ALTER TYPE membership_permission_override_permission ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    """Downgrade schema.

    PostgreSQL cannot drop a value from an enum type, so the values stay;
    removing every override that uses one returns the database to its
    earlier behaviour.
    """
    values = ", ".join(f"'{value}'" for value in _NEW_PERMISSIONS)
    op.execute(
        "DELETE FROM membership_permission_overrides "
        f"WHERE permission::text IN ({values})"
    )
