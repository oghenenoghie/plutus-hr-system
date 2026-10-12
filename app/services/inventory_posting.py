"""Stock adjustment documents and the stock-ledger posting engine.

`post_movements` is the one place stock moves. It writes the append-only
movements and updates the two projections — per-warehouse quantity
(inventory_stock_balances) and the per-item weighted-average cost pool
(inventory_item_costs) — inside the caller's transaction, so stock and its
history can never disagree. Later phases (receipts, issues, transfers,
stocktakes) post through it too.

Concurrency: the cost rows of every item involved, then the balance rows of
every (item, warehouse) pair, are locked FOR UPDATE in sorted order before
anything is read or written. Two postings touching the same stock therefore
run one after the other, and the second sees the first's result — it cannot
spend stock the first already took. Sorting gives every transaction the same
lock order, so they cannot deadlock on each other.

Idempotency: a document is moved out of DRAFT under a row lock, and the
movements carry a unique (org, source type, source line, movement type) key,
so the same line can never be posted (or reversed) twice even under retries.

No general-ledger posting happens here yet: that is Phase 3, once period
control (D13) and the receipt-accounting policy (D2) are in place.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    increase_value,
    round_minor,
)
from app.domain.inventory.quantities import (
    QuantityError,
    normalise,
    require_whole_if_needed,
    to_base_quantity,
)
from app.models.inventory import (
    InventoryAdjustment,
    InventoryAdjustmentLine,
    InventoryAdjustmentReason,
    InventoryAdjustmentStatus,
    InventoryItem,
    InventoryItemCost,
    InventoryItemUnit,
    InventorySettings,
    InventoryStockBalance,
    InventoryStockMovement,
    InventoryUnit,
    StockMovementType,
    StockSourceType,
)
from app.schemas.inventory import AdjustmentCreate
from app.services.inventory import (
    InventoryConflict,
    InventoryNotFound,
    get_item,
    get_unit,
    get_warehouse,
)
from app.services.posting import today_lagos

__all__ = [
    "InsufficientStockError",
    "PlannedMovement",
    "create_adjustment",
    "delete_adjustment",
    "post_adjustment",
    "post_movements",
    "reverse_adjustment",
    "update_adjustment",
]

# +1: the reason only ever adds stock; -1: only ever removes it; 0: either.
_REASON_DIRECTION: dict[InventoryAdjustmentReason, int] = {
    InventoryAdjustmentReason.OPENING_BALANCE: 1,
    InventoryAdjustmentReason.FOUND: 1,
    InventoryAdjustmentReason.DAMAGE: -1,
    InventoryAdjustmentReason.EXPIRY: -1,
    InventoryAdjustmentReason.LOSS: -1,
    InventoryAdjustmentReason.WRITE_OFF: -1,
    InventoryAdjustmentReason.CORRECTION: 0,
}


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


# --- adjustment documents ---------------------------------------------------


@dataclass(frozen=True)
class _ResolvedLine:
    line_no: int
    item: InventoryItem
    unit: InventoryUnit
    quantity: Decimal
    quantity_base: Decimal
    unit_cost_minor: int | None
    notes: str | None


def _resolve_line(
    db: Session,
    *,
    reason: InventoryAdjustmentReason,
    line_no: int,
    item_id: uuid.UUID,
    unit_id: uuid.UUID | None,
    quantity: Decimal,
    unit_cost_minor: int | None,
    notes: str | None,
) -> _ResolvedLine:
    """Validates one line against the item, its units and the reason."""
    item = get_item(db, item_id)
    where = f"line {line_no} ({item.sku})"
    if not item.is_active:
        raise ValueError(f"{where}: this item is archived")
    if not item.item_type.is_tracked:
        raise ValueError(
            f"{where}: {item.item_type.value.replace('_', '-')} items don't hold stock"
        )

    unit = get_unit(db, unit_id or item.base_unit_id)
    if not unit.is_active:
        raise ValueError(f"{where}: unit {unit.code} is inactive")
    factor = _factor_to_base(db, item, unit)
    if factor is None:
        raise ValueError(f"{where}: {unit.code} is not one of this item's units")

    try:
        qty = normalise(quantity)
        if qty == 0:
            raise ValueError(f"{where}: quantity can't be zero")
        require_whole_if_needed(qty, allows_fraction=unit.allows_fraction, unit_code=unit.code)
        base_qty = to_base_quantity(qty, factor)
        base_unit = get_unit(db, item.base_unit_id)
        require_whole_if_needed(
            base_qty, allows_fraction=base_unit.allows_fraction, unit_code=base_unit.code
        )
    except QuantityError as exc:
        raise ValueError(f"{where}: {exc}") from exc

    direction = _REASON_DIRECTION[reason]
    label = reason.value.replace("_", " ")
    if direction > 0 and qty < 0:
        raise ValueError(f"{where}: a {label} adjustment can only add stock")
    if direction < 0 and qty > 0:
        raise ValueError(f"{where}: a {label} adjustment can only remove stock")

    if qty > 0:
        cost = unit_cost_minor if unit_cost_minor is not None else _default_cost(item, factor)
        if cost is None:
            raise ValueError(f"{where}: enter a unit cost (this item has no default cost)")
    else:
        if unit_cost_minor is not None:
            raise ValueError(
                f"{where}: stock removed leaves at the item's average cost; don't enter a cost"
            )
        cost = None

    return _ResolvedLine(
        line_no=line_no,
        item=item,
        unit=unit,
        quantity=qty,
        quantity_base=base_qty,
        unit_cost_minor=cost,
        notes=notes,
    )


def _factor_to_base(db: Session, item: InventoryItem, unit: InventoryUnit) -> Decimal | None:
    if unit.id == item.base_unit_id:
        return Decimal(1)
    return db.scalar(
        select(InventoryItemUnit.factor_to_base).where(
            InventoryItemUnit.item_id == item.id, InventoryItemUnit.unit_id == unit.id
        )
    )


def _default_cost(item: InventoryItem, factor: Decimal) -> int | None:
    """The item's default cost is per base unit; scale it to the line's
    unit (a carton of 24 costs 24 x the per-piece default)."""
    if item.default_cost_minor is None:
        return None
    return round_minor(Decimal(item.default_cost_minor) * factor)


def _resolve_body(db: Session, body: AdjustmentCreate) -> list[_ResolvedLine]:
    return [
        _resolve_line(
            db,
            reason=body.reason,
            line_no=index,
            item_id=line.item_id,
            unit_id=line.unit_id,
            quantity=line.quantity,
            unit_cost_minor=line.unit_cost_minor,
            notes=line.notes,
        )
        for index, line in enumerate(body.lines, start=1)
    ]


def _check_header(db: Session, body: AdjustmentCreate) -> None:
    warehouse = get_warehouse(db, body.warehouse_id)
    if not warehouse.is_active:
        raise ValueError(f"warehouse {warehouse.code} is inactive")
    if body.adjustment_date > today_lagos():
        raise ValueError("an adjustment can't be dated in the future")


def _next_adjustment_number(db: Session, org_id: uuid.UUID) -> str:
    settings = db.scalar(
        select(InventorySettings).where(InventorySettings.org_id == org_id).with_for_update()
    )
    if settings is None or not settings.enabled:
        raise InventoryConflict("inventory is not enabled for this organisation")
    number = settings.next_adjustment_number
    settings.next_adjustment_number = number + 1
    return f"ADJ-{number:06d}"


def _write_lines(db: Session, adjustment: InventoryAdjustment, lines: list[_ResolvedLine]) -> None:
    for line in lines:
        db.add(
            InventoryAdjustmentLine(
                org_id=adjustment.org_id,
                adjustment_id=adjustment.id,
                line_no=line.line_no,
                item_id=line.item.id,
                unit_id=line.unit.id,
                quantity=line.quantity,
                unit_cost_minor=line.unit_cost_minor,
                notes=line.notes,
            )
        )


def create_adjustment(
    db: Session, *, org_id: uuid.UUID, actor_account_id: uuid.UUID | None, body: AdjustmentCreate
) -> InventoryAdjustment:
    _check_header(db, body)
    lines = _resolve_body(db, body)
    adjustment = InventoryAdjustment(
        id=uuid.uuid4(),
        org_id=org_id,
        adjustment_number=_next_adjustment_number(db, org_id),
        warehouse_id=body.warehouse_id,
        reason=body.reason,
        adjustment_date=body.adjustment_date,
        notes=body.notes,
        status=InventoryAdjustmentStatus.DRAFT,
        created_by=actor_account_id,
    )
    db.add(adjustment)
    db.flush()
    _write_lines(db, adjustment, lines)
    db.flush()
    return adjustment


def _lock_adjustment(db: Session, adjustment_id: uuid.UUID) -> InventoryAdjustment:
    adjustment = db.scalar(
        select(InventoryAdjustment)
        .where(InventoryAdjustment.id == adjustment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if adjustment is None:
        raise InventoryNotFound("adjustment not found")
    return adjustment


def _require_draft(adjustment: InventoryAdjustment) -> None:
    if adjustment.status != InventoryAdjustmentStatus.DRAFT:
        raise InventoryConflict(
            f"{adjustment.adjustment_number} is {adjustment.status.value}; only a draft can change"
        )


def update_adjustment(
    db: Session, adjustment_id: uuid.UUID, body: AdjustmentCreate
) -> InventoryAdjustment:
    """Replaces a draft's header and lines."""
    adjustment = _lock_adjustment(db, adjustment_id)
    _require_draft(adjustment)
    _check_header(db, body)
    lines = _resolve_body(db, body)
    for old in db.scalars(
        select(InventoryAdjustmentLine).where(
            InventoryAdjustmentLine.adjustment_id == adjustment.id
        )
    ):
        db.delete(old)
    db.flush()
    adjustment.warehouse_id = body.warehouse_id
    adjustment.reason = body.reason
    adjustment.adjustment_date = body.adjustment_date
    adjustment.notes = body.notes
    _write_lines(db, adjustment, lines)
    db.flush()
    return adjustment


