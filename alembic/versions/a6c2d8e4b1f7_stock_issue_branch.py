"""Stock issues to a branch

Revision ID: a6c2d8e4b1f7
Revises: e5b9c3f7a2d1
Create Date: 2026-11-17 09:00:00.000000

A stock issue can name the branch the stock goes to, beside or instead of a
department. Existing issues name none.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c2d8e4b1f7"
down_revision: Union[str, Sequence[str], None] = "e5b9c3f7a2d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory_stock_issues", sa.Column("branch_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "inventory_stock_issues_branch_id_fkey",
        "inventory_stock_issues",
        "branches",
        ["branch_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "inventory_stock_issues_branch_id_fkey", "inventory_stock_issues", type_="foreignkey"
    )
    op.drop_column("inventory_stock_issues", "branch_id")
