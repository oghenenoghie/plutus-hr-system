"""organisation country

Revision ID: c4e8b2d6f913
Revises: a3c9e1f7b254
Create Date: 2026-10-25 12:00:00.000000

Each organisation carries the country whose statutory rules it runs on
(docs/architecture/multicountry-tax.md, Part 1). Every existing organisation
is NG: until now payroll, bills and contractors resolved only Nigerian rules.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4e8b2d6f913'
down_revision: Union[str, Sequence[str], None] = 'a3c9e1f7b254'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organisations',
        sa.Column('country_code', sa.String(length=2), nullable=False, server_default='NG'),
    )
    op.create_check_constraint(
        'ck_organisations_country_code_iso', 'organisations', "country_code ~ '^[A-Z]{2}$'"
    )


def downgrade() -> None:
    op.drop_constraint('ck_organisations_country_code_iso', 'organisations', type_='check')
    op.drop_column('organisations', 'country_code')
