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
carry a unique (org, source type, source line, movement type, warehouse,
lot) key, so the same line can never be posted (or reversed) twice even
under retries.

Lots (D9, Phase 4): a lot-tracked item also keeps a balance per lot
(inventory_lot_balances), locked after its stock balance. An increase names
its lot. A decrease that names none is taken first-expiry-first-out, split
into one movement per lot; `skip_expired` keeps expired lots out of it (an
issue or a transfer never hands out expired stock). Lots carry no value of
their own: costing stays on the item's pool.

The general-ledger side (Phase 3) is posted by each document through
app/services/inventory_accounting.py, from the movements returned here.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text, tuple_
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
    InventoryItem,
    InventoryItemCost,
    InventoryStockBalance,
    InventoryStockMovement,
    StockMovementType,
    StockSourceType,
)
from app.models.inventory_control import InventoryLot, InventoryLotBalance
from app.services.accounting_periods import require_open_period
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
    # Lot-tracked items only: the lot moved. Required for an increase; a
    # decrease without one is allocated first-expiry-first-out.
    lot_id: uuid.UUID | None = None
    # For an allocated decrease: leave lots expired by the posting date
    # alone (issues and transfers).
    skip_expired: bool = False


# Advisory-lock class for "stock is moving in this warehouse". Postings hold
# it shared; a stocktake taking its cutoff snapshot holds it exclusively, so
# the snapshot sees every posting that committed before it and none after
# (D6). Any fixed 32-bit number works; this one is used nowhere else.
_WAREHOUSE_LOCK_CLASS = 0x494E5600


def _warehouse_lock_key(warehouse_id: uuid.UUID) -> int:
    return warehouse_id.int & 0x7FFFFFFF


def lock_warehouses_shared(db: Session, warehouse_ids: set[uuid.UUID]) -> None:
    """Taken by every posting, in key order so concurrent postings and a
    waiting snapshot can't deadlock. Shared holders never block each other."""
    for key in sorted({_warehouse_lock_key(w) for w in warehouse_ids}):
        db.execute(
            text("SELECT pg_advisory_xact_lock_shared(:class_id, :key)"),
            {"class_id": _WAREHOUSE_LOCK_CLASS, "key": key},
        )


