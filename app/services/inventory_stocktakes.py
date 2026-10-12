"""Stocktakes (D6): count a warehouse against a snapshot of the books taken
at a cutoff, and post only the differences. See
docs/architecture/inventory-integration.md §16.

Lifecycle: draft -> counting (start: the snapshot) -> pending_approval or
approved (submit, by the adjustment rule D8) -> posted. A draft can be
deleted; anything short of posted can be cancelled. Rejected is final:
start a new count.

Business carries on during a count. Starting it waits for every posting in
the warehouse to finish and records what the books held at that moment
(cutoff_at); documents posted afterwards change the balance as usual, and
the stocktake adds counted - expected to whatever the balance then is, so
nothing posted after the cutoff is overwritten. Posting is dated on the
count date and is refused in a locked period like any other stock movement.

Errors follow app.services.inventory: InventoryNotFound -> 404,
InventoryConflict -> 409, PermissionError -> 403, any other ValueError ->
400.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.domain.inventory.costing import EMPTY_POOL, CostPool, valued_at_average
from app.domain.inventory.quantities import QuantityError, normalise, require_whole_if_needed
from app.domain.inventory.stocktakes import gain_value_minor, needs_approval, variance
from app.models.approval import ApprovalRequestType
from app.models.inventory import (
    InventoryItem,
    InventoryItemCost,
    InventoryStockBalance,
    InventoryStockMovement,
    StockMovementType,
    StockSourceType,
)
from app.models.inventory_control import (
    InventoryLot,
    InventoryLotBalance,
    InventoryStocktake,
    InventoryStocktakeLine,
    StocktakeStatus,
)
from app.schemas.inventory_control import StocktakeCountsIn, StocktakeCreate, StocktakeLineAdd
from app.services import inventory_accounting as accounting
from app.services.accounting_periods import require_open_period
from app.services.inventory import (
    InventoryConflict,
    InventoryNotFound,
    get_category,
    get_inventory_settings,
    get_item,
    get_unit,
)
from app.services.inventory_common import (
    DocumentKind,
    check_lot,
    lock,
    next_document_number,
    open_approval,
    record_decision,
    require_not_future,
    require_operational_warehouse,
    require_status,
    resolve_lot,
    stamp,
)
from app.services.inventory_posting import PlannedMovement, freeze_warehouse, post_movements

_S = StocktakeStatus


def _lock_stocktake(db: Session, stocktake_id: uuid.UUID) -> InventoryStocktake:
    return lock(db, InventoryStocktake, stocktake_id, "stocktake")


def stocktake_lines(db: Session, stocktake_id: uuid.UUID) -> list[InventoryStocktakeLine]:
    return list(
        db.scalars(
            select(InventoryStocktakeLine)
            .where(InventoryStocktakeLine.stocktake_id == stocktake_id)
            .order_by(InventoryStocktakeLine.line_no)
        )
    )


def _in_scope(item: InventoryItem, stocktake: InventoryStocktake) -> bool:
    return item.item_type.is_tracked and (
        stocktake.category_id is None or item.category_id == stocktake.category_id
    )


def _check_header(db: Session, org_id: uuid.UUID, body: StocktakeCreate) -> None:
    require_operational_warehouse(db, body.warehouse_id)
    require_not_future(body.count_date, "a stocktake")
    require_open_period(db, org_id=org_id, entry_date=body.count_date)
    if body.category_id is not None:
        get_category(db, body.category_id)


# --- drafts -----------------------------------------------------------------


def create_stocktake(
    db: Session, *, org_id: uuid.UUID, actor_account_id: uuid.UUID | None, body: StocktakeCreate
) -> InventoryStocktake:
    _check_header(db, org_id, body)
    stocktake = InventoryStocktake(
        id=uuid.uuid4(),
        org_id=org_id,
        stocktake_number=next_document_number(db, org_id, DocumentKind.STOCKTAKE),
        warehouse_id=body.warehouse_id,
        category_id=body.category_id,
        count_date=body.count_date,
        notes=body.notes,
        status=_S.DRAFT,
        created_by=actor_account_id,
    )
    db.add(stocktake)
    db.flush()
    return stocktake


def update_stocktake(
    db: Session, stocktake_id: uuid.UUID, body: StocktakeCreate
) -> InventoryStocktake:
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.DRAFT, action="edited")
    _check_header(db, stocktake.org_id, body)
    stocktake.warehouse_id = body.warehouse_id
    stocktake.category_id = body.category_id
    stocktake.count_date = body.count_date
    stocktake.notes = body.notes
    db.flush()
    return stocktake


def delete_stocktake(db: Session, stocktake_id: uuid.UUID) -> InventoryStocktake:
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.DRAFT, action="deleted")
    db.delete(stocktake)
    db.flush()
    return stocktake


# --- counting ---------------------------------------------------------------


@dataclass(frozen=True)
class _Snapshot:
    item: InventoryItem
    quantity: Decimal
    lot: InventoryLot | None


def _snapshot(db: Session, stocktake: InventoryStocktake) -> list[_Snapshot]:
    """Every in-scope item (and, for a lot-tracked item, every lot) the
    books hold in the warehouse right now, sorted by SKU then expiry."""
    rows: list[_Snapshot] = []
    balances = db.execute(
        select(InventoryStockBalance, InventoryItem)
        .join(InventoryItem, InventoryItem.id == InventoryStockBalance.item_id)
        .where(
            InventoryStockBalance.warehouse_id == stocktake.warehouse_id,
            InventoryStockBalance.quantity_base != 0,
        )
        .execution_options(populate_existing=True)
    ).tuples()
    for balance, item in balances:
        if not _in_scope(item, stocktake):
            continue
        if not item.track_lots:
            rows.append(_Snapshot(item=item, quantity=balance.quantity_base, lot=None))
            continue
        for lot_balance, lot in db.execute(
            select(InventoryLotBalance, InventoryLot)
            .join(InventoryLot, InventoryLot.id == InventoryLotBalance.lot_id)
            .where(
                InventoryLotBalance.item_id == item.id,
                InventoryLotBalance.warehouse_id == stocktake.warehouse_id,
                InventoryLotBalance.quantity_base != 0,
            )
            .execution_options(populate_existing=True)
        ).tuples():
            rows.append(_Snapshot(item=item, quantity=lot_balance.quantity_base, lot=lot))
    rows.sort(
        key=lambda r: (
            r.item.sku,
            r.lot is None or r.lot.expiry_date is None,
            r.lot.expiry_date if r.lot and r.lot.expiry_date else None,
            r.lot.lot_number if r.lot else "",
        )
    )
    return rows


def start_stocktake(
    db: Session, stocktake_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryStocktake:
    """Takes the snapshot: one line per item (per lot, for a lot-tracked
    item) the books hold here, expected = the quantity at the cutoff."""
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.DRAFT, action="started")
    require_operational_warehouse(db, stocktake.warehouse_id)
    require_not_future(stocktake.count_date, "a stocktake")
    require_open_period(db, org_id=stocktake.org_id, entry_date=stocktake.count_date)

    freeze_warehouse(db, stocktake.warehouse_id)
    stocktake.cutoff_at = db.scalar(select(func.clock_timestamp())) or datetime.now(UTC)
    for line_no, row in enumerate(_snapshot(db, stocktake), start=1):
        db.add(
            InventoryStocktakeLine(
                org_id=stocktake.org_id,
                stocktake_id=stocktake.id,
                line_no=line_no,
                item_id=row.item.id,
                lot_id=row.lot.id if row.lot else None,
                lot_number=row.lot.lot_number if row.lot else None,
                expiry_date=row.lot.expiry_date if row.lot else None,
                expected_quantity_base=row.quantity,
            )
        )
    stocktake.status = _S.COUNTING
    stocktake.started_by = actor_account_id
    db.flush()
    return stocktake


def _counted(db: Session, item: InventoryItem, quantity: Decimal, where: str) -> Decimal:
    unit = get_unit(db, item.base_unit_id)
    try:
        counted = normalise(quantity)
        if counted < 0:
            raise ValueError(f"{where}: a count can't be negative")
        require_whole_if_needed(counted, allows_fraction=unit.allows_fraction, unit_code=unit.code)
    except QuantityError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return counted


def record_counts(
    db: Session, stocktake_id: uuid.UUID, body: StocktakeCountsIn
) -> InventoryStocktake:
    """Enters (or clears, with null) counted quantities, in base units."""
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.COUNTING, action="counted")
    lines = {line.id: line for line in stocktake_lines(db, stocktake.id)}
    seen: set[uuid.UUID] = set()
    for entry in body.counts:
        line = lines.get(entry.line_id)
        if line is None:
            raise InventoryNotFound(f"that line is not on {stocktake.stocktake_number}")
        if entry.line_id in seen:
            raise ValueError(f"line {line.line_no} is counted twice in one request")
        seen.add(entry.line_id)
        item = get_item(db, line.item_id)
        where = f"line {line.line_no} ({item.sku})"
        line.counted_quantity_base = (
            None
            if entry.counted_quantity is None
            else _counted(db, item, entry.counted_quantity, where)
        )
        if "notes" in entry.model_fields_set:
            line.notes = entry.notes
    db.flush()
    return stocktake


def _held_at_cutoff(
    db: Session, stocktake: InventoryStocktake, item_id: uuid.UUID, lot_id: uuid.UUID | None
) -> Decimal:
    """What the movements recorded before the cutoff add up to. Used only
    to refuse a line the snapshot should have listed (say, the item's
    category changed after the count started)."""
    where = [
        InventoryStockMovement.item_id == item_id,
        InventoryStockMovement.warehouse_id == stocktake.warehouse_id,
        InventoryStockMovement.created_at <= stocktake.cutoff_at,
    ]
    if lot_id is not None:
        where.append(InventoryStockMovement.lot_id == lot_id)
    return db.scalar(
        select(func.coalesce(func.sum(InventoryStockMovement.quantity_base), 0)).where(*where)
    ) or Decimal(0)


def add_line(
    db: Session, stocktake_id: uuid.UUID, body: StocktakeLineAdd
) -> InventoryStocktakeLine:
    """Adds an item or lot found on the shelves that the snapshot didn't
    list: the books held none of it here at the cutoff, so it is expected
    to be zero."""
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.COUNTING, action="added to")
    item = get_item(db, body.item_id)
    existing = stocktake_lines(db, stocktake.id)
    line_no = (existing[-1].line_no if existing else 0) + 1
    where = f"line {line_no} ({item.sku})"
    if not _in_scope(item, stocktake):
        raise ValueError(f"{where}: this item isn't part of {stocktake.stocktake_number}")
    lot = check_lot(
        db,
        item=item,
        lot_number=body.lot_number,
        expiry_date=body.expiry_date,
        where=where,
        incoming=True,
    )
    known = None
    if lot.lot_number is not None:
        known = db.scalar(
            select(InventoryLot).where(
                InventoryLot.item_id == item.id, InventoryLot.lot_number == lot.lot_number
            )
        )
    for line in existing:
        if line.item_id == item.id and line.lot_number == lot.lot_number:
            label = f"lot {lot.lot_number}" if lot.lot_number else "this item"
            raise InventoryConflict(f"{where}: {label} is already line {line.line_no}")
    # A lot the books don't know yet can't have been held at the cutoff.
    unknown_lot = item.track_lots and known is None
    if not unknown_lot and _held_at_cutoff(db, stocktake, item.id, known.id if known else None):
        raise InventoryConflict(
            f"{where}: the books held this here at the cutoff but it isn't on the count; "
            "cancel this stocktake and start a new one"
        )
    line = InventoryStocktakeLine(
        org_id=stocktake.org_id,
        stocktake_id=stocktake.id,
        line_no=line_no,
        item_id=item.id,
        lot_id=known.id if known else None,
        lot_number=lot.lot_number,
        expiry_date=known.expiry_date if known else lot.expiry_date,
        expected_quantity_base=Decimal(0),
        counted_quantity_base=_counted(db, item, body.counted_quantity, where),
        notes=body.notes,
    )
    db.add(line)
    db.flush()
    return line


def remove_line(db: Session, stocktake_id: uuid.UUID, line_id: uuid.UUID) -> InventoryStocktake:
    """Removes a line added during the count. Snapshot lines stay: count
    them as zero if the stock isn't there."""
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.COUNTING, action="changed")
    line = db.get(InventoryStocktakeLine, line_id)
    if line is None or line.stocktake_id != stocktake.id:
        raise InventoryNotFound(f"that line is not on {stocktake.stocktake_number}")
    if line.expected_quantity_base != 0:
        raise ValueError(
            f"line {line.line_no} is from the snapshot; count it as 0 if the stock isn't there"
        )
    db.delete(line)
    db.flush()
    return stocktake


