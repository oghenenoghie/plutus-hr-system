"""merge company assets into fixed assets

Revision ID: de798b342bdb
Revises: 00fdfba31859
Create Date: 2026-09-19 15:32:41.625460

HR's CompanyAsset (who has which laptop) and Accounting's FixedAsset
(cost/depreciation) were two separate, unlinked records for what could be
the same physical thing. This folds CompanyAsset's operational fields
(category, an employee assignment) onto FixedAsset, migrates every
existing company_assets/asset_assignments row across, then drops the old
tables — one record instead of two that could drift apart.

Migrated company assets get a placeholder financial profile
(cost_minor/useful_life_months) since CompanyAsset never collected those;
see the data migration below for the exact defaults. They should be
corrected to real figures once known — going forward, register_fixed_asset
requires real ones for every new asset.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de798b342bdb'
down_revision: Union[str, Sequence[str], None] = '00fdfba31859'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# CompanyAsset never collected these — a company asset migrated across
# gets this placeholder financial profile (3-year straight-line) rather
# than being dropped. cost_minor comes from purchase_value_minor when
# known, else this floor (register_fixed_asset requires cost_minor > 0).
_PLACEHOLDER_COST_MINOR = 100_00
_PLACEHOLDER_USEFUL_LIFE_MONTHS = 36


def upgrade() -> None:
    """Upgrade schema."""
    # op.add_column doesn't issue CREATE TYPE for an inline enum the way
    # op.create_table does, so the type has to exist before either column
    # referencing it is added; create_type=False below then stops each
    # Column from trying (and failing) to create it a second time.
    fixed_asset_category = sa.Enum(
        'laptop', 'phone', 'vehicle', 'furniture', 'other',
        name='fixed_asset_category',
    )
    asset_assignment_status = sa.Enum(
        'available', 'assigned', 'maintenance', name='asset_assignment_status'
    )
    fixed_asset_category.create(op.get_bind(), checkfirst=True)
    asset_assignment_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'fixed_assets',
        sa.Column(
            'category',
            sa.Enum(
                'laptop', 'phone', 'vehicle', 'furniture', 'other',
                name='fixed_asset_category',
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        'fixed_assets',
        sa.Column(
            'assignment_status',
            sa.Enum(
                'available', 'assigned', 'maintenance',
                name='asset_assignment_status',
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column('fixed_assets', sa.Column('assigned_employee_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_fixed_assets_assigned_employee_id',
        'fixed_assets',
        'employees',
        ['assigned_employee_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_table(
        'fixed_asset_assignments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('fixed_asset_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('assigned_date', sa.Date(), nullable=False),
        sa.Column('returned_date', sa.Date(), nullable=True),
        sa.Column('condition_notes', sa.String(length=500), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['fixed_asset_id'], ['fixed_assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_fixed_asset_assignments_fixed_asset_id', 'fixed_asset_assignments', ['fixed_asset_id']
    )
    op.execute("ALTER TABLE fixed_asset_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fixed_asset_assignments FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY fixed_asset_assignments_tenant_isolation ON fixed_asset_assignments "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    # --- Data migration: copy every company_assets/asset_assignments row
    # across before the old tables are dropped. ---
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO fixed_assets (
                id, org_id, name, asset_tag, acquisition_date, cost_minor,
                salvage_value_minor, useful_life_months, accumulated_depreciation_minor,
                status, category, assignment_status, assigned_employee_id, created_at
            )
            SELECT
                ca.id,
                ca.org_id,
                ca.name,
                ca.asset_tag,
                COALESCE(ca.purchase_date, ca.created_at::date),
                COALESCE(NULLIF(ca.purchase_value_minor, 0), :placeholder_cost),
                0,
                :placeholder_life,
                0,
                (CASE WHEN ca.status = 'retired' THEN 'disposed' ELSE 'active' END)::fixed_asset_status,
                ca.category::text::fixed_asset_category,
                CASE WHEN ca.status = 'retired' THEN NULL ELSE ca.status::text::asset_assignment_status END,
                (
                    SELECT aa.employee_id FROM asset_assignments aa
                    WHERE aa.asset_id = ca.id AND aa.returned_date IS NULL
                    LIMIT 1
                ),
                ca.created_at
            FROM company_assets ca
            """
        ),
        {
            "placeholder_cost": _PLACEHOLDER_COST_MINOR,
            "placeholder_life": _PLACEHOLDER_USEFUL_LIFE_MONTHS,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO fixed_asset_assignments (
                id, org_id, fixed_asset_id, employee_id, assigned_date,
                returned_date, condition_notes, created_at
            )
            SELECT id, org_id, asset_id, employee_id, assigned_date,
                   returned_date, condition_notes, created_at
            FROM asset_assignments
            """
        )
    )
    connection.execute(sa.text("UPDATE fixed_assets SET disposed_at = created_at WHERE status = 'disposed'"))

    op.drop_table('asset_assignments')
    op.drop_table('company_assets')
    sa.Enum(name='company_asset_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='company_asset_category').drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'company_assets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('asset_tag', sa.String(length=64), nullable=False),
        sa.Column(
            'category',
            sa.Enum(
                'laptop', 'phone', 'vehicle', 'furniture', 'other', name='company_asset_category'
            ),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.Enum(
                'available', 'assigned', 'maintenance', 'retired', name='company_asset_status'
            ),
            nullable=False,
        ),
        sa.Column('purchase_date', sa.Date(), nullable=True),
        sa.Column('purchase_value_minor', sa.BigInteger(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'asset_tag', name='uq_company_asset_org_tag'),
    )
    op.create_table(
        'asset_assignments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('asset_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('assigned_date', sa.Date(), nullable=False),
        sa.Column('returned_date', sa.Date(), nullable=True),
        sa.Column('condition_notes', sa.String(length=500), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['asset_id'], ['company_assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("ALTER TABLE company_assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_assets FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY company_assets_tenant_isolation ON company_assets "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )
    op.execute("ALTER TABLE asset_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE asset_assignments FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY asset_assignments_tenant_isolation ON asset_assignments "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    # Best-effort: only fixed_assets rows that carry a category came from
    # (or look like) a company asset; cost/depreciation figures added
    # after the merge have no home to go back to and are dropped here.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO company_assets (
                id, org_id, name, asset_tag, category, status, purchase_date,
                purchase_value_minor, created_at
            )
            SELECT
                id, org_id, name, asset_tag, category::text::company_asset_category,
                (CASE
                    WHEN status = 'disposed' THEN 'retired'
                    ELSE COALESCE(assignment_status::text, 'available')
                END)::company_asset_status,
                acquisition_date, cost_minor, created_at
            FROM fixed_assets
            WHERE category IS NOT NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO asset_assignments (
                id, org_id, asset_id, employee_id, assigned_date,
                returned_date, condition_notes, created_at
            )
            SELECT faa.id, faa.org_id, faa.fixed_asset_id, faa.employee_id, faa.assigned_date,
                   faa.returned_date, faa.condition_notes, faa.created_at
            FROM fixed_asset_assignments faa
            JOIN fixed_assets fa ON fa.id = faa.fixed_asset_id
            WHERE fa.category IS NOT NULL
            """
        )
    )
    # Rows just copied back to company_assets/asset_assignments would
    # otherwise also linger in fixed_assets, duplicated across both tables.
    connection.execute(sa.text("DELETE FROM fixed_assets WHERE category IS NOT NULL"))

    op.drop_index('ix_fixed_asset_assignments_fixed_asset_id', table_name='fixed_asset_assignments')
    op.drop_table('fixed_asset_assignments')
    op.drop_constraint('fk_fixed_assets_assigned_employee_id', 'fixed_assets', type_='foreignkey')
    op.drop_column('fixed_assets', 'assigned_employee_id')
    op.drop_column('fixed_assets', 'assignment_status')
    op.drop_column('fixed_assets', 'category')
    sa.Enum(name='asset_assignment_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='fixed_asset_category').drop(op.get_bind(), checkfirst=False)