def freeze_warehouse(db: Session, warehouse_id: uuid.UUID) -> None:
    """Waits for every posting into or out of the warehouse to finish and
    holds new ones back until this transaction ends."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:class_id, :key)"),
        {"class_id": _WAREHOUSE_LOCK_CLASS, "key": _warehouse_lock_key(warehouse_id)},
    )


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
    # Stock is dated like the journals it feeds, so the lock date (D13)
    # binds it too, whether or not this organisation posts to the GL yet.
    require_open_period(db, org_id=org_id, entry_date=entry_date)
    for plan in planned:
        if plan.quantity_base == 0:
            raise ValueError("a stock movement needs a non-zero quantity")
        if plan.quantity_base > 0 and plan.increase_value_minor is None:
            raise ValueError("an increase needs a value")

    items = {
        item.id: item
        for item in db.scalars(
            select(InventoryItem).where(InventoryItem.id.in_({p.item_id for p in planned}))
        )
    }
    for plan in planned:
        _check_lot_rule(items[plan.item_id], plan)

    lock_warehouses_shared(db, {p.warehouse_id for p in planned})
    pools = _lock_cost_pools(db, org_id=org_id, item_ids={p.item_id for p in planned})
    balances = _lock_balances(
        db, org_id=org_id, pairs={(p.item_id, p.warehouse_id) for p in planned}
    )
    lots = _LotStock.lock(db, org_id=org_id, items=items, planned=planned)

    movements: list[InventoryStockMovement] = []
    for plan in planned:
        balance = balances[(plan.item_id, plan.warehouse_id)]
        if plan.quantity_base < 0 and balance.quantity_base < -plan.quantity_base:
            raise InsufficientStockError(_shortage_message(db, plan, balance.quantity_base))
        if items[plan.item_id].track_lots and plan.lot_id is None:
            parts = lots.allocate(db, plan, entry_date=entry_date)
        else:
            parts = [plan]
        for part in parts:
            movements.append(
                _post_one(
                    part,
                    pool_row=pools[part.item_id],
                    balance=balance,
                    lots=lots,
                    org_id=org_id,
                    entry_date=entry_date,
                    source_type=source_type,
                    source_id=source_id,
                    actor_account_id=actor_account_id,
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


def _check_lot_rule(item: InventoryItem, plan: PlannedMovement) -> None:
    if not item.track_lots and plan.lot_id is not None:
        raise ValueError(f"{item.sku} doesn't track lots")
    if item.track_lots and plan.quantity_base > 0 and plan.lot_id is None:
        raise ValueError(f"{item.sku} tracks lots: say which lot the stock is")


def _post_one(
    plan: PlannedMovement,
    *,
    pool_row: InventoryItemCost,
    balance: InventoryStockBalance,
    lots: "_LotStock",
    org_id: uuid.UUID,
    entry_date: date,
    source_type: StockSourceType,
    source_id: uuid.UUID,
    actor_account_id: uuid.UUID | None,
) -> InventoryStockMovement:
    pool = CostPool(quantity=pool_row.quantity_base, value_minor=pool_row.value_minor)
    if plan.quantity_base > 0:
        assert plan.increase_value_minor is not None
        value = plan.increase_value_minor
        new_pool = apply_increase(pool, plan.quantity_base, value)
        signed_value = value
    else:
        new_pool, value = apply_decrease(pool, -plan.quantity_base)
        signed_value = -value
    if plan.lot_id is not None:
        lots.apply(plan)
    balance.quantity_base = normalise(balance.quantity_base + plan.quantity_base)
    pool_row.quantity_base = new_pool.quantity
    pool_row.value_minor = new_pool.value_minor
    return InventoryStockMovement(
        org_id=org_id,
        item_id=plan.item_id,
        warehouse_id=plan.warehouse_id,
        lot_id=plan.lot_id,
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


class _LotStock:
    """The lot balances one posting touches, locked after the stock
    balances (same lock order everywhere, so no deadlocks)."""

    def __init__(self, rows: list[InventoryLotBalance], lots: dict[uuid.UUID, InventoryLot]):
        self.rows = {(r.item_id, r.warehouse_id, r.lot_id): r for r in rows}
        self.lots = lots

    @classmethod
    def lock(
        cls,
        db: Session,
        *,
        org_id: uuid.UUID,
        items: dict[uuid.UUID, InventoryItem],
        planned: Sequence[PlannedMovement],
    ) -> "_LotStock":
        tracked = [p for p in planned if items[p.item_id].track_lots]
        if not tracked:
            return cls([], {})
        named = sorted({(p.item_id, p.warehouse_id, p.lot_id) for p in tracked if p.lot_id})
        if named:
            db.execute(
                pg_insert(InventoryLotBalance)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "org_id": org_id,
                            "item_id": item_id,
                            "warehouse_id": warehouse_id,
                            "lot_id": lot_id,
                            "quantity_base": 0,
                        }
                        for item_id, warehouse_id, lot_id in named
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_inventory_lot_balance")
            )
        pairs = sorted({(p.item_id, p.warehouse_id) for p in tracked})
        rows = list(
            db.scalars(
                select(InventoryLotBalance)
                .where(
                    tuple_(InventoryLotBalance.item_id, InventoryLotBalance.warehouse_id).in_(pairs)
                )
                .order_by(
                    InventoryLotBalance.item_id,
                    InventoryLotBalance.warehouse_id,
                    InventoryLotBalance.lot_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        lots = {
            lot.id: lot
            for lot in db.scalars(
                select(InventoryLot).where(InventoryLot.id.in_({r.lot_id for r in rows}))
            )
        }
        return cls(rows, lots)

    def apply(self, plan: PlannedMovement) -> None:
        assert plan.lot_id is not None
        row = self.rows[(plan.item_id, plan.warehouse_id, plan.lot_id)]
        after = normalise(row.quantity_base + plan.quantity_base)
        if after < 0:
            lot = self.lots[plan.lot_id]
            raise InsufficientStockError(
                f"lot {lot.lot_number} holds only {_fmt(row.quantity_base)} here, "
                f"{_fmt(-plan.quantity_base)} needed"
            )
        row.quantity_base = after

    def allocate(
        self, db: Session, plan: PlannedMovement, *, entry_date: date
    ) -> list[PlannedMovement]:
        """Splits a decrease across the pair's lots, earliest expiry first
        (lots without an expiry last, then oldest first)."""
        candidates = sorted(
            (
                row
                for (item_id, warehouse_id, _), row in self.rows.items()
                if item_id == plan.item_id
                and warehouse_id == plan.warehouse_id
                and row.quantity_base > 0
            ),
            key=lambda row: (
                self.lots[row.lot_id].expiry_date is None,
                self.lots[row.lot_id].expiry_date or date.max,
                self.lots[row.lot_id].created_at,
                self.lots[row.lot_id].lot_number,
            ),
        )
        expired = Decimal(0)
        if plan.skip_expired:
            fresh = []
            for row in candidates:
                expiry = self.lots[row.lot_id].expiry_date
                if expiry is not None and expiry < entry_date:
                    expired += row.quantity_base
                else:
                    fresh.append(row)
            candidates = fresh
        wanted = -plan.quantity_base
        parts: list[PlannedMovement] = []
        for row in candidates:
            if wanted <= 0:
                break
            take = min(row.quantity_base, wanted)
            parts.append(replace(plan, quantity_base=-take, lot_id=row.lot_id))
            wanted -= take
        if wanted > 0:
            available = -plan.quantity_base - wanted
            item = get_item(db, plan.item_id)
            unit = get_unit(db, item.base_unit_id)
            warehouse = get_warehouse(db, plan.warehouse_id)
            note = f" ({_fmt(expired)} {unit.code} more has expired)" if expired else ""
            raise InsufficientStockError(
                f"not enough {item.sku} in {warehouse.code} that hasn't expired: "
                f"{_fmt(available)} {unit.code} available{note}, "
                f"{_fmt(-plan.quantity_base)} {unit.code} needed"
            )
        return parts


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
