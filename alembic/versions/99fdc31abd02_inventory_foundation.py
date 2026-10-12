"""inventory foundation: master data, adjustments, stock ledger

Revision ID: 99fdc31abd02
Revises: 4f1c9a7e2b30
Create Date: 2026-10-12 10:00:00.000000

Phase 1 of docs/architecture/inventory-integration.md. Pure DDL, additive
only: new tables and enum values, no change to any existing row and no
backfill (so no dependency on the migration role bypassing RLS, audit P24).

Every table gets the standard tenant-isolation policy with FORCE ROW LEVEL
SECURITY. inventory_stock_movements is the stock ledger and is append-only
via the existing forbid_update_delete() trigger.

The four new permission values are added to the
membership_permission_override_permission enum. ALTER TYPE ... ADD VALUE
works inside a transaction on PostgreSQL 12+ as long as the new value is
not used in that same transaction, which this migration does not do.
Downgrade leaves those enum values in place: PostgreSQL cannot drop an enum
value, and an unused value is harmless.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99fdc31abd02'
down_revision: Union[str, Sequence[str], None] = '4f1c9a7e2b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ITEM_TYPES = ('stock', 'consumable', 'non_stock', 'service')
_MOVEMENT_TYPES = (
    'opening_balance',
    'adjustment_gain',
    'adjustment_loss',
    'reversal',
    'receipt',
    'issue',
    'transfer_out',
    'transfer_in',
)
_SOURCE_TYPES = (
    'inventory_adjustment',
    'goods_receipt',
    'stock_issue',
    'stock_transfer',
    'stocktake',
)
_ADJUSTMENT_REASONS = (
    'opening_balance',
    'found',
    'damage',
    'expiry',
    'loss',
    'write_off',
    'correction',
)
_ADJUSTMENT_STATUSES = ('draft', 'posted', 'reversed')
_NEW_PERMISSIONS = (
    'inventory.view',
    'inventory.manage',
    'inventory.adjust',
    'inventory.valuation',
)

# Creation order; dropped in reverse.
_TABLES = (
    'inventory_settings',
    'inventory_categories',
    'inventory_units',
    'inventory_items',
    'inventory_item_units',
    'inventory_warehouses',
    'inventory_adjustments',
    'inventory_adjustment_lines',
    'inventory_stock_movements',
    'inventory_stock_balances',
    'inventory_item_costs',
)

_QTY = sa.Numeric(18, 4)


def _uuid_pk() -> sa.Column:
    return sa.Column('id', sa.UUID(), nullable=False)


def _org_fk(ondelete: str = 'CASCADE') -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete=ondelete)


def _created_at() -> sa.Column:
    return sa.Column(
        'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
    )


def upgrade() -> None:
    """Upgrade schema."""
    for value in _NEW_PERMISSIONS:
        op.execute(
            f"ALTER TYPE membership_permission_override_permission ADD VALUE IF NOT EXISTS '{value}'"
        )

    op.create_table(
        'inventory_settings',
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'costing_method',
            sa.String(length=32),
            nullable=False,
            server_default='weighted_average',
        ),
        sa.Column('next_adjustment_number', sa.Integer(), nullable=False, server_default='1'),
        _updated_at(),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "costing_method = 'weighted_average'", name='ck_inventory_costing_method'
        ),
        sa.CheckConstraint(
            'next_adjustment_number > 0', name='ck_inventory_next_adjustment_number'
        ),
        _org_fk(),
        sa.PrimaryKeyConstraint('org_id'),
    )

    op.create_table(
        'inventory_categories',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('parent_id', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        _created_at(),
        sa.CheckConstraint(
            'parent_id IS NULL OR parent_id <> id', name='ck_inventory_category_parent'
        ),
        _org_fk(),
        sa.ForeignKeyConstraint(['parent_id'], ['inventory_categories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_inventory_category_org_name'),
    )

    op.create_table(
        'inventory_units',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('allows_fraction', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        _created_at(),
        _org_fk(),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'code', name='uq_inventory_unit_org_code'),
    )

    op.create_table(
        'inventory_items',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('sku', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('item_type', sa.Enum(*_ITEM_TYPES, name='inventory_item_type'), nullable=False),
        sa.Column('category_id', sa.UUID(), nullable=True),
        sa.Column('base_unit_id', sa.UUID(), nullable=False),
        sa.Column('reorder_level', _QTY, nullable=True),
        sa.Column('max_level', _QTY, nullable=True),
        sa.Column('default_cost_minor', sa.BigInteger(), nullable=True),
        sa.Column('preferred_vendor_id', sa.UUID(), nullable=True),
        sa.Column('barcode', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            'reorder_level IS NULL OR reorder_level >= 0', name='ck_inventory_item_reorder'
        ),
        sa.CheckConstraint(
            'max_level IS NULL OR (max_level > 0 AND '
            '(reorder_level IS NULL OR max_level >= reorder_level))',
            name='ck_inventory_item_max_level',
        ),
        sa.CheckConstraint(
            'default_cost_minor IS NULL OR default_cost_minor >= 0',
            name='ck_inventory_item_default_cost',
        ),
        _org_fk(),
        sa.ForeignKeyConstraint(['category_id'], ['inventory_categories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['base_unit_id'], ['inventory_units.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['preferred_vendor_id'], ['vendors.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'sku', name='uq_inventory_item_org_sku'),
    )

    op.create_table(
        'inventory_item_units',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('unit_id', sa.UUID(), nullable=False),
        sa.Column('factor_to_base', sa.Numeric(18, 6), nullable=False),
        _created_at(),
        sa.CheckConstraint('factor_to_base > 0', name='ck_inventory_item_unit_factor'),
        _org_fk(),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['unit_id'], ['inventory_units.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', 'unit_id', name='uq_inventory_item_unit'),
    )

    op.create_table(
        'inventory_warehouses',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('branch_id', sa.UUID(), nullable=True),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        _created_at(),
        _org_fk(),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'code', name='uq_inventory_warehouse_org_code'),
    )

    op.create_table(
        'inventory_adjustments',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('adjustment_number', sa.String(length=32), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column(
            'reason',
            sa.Enum(*_ADJUSTMENT_REASONS, name='inventory_adjustment_reason'),
            nullable=False,
        ),
        sa.Column('adjustment_date', sa.Date(), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column(
            'status',
            sa.Enum(*_ADJUSTMENT_STATUSES, name='inventory_adjustment_status'),
            nullable=False,
            server_default='draft',
        ),
        sa.Column('created_by', sa.UUID(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posted_by', sa.UUID(), nullable=True),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reversed_by', sa.UUID(), nullable=True),
        sa.Column('reversal_reason', sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status <> 'reversed' OR reversal_reason IS NOT NULL",
            name='ck_inventory_adjustment_reversal_reason',
        ),
        _org_fk(),
        sa.ForeignKeyConstraint(
            ['warehouse_id'], ['inventory_warehouses.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'adjustment_number', name='uq_inventory_adjustment_number'),
    )

    op.create_table(
        'inventory_adjustment_lines',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('adjustment_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('unit_id', sa.UUID(), nullable=False),
        sa.Column('quantity', _QTY, nullable=False),
        sa.Column('unit_cost_minor', sa.BigInteger(), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.CheckConstraint('quantity <> 0', name='ck_inventory_adjustment_line_quantity'),
        sa.CheckConstraint(
            '(quantity > 0 AND unit_cost_minor IS NOT NULL AND unit_cost_minor >= 0) '
            'OR (quantity < 0 AND unit_cost_minor IS NULL)',
            name='ck_inventory_adjustment_line_cost',
        ),
        _org_fk(),
        sa.ForeignKeyConstraint(
            ['adjustment_id'], ['inventory_adjustments.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['unit_id'], ['inventory_units.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('adjustment_id', 'line_no', name='uq_inventory_adjustment_line_no'),
    )

    op.create_table(
        'inventory_stock_movements',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column(
            'movement_type',
            sa.Enum(*_MOVEMENT_TYPES, name='inventory_movement_type'),
            nullable=False,
        ),
        sa.Column('quantity_base', _QTY, nullable=False),
        sa.Column('value_minor', sa.BigInteger(), nullable=False),
        sa.Column('unit_cost_minor', sa.BigInteger(), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column(
            'source_type', sa.Enum(*_SOURCE_TYPES, name='inventory_source_type'), nullable=False
        ),
        sa.Column('source_id', sa.UUID(), nullable=False),
        sa.Column('source_line_id', sa.UUID(), nullable=False),
        sa.Column('reversal_of_id', sa.UUID(), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('posted_by', sa.UUID(), nullable=True),
        _created_at(),
        sa.CheckConstraint('quantity_base <> 0', name='ck_inventory_movement_quantity'),
        sa.CheckConstraint(
            '(quantity_base > 0 AND value_minor >= 0) OR (quantity_base < 0 AND value_minor <= 0)',
            name='ck_inventory_movement_value_sign',
        ),
        sa.CheckConstraint(
            "(movement_type = 'reversal') = (reversal_of_id IS NOT NULL)",
            name='ck_inventory_movement_reversal',
        ),
        _org_fk('RESTRICT'),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['warehouse_id'], ['inventory_warehouses.id'], ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['reversal_of_id'], ['inventory_stock_movements.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'org_id',
            'source_type',
            'source_line_id',
            'movement_type',
            name='uq_inventory_movement_source_line',
        ),
    )
    op.create_index(
        'uq_inventory_movement_reversal_of',
        'inventory_stock_movements',
        ['reversal_of_id'],
        unique=True,
    )
    op.create_index(
        'ix_inventory_movements_item_wh_date',
        'inventory_stock_movements',
        ['org_id', 'item_id', 'warehouse_id', 'entry_date'],
    )
    op.create_index(
        'ix_inventory_movements_source',
        'inventory_stock_movements',
        ['org_id', 'source_type', 'source_id'],
    )

    op.create_table(
        'inventory_stock_balances',
        _uuid_pk(),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column('quantity_base', _QTY, nullable=False, server_default='0'),
        _updated_at(),
        sa.CheckConstraint('quantity_base >= 0', name='ck_inventory_balance_not_negative'),
        _org_fk(),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['warehouse_id'], ['inventory_warehouses.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'item_id', 'warehouse_id', name='uq_inventory_balance_item_warehouse'
        ),
    )

    op.create_table(
        'inventory_item_costs',
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('quantity_base', _QTY, nullable=False, server_default='0'),
        sa.Column('value_minor', sa.BigInteger(), nullable=False, server_default='0'),
        _updated_at(),
        sa.CheckConstraint('quantity_base >= 0', name='ck_inventory_cost_quantity'),
        sa.CheckConstraint('value_minor >= 0', name='ck_inventory_cost_value'),
        sa.CheckConstraint(
            'quantity_base > 0 OR value_minor = 0', name='ck_inventory_cost_no_orphan_value'
        ),
        _org_fk(),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('item_id'),
    )

    # Same tenant-isolation pattern as every other business table.
    for table in _TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY {table}_tenant_isolation ON {table} '
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )

    # The stock ledger is append-only, like ledger_entries and journal_entries.
    op.execute(
        'CREATE TRIGGER trg_inventory_stock_movements_append_only '
        'BEFORE UPDATE OR DELETE ON inventory_stock_movements '
        'FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()'
    )


def downgrade() -> None:
    """Downgrade schema.

    Dropping inventory_stock_movements discards the stock ledger permanently;
    downgrade only a database whose inventory history you can afford to lose.
    """
    for table in reversed(_TABLES):
        op.drop_table(table)
    bind = op.get_bind()
    for enum_name in (
        'inventory_adjustment_status',
        'inventory_adjustment_reason',
        'inventory_source_type',
        'inventory_movement_type',
        'inventory_item_type',
    ):
        sa.Enum(name=enum_name).drop(bind, checkfirst=False)
