"""employee pension rates

Revision ID: f1a2b3c4d5e6
Revises: e3f9a1c7b5d2
Create Date: 2026-11-10 22:00:00.000000

Per-employee pension rates (parts per million) for an employer whose scheme
contributes more than the statutory minimum. Null means the rule set's
rate; the API and the payroll engine refuse a rate below it.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e3f9a1c7b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("pension_employee_rate_ppm", sa.Integer(), nullable=True))
    op.add_column("employees", sa.Column("pension_employer_rate_ppm", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "pension_employer_rate_ppm")
    op.drop_column("employees", "pension_employee_rate_ppm")