def delete_adjustment(db: Session, adjustment_id: uuid.UUID) -> InventoryAdjustment:
    """Deletes a draft (its lines go with it). Posted documents are kept."""
    adjustment = _lock_adjustment(db, adjustment_id)
    _require_draft(adjustment)
    db.delete(adjustment)
    db.flush()
    return adjustment


def post_adjustment(
    db: Session, adjustment_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryAdjustment:
    adjustment = _lock_adjustment(db, adjustment_id)
    _require_draft(adjustment)
    stored = list(
        db.scalars(
            select(InventoryAdjustmentLine)
            .where(InventoryAdjustmentLine.adjustment_id == adjustment.id)
            .order_by(InventoryAdjustmentLine.line_no)
        )
    )
    if not stored:
        raise ValueError(f"{adjustment.adjustment_number} has no lines")
    warehouse = get_warehouse(db, adjustment.warehouse_id)
    if not warehouse.is_active:
        raise ValueError(f"warehouse {warehouse.code} is inactive")
    if adjustment.adjustment_date > today_lagos():
        raise ValueError("an adjustment can't be dated in the future")

    planned: list[PlannedMovement] = []
    for line in stored:
        # Re-validated at post time: the item, unit or conversion may have
        # changed since the draft was saved.
        resolved = _resolve_line(
            db,
            reason=adjustment.reason,
            line_no=line.line_no,
            item_id=line.item_id,
            unit_id=line.unit_id,
            quantity=line.quantity,
            unit_cost_minor=line.unit_cost_minor,
            notes=line.notes,
        )
        if resolved.quantity > 0:
            assert resolved.unit_cost_minor is not None
            movement_type = (
                StockMovementType.OPENING_BALANCE
                if adjustment.reason == InventoryAdjustmentReason.OPENING_BALANCE
                else StockMovementType.ADJUSTMENT_GAIN
            )
            value: int | None = increase_value(resolved.quantity, resolved.unit_cost_minor)
        else:
            movement_type = StockMovementType.ADJUSTMENT_LOSS
            value = None
        planned.append(
            PlannedMovement(
                source_line_id=line.id,
                item_id=line.item_id,
                warehouse_id=adjustment.warehouse_id,
                quantity_base=resolved.quantity_base,
                movement_type=movement_type,
                increase_value_minor=value,
                reason=adjustment.reason.value,
            )
        )

    post_movements(
        db,
        org_id=adjustment.org_id,
        entry_date=adjustment.adjustment_date,
        source_type=StockSourceType.INVENTORY_ADJUSTMENT,
        source_id=adjustment.id,
        planned=planned,
        actor_account_id=actor_account_id,
    )
    adjustment.status = InventoryAdjustmentStatus.POSTED
    adjustment.posted_at = datetime.now(UTC)
    adjustment.posted_by = actor_account_id
    db.flush()
    return adjustment


def reverse_adjustment(
    db: Session,
    adjustment_id: uuid.UUID,
    *,
    actor_account_id: uuid.UUID | None,
    reason: str,
) -> InventoryAdjustment:
    """Undoes a posted adjustment with compensating REVERSAL movements dated
    today. Stock an adjustment removed comes back at the value it left at;
    stock it added leaves at today's average cost, like any other removal —
    the difference from its original value is a cost variance (posted to
    the GL in Phase 3)."""
    reason = reason.strip()
    if not reason:
        raise ValueError("a reason is required to reverse an adjustment")
    adjustment = _lock_adjustment(db, adjustment_id)
    if adjustment.status != InventoryAdjustmentStatus.POSTED:
        raise InventoryConflict(
            f"{adjustment.adjustment_number} is {adjustment.status.value}; "
            "only a posted adjustment can be reversed"
        )
    originals = list(
        db.scalars(
            select(InventoryStockMovement)
            .where(
                InventoryStockMovement.source_type == StockSourceType.INVENTORY_ADJUSTMENT,
                InventoryStockMovement.source_id == adjustment.id,
                InventoryStockMovement.movement_type != StockMovementType.REVERSAL,
            )
            .order_by(InventoryStockMovement.created_at, InventoryStockMovement.id)
        )
    )
    # Put stock back first, then take stock out, so a reversal never fails
    # for a shortage it would itself have refilled.
    originals.sort(key=lambda m: m.quantity_base > 0)
    planned = [
        PlannedMovement(
            source_line_id=original.source_line_id,
            item_id=original.item_id,
            warehouse_id=original.warehouse_id,
            quantity_base=-original.quantity_base,
            movement_type=StockMovementType.REVERSAL,
            increase_value_minor=-original.value_minor if original.quantity_base < 0 else None,
            reversal_of_id=original.id,
            reason=reason,
        )
        for original in originals
    ]
    post_movements(
        db,
        org_id=adjustment.org_id,
        entry_date=today_lagos(),
        source_type=StockSourceType.INVENTORY_ADJUSTMENT,
        source_id=adjustment.id,
        planned=planned,
        actor_account_id=actor_account_id,
    )
    adjustment.status = InventoryAdjustmentStatus.REVERSED
    adjustment.reversed_at = datetime.now(UTC)
    adjustment.reversed_by = actor_account_id
    adjustment.reversal_reason = reason
    db.flush()
    return adjustment
