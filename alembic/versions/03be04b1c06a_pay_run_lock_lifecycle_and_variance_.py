"""pay run lock lifecycle and variance flags

Revision ID: 03be04b1c06a
Revises: 735962b7c278
Create Date: 2026-09-12 23:23:18.516195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '03be04b1c06a'
down_revision: Union[str, Sequence[str], None] = '735962b7c278'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # pay_run_status: draft/processing/completed/failed -> draft/validated/
    # locked/reversed. 'processing' never appears in committed data (it was
    # only ever set transiently, overwritten before the same transaction
    # committed), but the mapping is defensive rather than assumed.
    op.execute("ALTER TYPE pay_run_status RENAME TO pay_run_status_old")
    op.execute("CREATE TYPE pay_run_status AS ENUM ('draft', 'validated', 'locked', 'reversed')")
    op.execute("ALTER TABLE pay_runs ALTER COLUMN status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE pay_runs ALTER COLUMN status TYPE pay_run_status USING (
            CASE status::text
                WHEN 'completed' THEN 'locked'
                ELSE 'draft'
            END
        )::pay_run_status
        """
    )
    op.execute("ALTER TABLE pay_runs ALTER COLUMN status SET DEFAULT 'draft'")
    op.execute("DROP TYPE pay_run_status_old")

    op.add_column(
        "pay_runs",
        sa.Column(
            "employee_ids",
            postgresql.ARRAY(sa.UUID()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.alter_column("pay_runs", "employee_ids", server_default=None)
    op.add_column("pay_runs", sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pay_runs", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pay_runs", sa.Column("locked_by", sa.UUID(), nullable=True))
    op.add_column("pay_runs", sa.Column("disbursed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pay_runs", sa.Column("disbursed_by", sa.UUID(), nullable=True))
    op.add_column("pay_runs", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_pay_runs_locked_by_accounts", "pay_runs", "accounts", ["locked_by"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pay_runs_disbursed_by_accounts", "pay_runs", "accounts", ["disbursed_by"], ["id"],
        ondelete="SET NULL",
    )
    # completed_at is superseded by locked_at above — carrying it forward
    # would just be a second column meaning the same thing for every future
    # run, and no downstream code reads it.
    op.drop_column("pay_runs", "completed_at")

    op.create_table(
        "pay_run_variance_flags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("pay_run_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column(
            "flag_type",
            sa.Enum("gross_swing", "employee_missing", name="pay_run_variance_flag_type"),
            nullable=False,
        ),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pay_run_id"], ["pay_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pay_run_variance_flags_pay_run_id", "pay_run_variance_flags", ["pay_run_id"]
    )

    op.execute("ALTER TABLE pay_run_variance_flags ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pay_run_variance_flags FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY pay_run_variance_flags_tenant_isolation ON pay_run_variance_flags "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("pay_run_variance_flags")
    sa.Enum(name="pay_run_variance_flag_type").drop(op.get_bind(), checkfirst=False)

    op.add_column("pay_runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("fk_pay_runs_disbursed_by_accounts", "pay_runs", type_="foreignkey")
    op.drop_constraint("fk_pay_runs_locked_by_accounts", "pay_runs", type_="foreignkey")
    op.drop_column("pay_runs", "reversed_at")
    op.drop_column("pay_runs", "disbursed_by")
    op.drop_column("pay_runs", "disbursed_at")
    op.drop_column("pay_runs", "locked_by")
    op.drop_column("pay_runs", "locked_at")
    op.drop_column("pay_runs", "validated_at")
    op.drop_column("pay_runs", "employee_ids")

    op.execute("ALTER TYPE pay_run_status RENAME TO pay_run_status_old")
    op.execute("CREATE TYPE pay_run_status AS ENUM ('draft', 'processing', 'completed', 'failed')")
    op.execute("ALTER TABLE pay_runs ALTER COLUMN status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE pay_runs ALTER COLUMN status TYPE pay_run_status USING (
            CASE status::text
                WHEN 'locked' THEN 'completed'
                WHEN 'reversed' THEN 'completed'
                ELSE 'draft'
            END
        )::pay_run_status
        """
    )
    op.execute("ALTER TABLE pay_runs ALTER COLUMN status SET DEFAULT 'draft'")
    op.execute("DROP TYPE pay_run_status_old")