# --- values -----------------------------------------------------------------


def cost_pools(db: Session, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, CostPool]:
    if not item_ids:
        return {}
    return {
        row.item_id: CostPool(quantity=row.quantity_base, value_minor=row.value_minor)
        for row in db.scalars(
            select(InventoryItemCost).where(InventoryItemCost.item_id.in_(item_ids))
        )
    }


def line_variance_values(
    db: Session, lines: list[InventoryStocktakeLine]
) -> dict[uuid.UUID, int | None]:
    """Each counted line's variance valued at today's average cost (the
    item's default cost for a gain when it holds no stock). A loss is
    negative. None when a gain can't be valued."""
    counted = [line for line in lines if line.counted_quantity_base is not None]
    items = {
        item.id: item
        for item in db.scalars(
            select(InventoryItem).where(InventoryItem.id.in_({line.item_id for line in counted}))
        )
    }
    pools = cost_pools(db, set(items))
    values: dict[uuid.UUID, int | None] = {}
    for line in counted:
        assert line.counted_quantity_base is not None
        quantity = variance(line.expected_quantity_base, line.counted_quantity_base)
        pool = pools.get(line.item_id, EMPTY_POOL)
        if quantity > 0:
            values[line.id] = gain_value_minor(
                quantity, pool, items[line.item_id].default_cost_minor
            )
        elif quantity < 0:
            values[line.id] = -valued_at_average(pool, -quantity)
        else:
            values[line.id] = 0
    return values


