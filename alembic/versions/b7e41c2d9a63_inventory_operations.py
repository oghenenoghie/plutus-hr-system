"""inventory operations: purchase orders, goods receipts, issues, transfers

Revision ID: b7e41c2d9a63
Revises: 99fdc31abd02
Create Date: 2026-10-12 14:00:00.000000

Phase 2 of docs/architecture/inventory-integration.md (§14). Additive DDL
only, no backfill:

- eight new org-owned tables (purchase orders, goods receipts, stock issues
  and transfers, each with lines), each with the standard tenant-isolation
  policy and FORCE ROW LEVEL SECURITY;
- new columns with defaults on inventory_settings (document counters, the
  over-receipt tolerance D4, the adjustment approval limit D8, issue and
  transfer approval switches), inventory_warehouses (is_transit, D5) and
  inventory_adjustments (submission and decision timestamps);
- the stock-movement idempotency key gains warehouse_id, because a transfer
  line legitimately moves out of two warehouses (source, then transit) and
  into two (transit, then destination);
- enum values: four approval request types, six inventory permissions and
  three adjustment statuses. ALTER TYPE ... ADD VALUE runs inside the
  transaction (PostgreSQL 12+) and nothing here uses the new values.
  Downgrade leaves them: PostgreSQL cannot drop an enum value, and an unused
  one is harmless.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e41c2d9a63'
down_revision: Union[str, Sequence[str], None] = '99fdc31abd02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_PERMISSIONS = (
    'inventory.purchase',
    'inventory.approve',
    'inventory.receive',
    'inventory.issue',
    'inventory.transfer',
    'inventory.request',
)
_NEW_REQUEST_TYPES = ('purchase_order', 'stock_adjustment', 'stock_issue', 'stock_transfer')
_NEW_ADJUSTMENT_STATUSES = ('pending_approval', 'approved', 'rejected')

_PO_STATUSES = (
    'draft',
    'pending_approval',
    'approved',
    'rejected',
    'issued',
    'partially_received',
    'received',
    'closed',
    'cancelled',
)
_GRN_STATUSES = ('draft', 'posted', 'reversed')
_ISSUE_STATUSES = (
    'draft',
    'pending_approval',
    'approved',
    'rejected',
    'posted',
    'reversed',
    'cancelled',
)
_TRANSFER_STATUSES = (
    'draft',
    'pending_approval',
    'approved',
    'rejected',
    'in_transit',
    'received',
    'cancelled',
)

# Creation order; dropped in reverse.
_TABLES = (
    'inventory_purchase_orders',
    'inventory_purchase_order_lines',
    'inventory_goods_receipts',
    'inventory_goods_receipt_lines',
    'inventory_stock_issues',
    'inventory_stock_issue_lines',
    'inventory_stock_transfers',
    'inventory_stock_transfer_lines',
)

_QTY = sa.Numeric(18, 4)


def _id() -> sa.Column:
    return sa.Column('id', sa.UUID(), nullable=False)


def _org() -> sa.Column:
    return sa.Column('org_id', sa.UUID(), nullable=False)


def _org_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE')


def _stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)


def _when(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _who(name: str) -> sa.Column:
    return sa.Column(name, sa.UUID(), nullable=True)


def _fk(column: str, table: str, ondelete: str = 'RESTRICT') -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f'{table}.id'], ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    for value in _NEW_PERMISSIONS:
        op.execute(
            f"ALTER TYPE membership_permission_override_permission ADD VALUE IF NOT EXISTS '{value}'"
        )
    for value in _NEW_REQUEST_TYPES:
        op.execute(f"ALTER TYPE approval_request_type ADD VALUE IF NOT EXISTS '{value}'")
    for value in _NEW_ADJUSTMENT_STATUSES:
        op.execute(f"ALTER TYPE inventory_adjustment_status ADD VALUE IF NOT EXISTS '{value}'")

    # --- settings ---------------------------------------------------------
    for column in ('next_po_number', 'next_grn_number', 'next_issue_number', 'next_transfer_number'):
        op.add_column(
            'inventory_settings',
            sa.Column(column, sa.Integer(), nullable=False, server_default='1'),
        )
    op.add_column(
        'inventory_settings',
        sa.Column('over_receipt_tolerance_bp', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'inventory_settings',
        sa.Column('adjustment_gain_approval_limit_minor', sa.BigInteger(), nullable=True),
    )
    op.add_column(
        'inventory_settings',
        sa.Column(
            'require_issue_approval', sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        'inventory_settings',
        sa.Column(
            'require_transfer_approval', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_check_constraint(
        'ck_inventory_next_document_numbers',
        'inventory_settings',
        'next_po_number > 0 AND next_grn_number > 0 AND next_issue_number > 0 '
        'AND next_transfer_number > 0',
    )
    op.create_check_constraint(
        'ck_inventory_over_receipt_tolerance',
        'inventory_settings',
        'over_receipt_tolerance_bp BETWEEN 0 AND 10000',
    )
    op.create_check_constraint(
        'ck_inventory_adjustment_gain_limit',
        'inventory_settings',
        'adjustment_gain_approval_limit_minor IS NULL '
        'OR adjustment_gain_approval_limit_minor >= 0',
    )

    # --- warehouses: the in-transit location (D5) ------------------------
    op.add_column(
        'inventory_warehouses',
        sa.Column('is_transit', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        'uq_inventory_warehouse_transit',
        'inventory_warehouses',
        ['org_id'],
        unique=True,
        postgresql_where=sa.text('is_transit'),
    )

    # --- adjustments: approval (D8) --------------------------------------
    op.add_column('inventory_adjustments', _when('submitted_at'))
    op.add_column('inventory_adjustments', _who('submitted_by'))
    op.add_column('inventory_adjustments', _when('decided_at'))

    # --- movement idempotency key ----------------------------------------
    op.drop_constraint(
        'uq_inventory_movement_source_line', 'inventory_stock_movements', type_='unique'
    )
    op.create_unique_constraint(
        'uq_inventory_movement_source_line',
        'inventory_stock_movements',
        ['org_id', 'source_type', 'source_line_id', 'movement_type', 'warehouse_id'],
    )

    # --- purchase orders --------------------------------------------------
    op.create_table(
        'inventory_purchase_orders',
        _id(),
        _org(),
        sa.Column('po_number', sa.String(length=32), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=True),
        sa.Column('order_date', sa.Date(), nullable=False),
        sa.Column('expected_date', sa.Date(), nullable=True),
        sa.Column('vendor_reference', sa.String(length=64), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column(
            'status', sa.Enum(*_PO_STATUSES, name='inventory_po_status'), nullable=False
        ),
        _who('created_by'),
        _stamp('created_at'),
        _stamp('updated_at'),
        _when('submitted_at'),
        _who('submitted_by'),
        _when('decided_at'),
        _when('issued_at'),
        _who('issued_by'),
        _when('closed_at'),
        _who('closed_by'),
        sa.Column('close_reason', sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            'expected_date IS NULL OR expected_date >= order_date',
            name='ck_inventory_po_expected_date',
        ),
        _org_fk(),
        _fk('vendor_id', 'vendors'),
        _fk('warehouse_id', 'inventory_warehouses'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'po_number', name='uq_inventory_po_number'),
    )
    op.create_index(
        'ix_inventory_po_status', 'inventory_purchase_orders', ['org_id', 'status']
    )

    op.create_table(
        'inventory_purchase_order_lines',
        _id(),
        _org(),
        sa.Column('purchase_order_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('unit_id', sa.UUID(), nullable=False),
        sa.Column('quantity', _QTY, nullable=False),
        sa.Column('quantity_base', _QTY, nullable=False),
        sa.Column('unit_price_minor', sa.BigInteger(), nullable=False),
        sa.Column('discount_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('tax_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('received_quantity_base', _QTY, nullable=False, server_default='0'),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.CheckConstraint('quantity > 0 AND quantity_base > 0', name='ck_inventory_po_line_qty'),
        sa.CheckConstraint(
            'unit_price_minor >= 0 AND discount_minor >= 0 AND tax_minor >= 0',
            name='ck_inventory_po_line_amounts',
        ),
        sa.CheckConstraint(
            'discount_minor <= quantity * unit_price_minor',
            name='ck_inventory_po_line_discount',
        ),
        sa.CheckConstraint('received_quantity_base >= 0', name='ck_inventory_po_line_received'),
        _org_fk(),
        _fk('purchase_order_id', 'inventory_purchase_orders', 'CASCADE'),
        _fk('item_id', 'inventory_items'),
        _fk('unit_id', 'inventory_units'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('purchase_order_id', 'line_no', name='uq_inventory_po_line_no'),
    )

    # --- goods receipts ---------------------------------------------------
    op.create_table(
        'inventory_goods_receipts',
        _id(),
        _org(),
        sa.Column('grn_number', sa.String(length=32), nullable=False),
        sa.Column('purchase_order_id', sa.UUID(), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column('receipt_date', sa.Date(), nullable=False),
        sa.Column('supplier_reference', sa.String(length=64), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column(
            'status', sa.Enum(*_GRN_STATUSES, name='inventory_grn_status'), nullable=False
        ),
        _who('created_by'),
        _stamp('created_at'),
        _stamp('updated_at'),
        _when('posted_at'),
        _who('posted_by'),
        _when('reversed_at'),
        _who('reversed_by'),
        sa.Column('reversal_reason', sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status <> 'reversed' OR reversal_reason IS NOT NULL",
            name='ck_inventory_grn_reversal_reason',
        ),
        _org_fk(),
        _fk('purchase_order_id', 'inventory_purchase_orders'),
        _fk('warehouse_id', 'inventory_warehouses'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'grn_number', name='uq_inventory_grn_number'),
    )
    op.create_index(
        'ix_inventory_grn_purchase_order', 'inventory_goods_receipts', ['purchase_order_id']
    )

    op.create_table(
        'inventory_goods_receipt_lines',
        _id(),
        _org(),
        sa.Column('goods_receipt_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('po_line_id', sa.UUID(), nullable=False),
        sa.Column('accepted_quantity', _QTY, nullable=False),
        sa.Column('rejected_quantity', _QTY, nullable=False, server_default='0'),
        sa.Column('rejection_reason', sa.String(length=500), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            'accepted_quantity >= 0 AND rejected_quantity >= 0 '
            'AND accepted_quantity + rejected_quantity > 0',
            name='ck_inventory_grn_line_qty',
        ),
        _org_fk(),
        _fk('goods_receipt_id', 'inventory_goods_receipts', 'CASCADE'),
        _fk('po_line_id', 'inventory_purchase_order_lines'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('goods_receipt_id', 'line_no', name='uq_inventory_grn_line_no'),
        sa.UniqueConstraint('goods_receipt_id', 'po_line_id', name='uq_inventory_grn_po_line'),
    )

    # --- stock issues -----------------------------------------------------
    op.create_table(
        'inventory_stock_issues',
        _id(),
        _org(),
        sa.Column('issue_number', sa.String(length=32), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column('department_id', sa.UUID(), nullable=True),
        sa.Column('requested_by_employee_id', sa.UUID(), nullable=True),
        sa.Column('issue_date', sa.Date(), nullable=False),
        sa.Column('purpose', sa.String(length=500), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column(
            'status', sa.Enum(*_ISSUE_STATUSES, name='inventory_issue_status'), nullable=False
        ),
        _who('created_by'),
        _stamp('created_at'),
        _stamp('updated_at'),
        _when('submitted_at'),
        _who('submitted_by'),
        _when('decided_at'),
        _when('posted_at'),
        _who('posted_by'),
        _when('reversed_at'),
        _who('reversed_by'),
        sa.Column('reversal_reason', sa.String(length=500), nullable=True),
        _when('cancelled_at'),
        _who('cancelled_by'),
        sa.CheckConstraint(
            "status <> 'reversed' OR reversal_reason IS NOT NULL",
            name='ck_inventory_issue_reversal_reason',
        ),
        _org_fk(),
        _fk('warehouse_id', 'inventory_warehouses'),
        _fk('department_id', 'departments'),
        _fk('requested_by_employee_id', 'employees', 'SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'issue_number', name='uq_inventory_issue_number'),
    )
    op.create_index('ix_inventory_issue_status', 'inventory_stock_issues', ['org_id', 'status'])

    op.create_table(
        'inventory_stock_issue_lines',
        _id(),
        _org(),
        sa.Column('issue_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('unit_id', sa.UUID(), nullable=False),
        sa.Column('quantity', _QTY, nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.CheckConstraint('quantity > 0', name='ck_inventory_issue_line_qty'),
        _org_fk(),
        _fk('issue_id', 'inventory_stock_issues', 'CASCADE'),
        _fk('item_id', 'inventory_items'),
        _fk('unit_id', 'inventory_units'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('issue_id', 'line_no', name='uq_inventory_issue_line_no'),
    )

    # --- transfers --------------------------------------------------------
    op.create_table(
        'inventory_stock_transfers',
        _id(),
        _org(),
        sa.Column('transfer_number', sa.String(length=32), nullable=False),
        sa.Column('from_warehouse_id', sa.UUID(), nullable=False),
        sa.Column('to_warehouse_id', sa.UUID(), nullable=False),
        sa.Column('transfer_date', sa.Date(), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column(
            'status',
            sa.Enum(*_TRANSFER_STATUSES, name='inventory_transfer_status'),
            nullable=False,
        ),
        sa.Column('discrepancy_reason', sa.String(length=500), nullable=True),
        _who('created_by'),
        _stamp('created_at'),
        _stamp('updated_at'),
        _when('submitted_at'),
        _who('submitted_by'),
        _when('decided_at'),
        _when('dispatched_at'),
        _who('dispatched_by'),
        _when('received_at'),
        _who('received_by'),
        _when('cancelled_at'),
        _who('cancelled_by'),
        sa.CheckConstraint(
            'from_warehouse_id <> to_warehouse_id', name='ck_inventory_transfer_warehouses'
        ),
        _org_fk(),
        _fk('from_warehouse_id', 'inventory_warehouses'),
        _fk('to_warehouse_id', 'inventory_warehouses'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'transfer_number', name='uq_inventory_transfer_number'),
    )
    op.create_index(
        'ix_inventory_transfer_status', 'inventory_stock_transfers', ['org_id', 'status']
    )

    op.create_table(
        'inventory_stock_transfer_lines',
        _id(),
        _org(),
        sa.Column('transfer_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('unit_id', sa.UUID(), nullable=False),
        sa.Column('quantity', _QTY, nullable=False),
        sa.Column('dispatched_quantity_base', _QTY, nullable=True),
        sa.Column('received_quantity_base', _QTY, nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.CheckConstraint('quantity > 0', name='ck_inventory_transfer_line_qty'),
        sa.CheckConstraint(
            'received_quantity_base IS NULL OR (dispatched_quantity_base IS NOT NULL '
            'AND received_quantity_base >= 0 '
            'AND received_quantity_base <= dispatched_quantity_base)',
            name='ck_inventory_transfer_line_received',
        ),
        _org_fk(),
        _fk('transfer_id', 'inventory_stock_transfers', 'CASCADE'),
        _fk('item_id', 'inventory_items'),
        _fk('unit_id', 'inventory_units'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transfer_id', 'line_no', name='uq_inventory_transfer_line_no'),
    )

    for table in _TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY {table}_tenant_isolation ON {table} '
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )


def downgrade() -> None:
    """Downgrade schema.

    Restoring the narrower movement key fails if transfers have already been
    dispatched and received (their movements are only unique with the
    warehouse); downgrade only a database without transfer history.
    """
    for table in reversed(_TABLES):
        op.drop_table(table)
    bind = op.get_bind()
    for enum_name in (
        'inventory_transfer_status',
        'inventory_issue_status',
        'inventory_grn_status',
        'inventory_po_status',
    ):
        sa.Enum(name=enum_name).drop(bind, checkfirst=False)

    op.drop_constraint(
        'uq_inventory_movement_source_line', 'inventory_stock_movements', type_='unique'
    )
    op.create_unique_constraint(
        'uq_inventory_movement_source_line',
        'inventory_stock_movements',
        ['org_id', 'source_type', 'source_line_id', 'movement_type'],
    )

    op.drop_column('inventory_adjustments', 'decided_at')
    op.drop_column('inventory_adjustments', 'submitted_by')
    op.drop_column('inventory_adjustments', 'submitted_at')

    op.drop_index('uq_inventory_warehouse_transit', table_name='inventory_warehouses')
    op.drop_column('inventory_warehouses', 'is_transit')

    for constraint in (
        'ck_inventory_adjustment_gain_limit',
        'ck_inventory_over_receipt_tolerance',
        'ck_inventory_next_document_numbers',
    ):
        op.drop_constraint(constraint, 'inventory_settings', type_='check')
    for column in (
        'require_transfer_approval',
        'require_issue_approval',
        'adjustment_gain_approval_limit_minor',
        'over_receipt_tolerance_bp',
        'next_transfer_number',
        'next_issue_number',
        'next_grn_number',
        'next_po_number',
    ):
        op.drop_column('inventory_settings', column)
