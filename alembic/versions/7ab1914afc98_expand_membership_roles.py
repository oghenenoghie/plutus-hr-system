"""expand membership roles (accountant, hr_manager, department_manager, auditor)

Revision ID: 7ab1914afc98
Revises: b6ea32f8e106
Create Date: 2026-09-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7ab1914afc98'
down_revision: Union[str, Sequence[str], None] = 'b6ea32f8e106'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # New values for the existing membership_role enum. Postgres has no
    # transactional ADD VALUE ... IF NOT EXISTS-free downgrade path for a
    # single value, so this is forward-only, same as every other enum
    # addition in this codebase's history (see 802c9a295881).
    for value in ("accountant", "hr_manager", "department_manager", "auditor"):
        op.execute(f"ALTER TYPE membership_role ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Downgrade schema."""
    # The values added above are not removed here — Postgres has no DROP
    # VALUE for enums short of recreating the type, and membership_role is
    # in active use by memberships.
    pass