def requires_approval(db: Session, stocktake: InventoryStocktake) -> bool:
    lines = stocktake_lines(db, stocktake.id)
    values = line_variance_values(db, lines)
    limit = get_inventory_settings(db, org_id=stocktake.org_id).adjustment_gain_approval_limit_minor
    return needs_approval(
        (
            (variance(line.expected_quantity_base, line.counted_quantity_base), values[line.id])
            for line in lines
            if line.counted_quantity_base is not None
        ),
        limit,
    )


# --- approval (D8) ----------------------------------------------------------


def submit_stocktake(
    db: Session, stocktake_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryStocktake:
    """Every line must be counted. Missing stock, or found stock worth the
    adjustment approval limit, goes for approval; anything else is approved
    at once and can be posted."""
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.COUNTING, action="submitted")
    lines = stocktake_lines(db, stocktake.id)
    uncounted = [line for line in lines if line.counted_quantity_base is None]
    if uncounted:
        raise ValueError(
            f"{len(uncounted)} line(s) of {stocktake.stocktake_number} aren't counted yet "
            f"(first: line {uncounted[0].line_no}); count them, as 0 if the stock isn't there"
        )
    values = line_variance_values(db, lines)
    for line in lines:
        if values[line.id] is None:
            item = get_item(db, line.item_id)
            raise ValueError(
                f"line {line.line_no} ({item.sku}): stock was found but the item has no cost "
                "to value it at; set its default cost"
            )
    stamp(stocktake, "submitted", actor_account_id)
    if requires_approval(db, stocktake):
        stocktake.status = _S.PENDING_APPROVAL
        open_approval(
            db,
            org_id=stocktake.org_id,
            request_type=ApprovalRequestType.STOCKTAKE,
            request_id=stocktake.id,
        )
    else:
        stocktake.status = _S.APPROVED
        stamp(stocktake, "decided", None)
    db.flush()
    return stocktake


