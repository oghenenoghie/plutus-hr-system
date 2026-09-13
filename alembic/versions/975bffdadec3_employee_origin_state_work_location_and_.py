"""employee origin state, work location and photo

Revision ID: 975bffdadec3
Revises: 3203eefbd3d2
Create Date: 2026-09-13 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '975bffdadec3'
down_revision: Union[str, Sequence[str], None] = '3203eefbd3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('employees', sa.Column('state_of_origin', sa.String(length=64), nullable=True))
    op.add_column('employees', sa.Column('photo_url', sa.String(length=1000), nullable=True))
    op.add_column('employees', sa.Column('branch_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_employees_branch_id', 'employees', 'branches', ['branch_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_employees_branch_id', 'employees', type_='foreignkey')
    op.drop_column('employees', 'branch_id')
    op.drop_column('employees', 'photo_url')
    op.drop_column('employees', 'state_of_origin')
