"""inventory performance indexes

Revision ID: 7f6106c58e40
Revises: d8a35f6b2c71
Create Date: 2026-10-13 12:00:00.000000

Phase 5 of docs/architecture/inventory-integration.md (§17). Indexes only:
no table, column or data changes. Each one was justified by EXPLAIN ANALYZE
on a seeded database (one organisation with 121k movements among 41 others,
444k movements in all), as the API's ordinary role with the tenant set:

- inventory_stock_movements (org_id, entry_date, created_at, id): the
  movement list's newest-first order is walked backwards instead of sorting
  the organisation's whole history (237 ms -> 1.7 ms for the first page,
  with the page-first query in app/services/inventory_queries.py), and
  date-bounded reports read only their dates;
- inventory_stock_movements (org_id, created_at, id): the overview's latest
  movements (230 ms -> 0.2 ms);
- inventory_purchase_order_lines (org_id, item_id): reorder suggestions,
  which otherwise scan every organisation's order lines (63 ms -> 7 ms);
- inventory_goods_receipt_lines (po_line_id): the foreign-key check run for
  each line deleted when a draft order is edited or deleted, otherwise a
  scan of every organisation's receipt lines (11 ms -> 0.7 ms for 3 lines);
- inventory_lot_balances (org_id, warehouse_id): lot stock and expiry
  (57 ms -> 7 ms);
- inventory_item_costs (org_id): the overview's stock value and stock-out
  counts (9-11 ms -> under 1 ms).

Without an index that starts with org_id, the tenant-isolation policy's
filter can't narrow a scan, so the cost grows with every organisation on a
shared database rather than with this one's own data.

CREATE INDEX (not CONCURRENTLY) inside the migration's transaction: it
blocks writes to each table while it builds, which on these tables takes
well under a second at today's volumes. Downgrade drops the indexes.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7f6106c58e40'
down_revision: Union[str, Sequence[str], None] = 'd8a35f6b2c71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    (
        'ix_inventory_movements_org_date',
        'inventory_stock_movements',
        ['org_id', 'entry_date', 'created_at', 'id'],
    ),
    (
        'ix_inventory_movements_org_created',
        'inventory_stock_movements',
        ['org_id', 'created_at', 'id'],
    ),
    ('ix_inventory_po_lines_org_item', 'inventory_purchase_order_lines', ['org_id', 'item_id']),
    ('ix_inventory_grn_lines_po_line', 'inventory_goods_receipt_lines', ['po_line_id']),
    (
        'ix_inventory_lot_balances_org_warehouse',
        'inventory_lot_balances',
        ['org_id', 'warehouse_id'],
    ),
    ('ix_inventory_item_costs_org', 'inventory_item_costs', ['org_id']),
)


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
