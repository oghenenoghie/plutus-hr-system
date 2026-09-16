"""organisation onboarding defaults

Revision ID: 2ed05b300119
Revises: c90fedb782d8
Create Date: 2026-09-15 11:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2ed05b300119"
down_revision: Union[str, Sequence[str], None] = "c90fedb782d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    organisation_default_pay_frequency = postgresql.ENUM(
        "monthly", "weekly", "biweekly", name="organisation_default_pay_frequency"
    )
    organisation_default_pay_frequency.create(op.get_bind())
    op.add_column(
        "organisations",
        sa.Column(
            "default_pay_frequency",
            organisation_default_pay_frequency,
            nullable=False,
            server_default="monthly",
        ),
    )
    op.add_column("organisations", sa.Column("default_pfa", sa.String(length=255), nullable=True))
    op.add_column(
        "organisations",
        sa.Column(
            "states_of_operation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("organisations", "states_of_operation")
    op.drop_column("organisations", "default_pfa")
    op.drop_column("organisations", "default_pay_frequency")
    postgresql.ENUM(name="organisation_default_pay_frequency").drop(op.get_bind())