def decide_stocktake(
    db: Session,
    stocktake_id: uuid.UUID,
    *,
    claims: TokenClaims,
    approve: bool,
    comment: str | None = None,
) -> InventoryStocktake:
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(
        stocktake,
        stocktake.stocktake_number,
        _S.PENDING_APPROVAL,
        action="approved" if approve else "rejected",
    )
    if record_decision(
        db,
        claims=claims,
        request_type=ApprovalRequestType.STOCKTAKE,
        request_id=stocktake.id,
        requester_employee_id=None,
        approve=approve,
        comment=comment,
    ):
        stocktake.status = _S.APPROVED if approve else _S.REJECTED
        stamp(stocktake, "decided", None)
    db.flush()
    return stocktake


def cancel_stocktake(
    db: Session, stocktake_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryStocktake:
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(
        stocktake,
        stocktake.stocktake_number,
        _S.DRAFT,
        _S.COUNTING,
        _S.PENDING_APPROVAL,
        _S.APPROVED,
        _S.REJECTED,
        action="cancelled",
    )
    stocktake.status = _S.CANCELLED
    stamp(stocktake, "cancelled", actor_account_id)
    db.flush()
    return stocktake


# --- posting ----------------------------------------------------------------


def post_stocktake(
    db: Session, stocktake_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryStocktake:
    """Posts each line's variance on the count date: stock found comes in
    at today's average cost (the default cost for an item holding none),
    stock missing leaves at the average, both against inventory_adjustment.
    Lots found during the count are created now."""
    stocktake = _lock_stocktake(db, stocktake_id)
    require_status(stocktake, stocktake.stocktake_number, _S.APPROVED, action="posted")
    require_not_future(stocktake.count_date, "a stocktake")
    lines = stocktake_lines(db, stocktake.id)
    values = line_variance_values(db, lines)

    planned: list[PlannedMovement] = []
    for line in lines:
        assert line.counted_quantity_base is not None
        quantity = variance(line.expected_quantity_base, line.counted_quantity_base)
        if quantity == 0:
            continue
        item = get_item(db, line.item_id)
        where = f"line {line.line_no} ({item.sku})"
        if line.lot_id is None and line.lot_number is not None:
            # Found during the count: a lot the books didn't know.
            line.lot_id = resolve_lot(
                db,
                org_id=stocktake.org_id,
                item=item,
                lot_number=line.lot_number,
                expiry_date=line.expiry_date,
                where=where,
                incoming=True,
            )
        gain = quantity > 0
        value = values[line.id]
        if gain and value is None:
            raise ValueError(f"{where}: the item has no cost to value found stock at")
        planned.append(
            PlannedMovement(
                source_line_id=line.id,
                item_id=line.item_id,
                warehouse_id=stocktake.warehouse_id,
                quantity_base=quantity,
                movement_type=(
                    StockMovementType.ADJUSTMENT_GAIN if gain else StockMovementType.ADJUSTMENT_LOSS
                ),
                increase_value_minor=value if gain else None,
                reason=f"stocktake {stocktake.stocktake_number}",
                lot_id=line.lot_id,
            )
        )

    if planned:
        movements = post_movements(
            db,
            org_id=stocktake.org_id,
            entry_date=stocktake.count_date,
            source_type=StockSourceType.STOCKTAKE,
            source_id=stocktake.id,
            planned=planned,
            actor_account_id=actor_account_id,
        )
        accounting.post_stocktake_journal(
            db, stocktake=stocktake, movements=movements, actor_account_id=actor_account_id
        )
    else:
        # Nothing to move, but the lock date still binds the count date.
        require_open_period(db, org_id=stocktake.org_id, entry_date=stocktake.count_date)
    stocktake.status = _S.POSTED
    stamp(stocktake, "posted", actor_account_id)
    db.flush()
    return stocktake


def get_stocktake(db: Session, stocktake_id: uuid.UUID) -> InventoryStocktake:
    stocktake = db.get(InventoryStocktake, stocktake_id)
    if stocktake is None:
        raise InventoryNotFound("stocktake not found")
    return stocktake
