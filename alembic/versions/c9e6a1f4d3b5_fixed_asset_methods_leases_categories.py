"""fixed asset depreciation methods, leases and asset categories

Revision ID: c9e6a1f4d3b5
Revises: b8d5f0e3c2a4
Create Date: 2026-11-11 00:30:00.000000

Each fixed asset says how it's written down (straight line, reducing
balance or write off, with an optional yearly rate) and whether it's owned
or leased (a right-of-use asset over a lease term). Organisations define
their own asset categories with the depreciation each usually takes.
Existing assets carry on as owned, straight line over their useful life.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e6a1f4d3b5"
down_revision: Union[str, Sequence[str], None] = "b8d5f0e3c2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("depreciation_method", sa.String(length=24), nullable=False),
        sa.Column("depreciation_rate_ppm", sa.Integer(), nullable=True),
        sa.Column("useful_life_months", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "name", name="uq_asset_category_org_name"),
    )
    op.execute("ALTER TABLE asset_categories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE asset_categories FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY asset_categories_tenant_isolation ON asset_categories "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    op.add_column(
        "fixed_assets",
        sa.Column(
            "acquisition_type", sa.String(length=16), nullable=False, server_default="acquired"
        ),
    )
    op.add_column(
        "fixed_assets",
        sa.Column(
            "depreciation_method",
            sa.String(length=24),
            nullable=False,
            server_default="straight_line",
        ),
    )
    op.add_column("fixed_assets", sa.Column("depreciation_rate_ppm", sa.Integer(), nullable=True))
    op.add_column("fixed_assets", sa.Column("lease_term_months", sa.Integer(), nullable=True))
    op.add_column("fixed_assets", sa.Column("asset_category_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_fixed_assets_asset_category",
        "fixed_assets",
        "asset_categories",
        ["asset_category_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_fixed_assets_asset_category", "fixed_assets", type_="foreignkey")
    op.drop_column("fixed_assets", "asset_category_id")
    op.drop_column("fixed_assets", "lease_term_months")
    op.drop_column("fixed_assets", "depreciation_rate_ppm")
    op.drop_column("fixed_assets", "depreciation_method")
    op.drop_column("fixed_assets", "acquisition_type")
    op.drop_table("asset_categories")
