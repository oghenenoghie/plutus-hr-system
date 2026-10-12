"""inventory stock control: lots and expiry, stocktakes

Revision ID: d8a35f6b2c71
Revises: c5f82a1d7e94
Create Date: 2026-10-12 18:00:00.000000

Phase 4 of docs/architecture/inventory-integration.md (§16). Additive DDL
plus one index swap, no backfill:

- inventory_lots and inventory_lot_balances (D9), inventory_stocktakes and
  inventory_stocktake_lines (D6): org-owned, each with the standard
  tenant-isolation policy and FORCE ROW LEVEL SECURITY;
- lot columns: inventory_items.track_lots / track_expiry (default off, so
  every existing item behaves exactly as before), the lot of each stock
  movement, and lot capture on goods receipt and adjustment lines;
- inventory_settings.next_stocktake_number;
- the stock-movement idempotency key becomes a unique index that includes
  the lot (coalesced, so movements without a lot still collide as before):
  one document line of a lot-tracked item can move several lots;
- enum values: journal_source_type 'stocktake', approval_request_type
  'stocktake', and the new inventory_stocktake_status type. ADD VALUE runs
  inside the transaction (PostgreSQL 12+) and nothing here uses the new
  values. Downgrade leaves the added enum values (PostgreSQL cannot drop
  one; unused values are harmless) and drops the new type.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8a35f6b2c71'
down_revision: Union[str, Sequence[str], None] = 'c5f82a1d7e94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NO_LOT = "'00000000-0000-0000-0000-000000000000'::uuid"
_NEW_TABLES = (
    'inventory_lots',
    'inventory_lot_balances',
    'inventory_stocktakes',
    'inventory_stocktake_lines',
)


def _uuid(name: str, *args: object, **kwargs: object) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, postgresql.UUID(as_uuid=True), *args, **kwargs)  # type: ignore[arg-type]


def _org() -> sa.Column:  # type: ignore[type-arg]
    return _uuid(
        'org_id', sa.ForeignKey('organisations.id', ondelete='CASCADE'), nullable=False
    )


def upgrade() -> None:
    op.execute("ALTER TYPE journal_source_type ADD VALUE IF NOT EXISTS 'stocktake'")
    op.execute("ALTER TYPE approval_request_type ADD VALUE IF NOT EXISTS 'stocktake'")

    # --- lots (D9)
    op.add_column(
        'inventory_items',
        sa.Column('track_lots', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'inventory_items',
        sa.Column('track_expiry', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        'ck_inventory_item_expiry_lots', 'inventory_items', 'track_lots OR NOT track_expiry'
    )
    op.create_table(
        'inventory_lots',
        _uuid('id', primary_key=True),
        _org(),
        _uuid('item_id', sa.ForeignKey('inventory_items.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('lot_number', sa.String(length=64), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.UniqueConstraint('org_id', 'item_id', 'lot_number', name='uq_inventory_lot_number'),
    )
    op.create_table(
        'inventory_lot_balances',
        _uuid('id', primary_key=True),
        _org(),
        _uuid('item_id', sa.ForeignKey('inventory_items.id', ondelete='RESTRICT'), nullable=False),
        _uuid(
            'warehouse_id',
            sa.ForeignKey('inventory_warehouses.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        _uuid('lot_id', sa.ForeignKey('inventory_lots.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity_base', sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint('item_id', 'warehouse_id', 'lot_id', name='uq_inventory_lot_balance'),
        sa.CheckConstraint('quantity_base >= 0', name='ck_inventory_lot_balance_quantity'),
    )
    op.create_index(
        'ix_inventory_lot_balances_item_wh', 'inventory_lot_balances', ['item_id', 'warehouse_id']
    )
    op.add_column(
        'inventory_stock_movements',
        _uuid('lot_id', sa.ForeignKey('inventory_lots.id', ondelete='RESTRICT'), nullable=True),
    )
    for table in ('inventory_goods_receipt_lines', 'inventory_adjustment_lines'):
        op.add_column(table, sa.Column('lot_number', sa.String(length=64), nullable=True))
        op.add_column(table, sa.Column('expiry_date', sa.Date(), nullable=True))

    op.drop_constraint(
        'uq_inventory_movement_source_line', 'inventory_stock_movements', type_='unique'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_inventory_movement_source_line ON inventory_stock_movements '
        '(org_id, source_type, source_line_id, movement_type, warehouse_id, '
        f'coalesce(lot_id, {_NO_LOT}))'
    )

    # --- stocktakes (D6)
    op.add_column(
        'inventory_settings',
        sa.Column('next_stocktake_number', sa.Integer(), nullable=False, server_default='1'),
    )
    op.drop_constraint(
        'ck_inventory_next_document_numbers', 'inventory_settings', type_='check'
    )
    op.create_check_constraint(
        'ck_inventory_next_document_numbers',
        'inventory_settings',
        'next_po_number > 0 AND next_grn_number > 0 AND next_issue_number > 0 '
        'AND next_transfer_number > 0 AND next_stocktake_number > 0',
    )
    stocktake_status = postgresql.ENUM(
        'draft',
        'counting',
        'pending_approval',
        'approved',
        'rejected',
        'posted',
        'cancelled',
        name='inventory_stocktake_status',
    )
    stocktake_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        'inventory_stocktakes',
        _uuid('id', primary_key=True),
        _org(),
        sa.Column('stocktake_number', sa.String(length=32), nullable=False),
        _uuid(
            'warehouse_id',
            sa.ForeignKey('inventory_warehouses.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        _uuid(
            'category_id',
            sa.ForeignKey('inventory_categories.id', ondelete='RESTRICT'),
            nullable=True,
        ),
        sa.Column('count_date', sa.Date(), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column(
            'status',
            postgresql.ENUM(name='inventory_stocktake_status', create_type=False),
            nullable=False,
        ),
        sa.Column('cutoff_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        _uuid('created_by', nullable=True),
        _uuid('started_by', nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        _uuid('submitted_by', nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        _uuid('posted_by', nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        _uuid('cancelled_by', nullable=True),
        sa.UniqueConstraint('org_id', 'stocktake_number', name='uq_inventory_stocktake_number'),
    )
    op.create_index('ix_inventory_stocktake_status', 'inventory_stocktakes', ['org_id', 'status'])
    op.create_table(
        'inventory_stocktake_lines',
        _uuid('id', primary_key=True),
        _org(),
        _uuid(
            'stocktake_id',
            sa.ForeignKey('inventory_stocktakes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('line_no', sa.Integer(), nullable=False),
        _uuid('item_id', sa.ForeignKey('inventory_items.id', ondelete='RESTRICT'), nullable=False),
        _uuid('lot_id', sa.ForeignKey('inventory_lots.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('lot_number', sa.String(length=64), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('expected_quantity_base', sa.Numeric(18, 4), nullable=False),
        sa.Column('counted_quantity_base', sa.Numeric(18, 4), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.UniqueConstraint('stocktake_id', 'line_no', name='uq_inventory_stocktake_line_no'),
        sa.CheckConstraint(
            'expected_quantity_base >= 0', name='ck_inventory_stocktake_line_expected'
        ),
        sa.CheckConstraint(
            'counted_quantity_base IS NULL OR counted_quantity_base >= 0',
            name='ck_inventory_stocktake_line_counted',
        ),
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_inventory_stocktake_item_lot ON inventory_stocktake_lines '
        "(stocktake_id, item_id, coalesce(lot_number, ''))"
    )

    for table in _NEW_TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY {table}_tenant_isolation ON {table} '
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        op.execute(f'DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}')
    op.drop_table('inventory_stocktake_lines')
    op.drop_index('ix_inventory_stocktake_status', table_name='inventory_stocktakes')
    op.drop_table('inventory_stocktakes')
    postgresql.ENUM(name='inventory_stocktake_status').drop(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        'ck_inventory_next_document_numbers', 'inventory_settings', type_='check'
    )
    op.create_check_constraint(
        'ck_inventory_next_document_numbers',
        'inventory_settings',
        'next_po_number > 0 AND next_grn_number > 0 AND next_issue_number > 0 '
        'AND next_transfer_number > 0',
    )
    op.drop_column('inventory_settings', 'next_stocktake_number')

    op.execute('DROP INDEX uq_inventory_movement_source_line')
    op.create_unique_constraint(
        'uq_inventory_movement_source_line',
        'inventory_stock_movements',
        ['org_id', 'source_type', 'source_line_id', 'movement_type', 'warehouse_id'],
    )
    for table in ('inventory_adjustment_lines', 'inventory_goods_receipt_lines'):
        op.drop_column(table, 'expiry_date')
        op.drop_column(table, 'lot_number')
    op.drop_column('inventory_stock_movements', 'lot_id')
    op.drop_index('ix_inventory_lot_balances_item_wh', table_name='inventory_lot_balances')
    op.drop_table('inventory_lot_balances')
    op.drop_table('inventory_lots')
    op.drop_constraint('ck_inventory_item_expiry_lots', 'inventory_items', type_='check')
    op.drop_column('inventory_items', 'track_expiry')
    op.drop_column('inventory_items', 'track_lots')
