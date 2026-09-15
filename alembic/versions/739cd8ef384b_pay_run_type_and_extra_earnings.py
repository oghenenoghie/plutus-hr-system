"""pay run type and per-employee extra earnings

Revision ID: 739cd8ef384b
Revises: 7ab1914afc98
Create Date: 2026-09-15 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "739cd8ef384b"
down_revision: Union[str, Sequence[str], None] = "7ab1914afc98"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pay_run_type = postgresql.ENUM(
        "regular", "bonus", "thirteenth_month", "arrears", "off_cycle", name="pay_run_type"
    )
    pay_run_type.create(op.get_bind())
    op.add_column(
        "pay_runs",
        sa.Column(
            "run_type",
            pay_run_type,
            nullable=False,
            server_default="regular",
        ),
    )
    op.add_column(
        "pay_runs",
        sa.Column(
            "extra_earnings_minor",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pay_runs", "extra_earnings_minor")
    op.drop_column("pay_runs", "run_type")
    postgresql.ENUM(name="pay_run_type").drop(op.get_bind())
