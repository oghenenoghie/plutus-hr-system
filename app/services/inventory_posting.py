"""The stock-ledger posting engine.

`post_movements` is the one place stock moves. It writes the append-only
movements and updates the two projections — per-warehouse quantity
(inventory_stock_balances) and the per-item weighted-average cost pool
(inventory_item_costs) — inside the caller's transaction, so stock and its
history can never disagree. Every document posts through it: adjustments
(app/services/inventory_adjustments.py), goods receipts, issues and
transfers (Phase 2), stocktakes later.

Concurrency: the cost rows of every item involved, then the balance rows of
every (item, warehouse) pair, are locked FOR UPDATE in sorted order before
anything is read or written. Two postings touching the same stock therefore
run one after the other, and the second sees the first's result — it cannot
spend stock the first already took. Sorting gives every transaction the same
lock order, so they cannot deadlock on each other.

Idempotency: a document changes status under a row lock, and the movements
carry a unique (org, source type, source line, movement type, warehouse)
key, so the same line can never be posted (or reversed) twice even under
retries.

No general-ledger posting happens here yet: that is Phase 3, once period
control (D13) and the receipt-accounting policy (D2) are in place.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.inventory.costing import (
    CostPool,
    InsufficientStockError,
    apply_decrease,
    apply_increase,
    round_minor,
)
from app.domain.inventory.quantities import normalise
from app.models.inventory import (
    InventoryItemCost,
    InventoryStockBalance,
    InventoryStockMovement,
    StockMovementType,
    StockSourceType,
)
from app.services.inventory import InventoryConflict, get_item, get_unit, get_warehouse

__all__ = ["InsufficientStockError", "PlannedMovement", "post_movements"]


# --- the posting engine -----------------------------------------------------


@dataclass(frozen=True)
class PlannedMovement:
    """One stock change to post. `quantity_base` is signed and non-zero.
    An increase carries the value it enters at; a decrease leaves at the
    item's average cost, worked out when it posts."""

    source_line_id: uuid.UUID
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity_base: Decimal
    movement_type: StockMovementType
    increase_value_minor: int | None = None
    reversal_of_id: uuid.UUID | None = None
    reason: str | None = None


def post_movements(
    db: Session,
    *,
    org_id: uuid.UUID,
    entry_date: date,
    source_type: StockSourceType,
    source_id: uuid.UUID,
    planned: Sequence[PlannedMovement],
    actor_account_id: uuid.UUID | None,
) -> list[InventoryStockMovement]:
    if not planned:
        raise ValueError("nothing to post")
    for plan in planned:
        if plan.quantity_base == 0:
            raise ValueError("a stock movement needs a non-zero quantity")
        if plan.quantity_base > 0 and plan.increase_value_minor is None:
            raise ValueError("an increase needs a value")

    pools = _lock_cost_pools(db, org_id=org_id, item_ids={p.item_id for p in planned})
    balances = _lock_balances(
        db, org_id=org_id, pairs={(p.item_id, p.warehouse_id) for p in planned}
    )

    movements: list[InventoryStockMovement] = []
    for plan in planned:
        pool_row = pools[plan.item_id]
        balance = balances[(plan.item_id, plan.warehouse_id)]
        pool = CostPool(quantity=pool_row.quantity_base, value_minor=pool_row.value_minor)

        if plan.quantity_base > 0:
            assert plan.increase_value_minor is not None
            value = plan.increase_value_minor
            new_pool = apply_increase(pool, plan.quantity_base, value)
            signed_value = value
        else:
            wanted = -plan.quantity_base
            if balance.quantity_base < wanted:
                raise InsufficientStockError(_shortage_message(db, plan, balance.quantity_base))
            new_pool, value = apply_decrease(pool, wanted)
            signed_value = -value

        balance.quantity_base = normalise(balance.quantity_base + plan.quantity_base)
        pool_row.quantity_base = new_pool.quantity
        pool_row.value_minor = new_pool.value_minor
        movements.append(
            InventoryStockMovement(
                org_id=org_id,
                item_id=plan.item_id,
                warehouse_id=plan.warehouse_id,
                movement_type=plan.movement_type,
                quantity_base=plan.quantity_base,
                value_minor=signed_value,
                unit_cost_minor=round_minor(Decimal(abs(signed_value)) / abs(plan.quantity_base)),
                entry_date=entry_date,
                source_type=source_type,
                source_id=source_id,
                source_line_id=plan.source_line_id,
                reversal_of_id=plan.reversal_of_id,
                reason=plan.reason,
                posted_by=actor_account_id,
            )
        )

    db.add_all(movements)
    try:
        db.flush()
    except IntegrityError as exc:
        # The unique source-line key: this line was already posted. The
        # document lock makes this unreachable in normal use; it is the
        # structural backstop.
        raise InventoryConflict("this document has already been posted") from exc
    return movements


def _lock_cost_pools(
    db: Session, *, org_id: uuid.UUID, item_ids: set[uuid.UUID]
) -> dict[uuid.UUID, InventoryItemCost]:
    ordered = sorted(item_ids)
    db.execute(
        pg_insert(InventoryItemCost)
        .values(
            [
                {"item_id": item_id, "org_id": org_id, "quantity_base": 0, "value_minor": 0}
                for item_id in ordered
            ]
        )
        .on_conflict_do_nothing(index_elements=["item_id"])
    )
    rows = db.scalars(
        select(InventoryItemCost)
        .where(InventoryItemCost.item_id.in_(ordered))
        .order_by(InventoryItemCost.item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return {row.item_id: row for row in rows}


def _lock_balances(
    db: Session, *, org_id: uuid.UUID, pairs: set[tuple[uuid.UUID, uuid.UUID]]
) -> dict[tuple[uuid.UUID, uuid.UUID], InventoryStockBalance]:
    ordered = sorted(pairs)
    db.execute(
        pg_insert(InventoryStockBalance)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "org_id": org_id,
                    "item_id": item_id,
                    "warehouse_id": warehouse_id,
                    "quantity_base": 0,
                }
                for item_id, warehouse_id in ordered
            ]
        )
        .on_conflict_do_nothing(constraint="uq_inventory_balance_item_warehouse")
    )
    rows = db.scalars(
        select(InventoryStockBalance)
        .where(
            tuple_(InventoryStockBalance.item_id, InventoryStockBalance.warehouse_id).in_(ordered)
        )
        .order_by(InventoryStockBalance.item_id, InventoryStockBalance.warehouse_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return {(row.item_id, row.warehouse_id): row for row in rows}


def _shortage_message(db: Session, plan: PlannedMovement, available: Decimal) -> str:
    item = get_item(db, plan.item_id)
    unit = get_unit(db, item.base_unit_id)
    warehouse = get_warehouse(db, plan.warehouse_id)
    return (
        f"not enough {item.sku} in {warehouse.code}: {_fmt(available)} {unit.code} available, "
        f"{_fmt(-plan.quantity_base)} {unit.code} needed"
    )


def _fmt(quantity: Decimal) -> str:
    """A quantity without trailing zeros: 12.5000 -> "12.5", 100 -> "100"."""
    return format(quantity.normalize(), "f")
