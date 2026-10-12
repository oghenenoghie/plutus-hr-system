"""Read models for inventory Phase 4 (stock control): stocktake views, lot
stock, reorder suggestions and the stock reports. See
docs/architecture/inventory-integration.md §16.

Every report is rebuilt from the append-only movement ledger, so its
totals agree with the stock balances and, for an organisation posting to
the GL, with the inventory account (the valuation report shows both).
Values are left out (None) for callers without inventory.valuation.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.domain.inventory.accounting import INVENTORY_ACCOUNT
from app.domain.inventory.costing import (
    EMPTY_POOL,
    CostPool,
    average_unit_cost,
    round_minor,
    valued_at_average,
)
from app.domain.inventory.purchasing import line_net_minor
from app.domain.inventory.stocktakes import needs_approval, variance
from app.models.inventory import (
    InventoryCategory,
    InventoryItem,
    InventoryStockMovement,
    InventoryUnit,
    InventoryWarehouse,
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
from app.models.inventory_documents import (
    InventoryPurchaseOrder,
    InventoryPurchaseOrderLine,
    PurchaseOrderStatus,
)
from app.models.journal_entry import JournalEntry
from app.models.ledger import LedgerEntry
from app.models.vendor import Vendor
from app.schemas.inventory_control import (
    ExpiryReportOut,
    LotStockOut,
    MovementSummaryOut,
    MovementSummaryRowOut,
    OutstandingOrderRowOut,
    OutstandingOrdersOut,
    ReorderSuggestionOut,
    StocktakeLineOut,
    StocktakeOut,
    ValuationReportOut,
    ValuationRowOut,
    VarianceReportOut,
    VarianceRowOut,
)
from app.services.inventory import get_inventory_settings
from app.services.inventory_queries import TRACKED_TYPES, document_numbers, lot_numbers
from app.services.inventory_stocktakes import cost_pools, line_variance_values
from app.services.posting import lagos_date, today_lagos

ON_ORDER = (
    PurchaseOrderStatus.APPROVED,
    PurchaseOrderStatus.ISSUED,
    PurchaseOrderStatus.PARTIALLY_RECEIVED,
)
OUTSTANDING = (PurchaseOrderStatus.ISSUED, PurchaseOrderStatus.PARTIALLY_RECEIVED)


def _units(db: Session, unit_ids: set[uuid.UUID]) -> dict[uuid.UUID, InventoryUnit]:
    if not unit_ids:
        return {}
    return {
        u.id: u for u in db.scalars(select(InventoryUnit).where(InventoryUnit.id.in_(unit_ids)))
    }


def _items(db: Session, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, InventoryItem]:
    if not item_ids:
        return {}
    return {
        i.id: i for i in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(item_ids)))
    }


# --- stocktakes -------------------------------------------------------------


def list_stocktakes(
    db: Session,
    *,
    status: StocktakeStatus | None = None,
    warehouse_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[InventoryStocktake]:
    query = select(InventoryStocktake).order_by(InventoryStocktake.created_at.desc()).limit(limit)
    if status is not None:
        query = query.where(InventoryStocktake.status == status)
    if warehouse_id is not None:
        query = query.where(InventoryStocktake.warehouse_id == warehouse_id)
    return list(db.scalars(query))


def stocktake_views(
    db: Session,
    stocktakes: Sequence[InventoryStocktake],
    *,
    with_lines: bool,
    with_value: bool,
) -> list[StocktakeOut]:
    if not stocktakes:
        return []
    ids = [s.id for s in stocktakes]
    lines_by: dict[uuid.UUID, list[InventoryStocktakeLine]] = defaultdict(list)
    for line in db.scalars(
        select(InventoryStocktakeLine)
        .where(InventoryStocktakeLine.stocktake_id.in_(ids))
        .order_by(InventoryStocktakeLine.line_no)
    ):
        lines_by[line.stocktake_id].append(line)
    warehouses = {
        w.id: w
        for w in db.scalars(
            select(InventoryWarehouse).where(
                InventoryWarehouse.id.in_({s.warehouse_id for s in stocktakes})
            )
        )
    }
    category_ids = {s.category_id for s in stocktakes if s.category_id}
    categories = (
        dict(
            db.execute(
                select(InventoryCategory.id, InventoryCategory.name).where(
                    InventoryCategory.id.in_(category_ids)
                )
            )
            .tuples()
            .all()
        )
        if category_ids
        else {}
    )
    all_lines = [line for lines in lines_by.values() for line in lines]
    items = _items(db, {line.item_id for line in all_lines})
    units = _units(db, {item.base_unit_id for item in items.values()})

    # Posted stocktakes: the values their movements actually carried.
    posted_values: dict[uuid.UUID, int] = {}
    posted_ids = [s.id for s in stocktakes if s.status == StocktakeStatus.POSTED]
    if with_value and posted_ids:
        posted_values = dict(
            db.execute(
                select(
                    InventoryStockMovement.source_line_id,
                    func.sum(InventoryStockMovement.value_minor),
                )
                .where(
                    InventoryStockMovement.source_type == StockSourceType.STOCKTAKE,
                    InventoryStockMovement.source_id.in_(posted_ids),
                    InventoryStockMovement.movement_type != StockMovementType.REVERSAL,
                )
                .group_by(InventoryStockMovement.source_line_id)
            )
            .tuples()
            .all()
        )
    limit = get_inventory_settings(
        db, org_id=stocktakes[0].org_id
    ).adjustment_gain_approval_limit_minor

    views = []
    for stocktake in stocktakes:
        lines = lines_by.get(stocktake.id, [])
        posted = stocktake.status == StocktakeStatus.POSTED
        estimates = line_variance_values(db, lines) if not posted else {}
        line_views: list[StocktakeLineOut] = []
        gains = losses = 0
        variance_count = 0
        any_unvalued = False
        for line in lines:
            item = items[line.item_id]
            unit = units[item.base_unit_id]
            diff = (
                variance(line.expected_quantity_base, line.counted_quantity_base)
                if line.counted_quantity_base is not None
                else None
            )
            value: int | None
            if posted:
                value = posted_values.get(line.id, 0)
            else:
                value = estimates.get(line.id)
                if diff is not None and diff > 0 and value is None:
                    any_unvalued = True
            if diff:
                variance_count += 1
                if value:
                    if value > 0:
                        gains += value
                    else:
                        losses += -value
            line_views.append(
                StocktakeLineOut(
                    id=line.id,
                    line_no=line.line_no,
                    item_id=item.id,
                    sku=item.sku,
                    item_name=item.name,
                    base_unit_code=unit.code,
                    base_unit_allows_fraction=unit.allows_fraction,
                    lot_id=line.lot_id,
                    lot_number=line.lot_number,
                    expiry_date=line.expiry_date,
                    expected_quantity=line.expected_quantity_base,
                    counted_quantity=line.counted_quantity_base,
                    variance=diff,
                    variance_value_minor=value if with_value else None,
                    added_during_count=line.expected_quantity_base == 0,
                    notes=line.notes,
                )
            )
        counted = sum(1 for line in lines if line.counted_quantity_base is not None)
        needs: bool | None = None
        if (
            stocktake.status == StocktakeStatus.COUNTING
            and counted == len(lines)
            and not any_unvalued
        ):
            # The same rule submit applies.
            needs = needs_approval(
                ((v.variance, estimates.get(v.id)) for v in line_views if v.variance is not None),
                limit,
            )
        warehouse = warehouses[stocktake.warehouse_id]
        views.append(
            StocktakeOut(
                id=stocktake.id,
                stocktake_number=stocktake.stocktake_number,
                warehouse_id=warehouse.id,
                warehouse_code=warehouse.code,
                warehouse_name=warehouse.name,
                category_id=stocktake.category_id,
                category_name=categories.get(stocktake.category_id)
                if stocktake.category_id
                else None,
                count_date=stocktake.count_date,
                notes=stocktake.notes,
                status=stocktake.status,
                cutoff_at=stocktake.cutoff_at,
                created_at=stocktake.created_at,
                submitted_at=stocktake.submitted_at,
                decided_at=stocktake.decided_at,
                posted_at=stocktake.posted_at,
                cancelled_at=stocktake.cancelled_at,
                line_count=len(lines),
                counted_count=counted,
                variance_count=variance_count,
                gain_value_minor=gains if with_value else None,
                loss_value_minor=losses if with_value else None,
                needs_approval=needs,
                lines=line_views if with_lines else None,
            )
        )
    return views


# --- lots -------------------------------------------------------------------


def lot_stock(
    db: Session,
    *,
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    expiring_by: date | None = None,
    with_value: bool,
) -> list[LotStockOut]:
    """Lots holding stock, soonest expiry first. With `expiring_by`, only
    lots expiring on or before that date (expired ones included)."""
    query = (
        select(InventoryLotBalance, InventoryLot, InventoryItem, InventoryWarehouse)
        .join(InventoryLot, InventoryLot.id == InventoryLotBalance.lot_id)
        .join(InventoryItem, InventoryItem.id == InventoryLotBalance.item_id)
        .join(InventoryWarehouse, InventoryWarehouse.id == InventoryLotBalance.warehouse_id)
        .where(InventoryLotBalance.quantity_base > 0)
        .order_by(
            InventoryLot.expiry_date.asc().nulls_last(),
            InventoryItem.sku,
            InventoryLot.lot_number,
            InventoryWarehouse.code,
        )
    )
    if item_id is not None:
        query = query.where(InventoryLotBalance.item_id == item_id)
    if warehouse_id is not None:
        query = query.where(InventoryLotBalance.warehouse_id == warehouse_id)
    if expiring_by is not None:
        query = query.where(InventoryLot.expiry_date <= expiring_by)
    rows = list(db.execute(query).tuples())
    units = _units(db, {item.base_unit_id for _, _, item, _ in rows})
    pools = cost_pools(db, {item.id for _, _, item, _ in rows}) if with_value else {}
    today = today_lagos()
    out = []
    for balance, lot, item, warehouse in rows:
        days = (lot.expiry_date - today).days if lot.expiry_date else None
        out.append(
            LotStockOut(
                lot_id=lot.id,
                lot_number=lot.lot_number,
                expiry_date=lot.expiry_date,
                item_id=item.id,
                sku=item.sku,
                item_name=item.name,
                base_unit_code=units[item.base_unit_id].code,
                warehouse_id=warehouse.id,
                warehouse_code=warehouse.code,
                quantity=balance.quantity_base,
                expired=days is not None and days < 0,
                days_to_expiry=days,
                value_minor=valued_at_average(pools.get(item.id, EMPTY_POOL), balance.quantity_base)
                if with_value
                else None,
            )
        )
    return out


def expiry_report(db: Session, *, within_days: int, with_value: bool) -> ExpiryReportOut:
    today = today_lagos()
    rows = lot_stock(db, expiring_by=today + timedelta(days=within_days), with_value=with_value)
    expired = sum((r.value_minor or 0) for r in rows if r.expired)
    expiring = sum((r.value_minor or 0) for r in rows if not r.expired)
    return ExpiryReportOut(
        as_of=today,
        within_days=within_days,
        rows=rows,
        expired_value_minor=expired if with_value else None,
        expiring_value_minor=expiring if with_value else None,
    )


# --- reorder ----------------------------------------------------------------


def _expired_quantities(db: Session, today: date) -> dict[uuid.UUID, Decimal]:
    return {
        item_id: quantity
        for item_id, quantity in db.execute(
            select(InventoryLotBalance.item_id, func.sum(InventoryLotBalance.quantity_base))
            .join(InventoryLot, InventoryLot.id == InventoryLotBalance.lot_id)
            .where(InventoryLot.expiry_date < today)
            .group_by(InventoryLotBalance.item_id)
        ).tuples()
    }


def _on_order(db: Session) -> dict[uuid.UUID, Decimal]:
    outstanding = InventoryPurchaseOrderLine.quantity_base - func.least(
        InventoryPurchaseOrderLine.received_quantity_base, InventoryPurchaseOrderLine.quantity_base
    )
    return {
        item_id: quantity
        for item_id, quantity in db.execute(
            select(InventoryPurchaseOrderLine.item_id, func.sum(outstanding))
            .join(
                InventoryPurchaseOrder,
                InventoryPurchaseOrder.id == InventoryPurchaseOrderLine.purchase_order_id,
            )
            .where(InventoryPurchaseOrder.status.in_(ON_ORDER))
            .group_by(InventoryPurchaseOrderLine.item_id)
        ).tuples()
    }


def _last_unit_costs(db: Session, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Net price per base unit on each item's most recent order line that
    went out to a vendor."""
    if not item_ids:
        return {}
    latest = (
        select(
            InventoryPurchaseOrderLine,
            func.row_number()
            .over(
                partition_by=InventoryPurchaseOrderLine.item_id,
                order_by=(
                    InventoryPurchaseOrder.order_date.desc(),
                    InventoryPurchaseOrder.created_at.desc(),
                ),
            )
            .label("rank"),
        )
        .join(
            InventoryPurchaseOrder,
            InventoryPurchaseOrder.id == InventoryPurchaseOrderLine.purchase_order_id,
        )
        .where(
            InventoryPurchaseOrderLine.item_id.in_(item_ids),
            InventoryPurchaseOrder.status.in_(
                (*ON_ORDER, PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.CLOSED)
            ),
        )
        .subquery()
    )
    line = select(latest).where(latest.c.rank == 1)
    costs: dict[uuid.UUID, int] = {}
    for row in db.execute(line).mappings():
        net = line_net_minor(row["quantity"], row["unit_price_minor"], row["discount_minor"])
        costs[row["item_id"]] = round_minor(Decimal(net) / row["quantity_base"])
    return costs


def reorder_suggestions(db: Session, *, with_value: bool) -> list[ReorderSuggestionOut]:
    """Items whose usable stock plus what's on order is at or below their
    reorder level: order up to the maximum level (or the reorder level
    when no maximum is set)."""
    today = today_lagos()
    items = list(
        db.scalars(
            select(InventoryItem)
            .where(
                InventoryItem.is_active.is_(True),
                InventoryItem.item_type.in_(TRACKED_TYPES),
                InventoryItem.reorder_level.is_not(None),
            )
            .order_by(InventoryItem.sku)
        )
    )
    if not items:
        return []
    pools = cost_pools(db, {item.id for item in items})
    expired = _expired_quantities(db, today)
    on_order = _on_order(db)
    vendor_ids = {item.preferred_vendor_id for item in items if item.preferred_vendor_id}
    vendors = (
        dict(
            db.execute(select(Vendor.id, Vendor.name).where(Vendor.id.in_(vendor_ids)))
            .tuples()
            .all()
        )
        if vendor_ids
        else {}
    )
    units = _units(db, {item.base_unit_id for item in items})
    out = []
    candidates = []
    for item in items:
        assert item.reorder_level is not None
        on_hand = pools.get(item.id, EMPTY_POOL).quantity
        stale = expired.get(item.id, Decimal(0))
        ordered = on_order.get(item.id, Decimal(0))
        available = on_hand - stale + ordered
        if available > item.reorder_level:
            continue
        target = item.max_level if item.max_level is not None else item.reorder_level
        suggested = target - available
        unit = units[item.base_unit_id]
        if not unit.allows_fraction:
            suggested = suggested.to_integral_value(rounding=ROUND_CEILING)
        if suggested <= 0:
            continue
        candidates.append((item, on_hand, stale, ordered, available, suggested))
    costs = _last_unit_costs(db, {c[0].id for c in candidates})
    for item, on_hand, stale, ordered, available, suggested in candidates:
        assert item.reorder_level is not None
        cost = costs.get(item.id)
        if cost is None:
            cost = item.default_cost_minor
        out.append(
            ReorderSuggestionOut(
                item_id=item.id,
                sku=item.sku,
                item_name=item.name,
                base_unit_code=units[item.base_unit_id].code,
                reorder_level=item.reorder_level,
                max_level=item.max_level,
                on_hand=on_hand,
                expired=stale,
                on_order=ordered,
                available=available,
                suggested_quantity=suggested,
                preferred_vendor_id=item.preferred_vendor_id,
                preferred_vendor_name=vendors.get(item.preferred_vendor_id)
                if item.preferred_vendor_id
                else None,
                last_unit_cost_minor=cost if with_value else None,
                estimated_cost_minor=round_minor(suggested * cost)
                if with_value and cost is not None
                else None,
            )
        )
    return out


# --- valuation --------------------------------------------------------------


def gl_inventory_balance(db: Session, *, org_id: uuid.UUID, as_of: date) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LedgerEntry.debit_minor - LedgerEntry.credit_minor), 0))
            .join(JournalEntry, JournalEntry.id == LedgerEntry.journal_entry_id)
            .where(
                LedgerEntry.org_id == org_id,
                LedgerEntry.account == INVENTORY_ACCOUNT,
                JournalEntry.entry_date <= as_of,
            )
        )
        or 0
    )


def _gl_covers(db: Session, gl_started_at: datetime | None, as_of: date) -> bool:
    """Whether the inventory account can be compared on `as_of`. Stock that
    moved before GL posting started reached the GL as one opening journal
    on the start date, so before that date the account only matches for
    an organisation that posted to the GL from its first movement."""
    if gl_started_at is None:
        return False
    if as_of >= lagos_date(gl_started_at):
        return True
    return not db.scalar(select(exists().where(InventoryStockMovement.created_at < gl_started_at)))


def valuation_report(
    db: Session,
    *,
    org_id: uuid.UUID,
    as_of: date,
    by_warehouse: bool,
    warehouse_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
) -> ValuationReportOut:
    """Quantity and value of every item at the end of `as_of`. Split by
    warehouse, each warehouse carries the value its movements brought in
    and took out; the item total is the same either way. The GL comparison
    covers the whole organisation, so it's shown only unfiltered."""
    keys = [InventoryStockMovement.item_id]
    if by_warehouse:
        keys.append(InventoryStockMovement.warehouse_id)
    query = (
        select(
            *keys,
            func.sum(InventoryStockMovement.quantity_base),
            func.sum(InventoryStockMovement.value_minor),
        )
        .where(InventoryStockMovement.entry_date <= as_of)
        .group_by(*keys)
    )
    if warehouse_id is not None:
        query = query.where(InventoryStockMovement.warehouse_id == warehouse_id)
    if category_id is not None:
        query = query.join(InventoryItem, InventoryItem.id == InventoryStockMovement.item_id).where(
            InventoryItem.category_id == category_id
        )
    raw = list(db.execute(query).tuples())
    items = _items(db, {row[0] for row in raw})
    units = _units(db, {item.base_unit_id for item in items.values()})
    category_ids = {item.category_id for item in items.values() if item.category_id}
    categories = (
        dict(
            db.execute(
                select(InventoryCategory.id, InventoryCategory.name).where(
                    InventoryCategory.id.in_(category_ids)
                )
            )
            .tuples()
            .all()
        )
        if category_ids
        else {}
    )
    warehouses = {w.id: w for w in db.scalars(select(InventoryWarehouse))} if by_warehouse else {}
    rows: list[ValuationRowOut] = []
    for raw_row in raw:
        item = items[raw_row[0]]
        warehouse = warehouses[raw_row[1]] if by_warehouse else None
        quantity, value = raw_row[-2], int(raw_row[-1])
        if quantity == 0 and value == 0:
            continue
        average = (
            average_unit_cost(CostPool(quantity=quantity, value_minor=value))
            if quantity > 0 and value >= 0
            else None
        )
        rows.append(
            ValuationRowOut(
                item_id=item.id,
                sku=item.sku,
                item_name=item.name,
                category_name=categories.get(item.category_id) if item.category_id else None,
                base_unit_code=units[item.base_unit_id].code,
                warehouse_id=warehouse.id if warehouse else None,
                warehouse_code=warehouse.code if warehouse else None,
                quantity=quantity,
                value_minor=value,
                average_cost_minor=round_minor(average) if average is not None else None,
            )
        )
    rows.sort(key=lambda r: (r.sku, r.warehouse_code or ""))
    total_value = sum(r.value_minor for r in rows)
    settings = get_inventory_settings(db, org_id=org_id)
    gl_balance: int | None = None
    if (
        settings.post_to_gl
        and warehouse_id is None
        and category_id is None
        and _gl_covers(db, settings.gl_started_at, as_of)
    ):
        gl_balance = gl_inventory_balance(db, org_id=org_id, as_of=as_of)
    return ValuationReportOut(
        as_of=as_of,
        by_warehouse=by_warehouse,
        rows=rows,
        total_quantity=sum((r.quantity for r in rows), Decimal(0)),
        total_value_minor=total_value,
        posts_to_gl=settings.post_to_gl,
        gl_started_at=settings.gl_started_at,
        gl_balance_minor=gl_balance,
        difference_minor=total_value - gl_balance if gl_balance is not None else None,
    )


# --- movement summary -------------------------------------------------------

_COLUMN: dict[StockMovementType, str] = {
    StockMovementType.RECEIPT: "received",
    StockMovementType.ISSUE: "issued",
    StockMovementType.TRANSFER_IN: "transferred_in",
    StockMovementType.TRANSFER_OUT: "transferred_out",
    StockMovementType.OPENING_BALANCE: "adjusted",
    StockMovementType.ADJUSTMENT_GAIN: "adjusted",
    StockMovementType.ADJUSTMENT_LOSS: "adjusted",
    StockMovementType.REVERSAL: "reversed",
}


def movement_summary(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    warehouse_id: uuid.UUID | None,
    with_value: bool,
) -> MovementSummaryOut:
    """Per item: the opening balance, each kind of movement in the period
    (signed: stock out is negative) and the closing balance, which is the
    opening plus the movements."""
    if date_to < date_from:
        raise ValueError("the period ends before it starts")
    scope = [InventoryStockMovement.entry_date <= date_to]
    if warehouse_id is not None:
        scope.append(InventoryStockMovement.warehouse_id == warehouse_id)
    opening = InventoryStockMovement.entry_date < date_from
    rows = db.execute(
        select(
            InventoryStockMovement.item_id,
            InventoryStockMovement.movement_type,
            opening.label("before"),
            func.sum(InventoryStockMovement.quantity_base),
            func.sum(InventoryStockMovement.value_minor),
        )
        .where(*scope)
        .group_by(InventoryStockMovement.item_id, InventoryStockMovement.movement_type, opening)
    ).tuples()
    totals: dict[uuid.UUID, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    values: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item_id, movement_type, before, quantity, value in rows:
        if before:
            totals[item_id]["opening"] += quantity
            values[item_id]["opening"] += int(value)
        else:
            totals[item_id][_COLUMN[movement_type]] += quantity
            values[item_id]["period"] += int(value)
    items = _items(db, set(totals))
    units = _units(db, {item.base_unit_id for item in items.values()})
    out = []
    for item_id, t in totals.items():
        item = items[item_id]
        moved = sum(
            (
                t[c]
                for c in (
                    "received",
                    "issued",
                    "transferred_in",
                    "transferred_out",
                    "adjusted",
                    "reversed",
                )
            ),
            Decimal(0),
        )
        closing = t["opening"] + moved
        if (
            t["opening"] == 0
            and closing == 0
            and all(
                t[c] == 0
                for c in (
                    "received",
                    "issued",
                    "transferred_in",
                    "transferred_out",
                    "adjusted",
                    "reversed",
                )
            )
        ):
            continue
        out.append(
            MovementSummaryRowOut(
                item_id=item.id,
                sku=item.sku,
                item_name=item.name,
                base_unit_code=units[item.base_unit_id].code,
                opening_quantity=t["opening"],
                received=t["received"],
                issued=t["issued"],
                transferred_in=t["transferred_in"],
                transferred_out=t["transferred_out"],
                adjusted=t["adjusted"],
                reversed=t["reversed"],
                closing_quantity=closing,
                opening_value_minor=values[item_id]["opening"] if with_value else None,
                closing_value_minor=values[item_id]["opening"] + values[item_id]["period"]
                if with_value
                else None,
            )
        )
    out.sort(key=lambda r: r.sku)
    return MovementSummaryOut(
        date_from=date_from, date_to=date_to, warehouse_id=warehouse_id, rows=out
    )


# --- adjustments and variances ----------------------------------------------


def variance_report(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    warehouse_id: uuid.UUID | None,
    with_value: bool,
) -> VarianceReportOut:
    """Stock gained and lost outside the normal flow: adjustments, stocktake
    variances and transit losses, with reversals of adjustments and counts."""
    if date_to < date_from:
        raise ValueError("the period ends before it starts")
    corrective = (StockSourceType.INVENTORY_ADJUSTMENT, StockSourceType.STOCKTAKE)
    query = (
        select(InventoryStockMovement, InventoryItem, InventoryWarehouse, InventoryUnit.code)
        .join(InventoryItem, InventoryItem.id == InventoryStockMovement.item_id)
        .join(InventoryWarehouse, InventoryWarehouse.id == InventoryStockMovement.warehouse_id)
        .join(InventoryUnit, InventoryUnit.id == InventoryItem.base_unit_id)
        .where(
            InventoryStockMovement.entry_date >= date_from,
            InventoryStockMovement.entry_date <= date_to,
            or_(
                InventoryStockMovement.movement_type.in_(
                    (StockMovementType.ADJUSTMENT_GAIN, StockMovementType.ADJUSTMENT_LOSS)
                ),
                and_(
                    InventoryStockMovement.movement_type == StockMovementType.REVERSAL,
                    InventoryStockMovement.source_type.in_(corrective),
                ),
            ),
        )
        .order_by(
            InventoryStockMovement.entry_date,
            InventoryStockMovement.created_at,
            InventoryStockMovement.id,
        )
    )
    if warehouse_id is not None:
        query = query.where(InventoryStockMovement.warehouse_id == warehouse_id)
    rows = list(db.execute(query).tuples())
    numbers = document_numbers(db, {(m.source_type, m.source_id) for m, _, _, _ in rows})
    lots = lot_numbers(db, {m.lot_id for m, _, _, _ in rows if m.lot_id})
    out = [
        VarianceRowOut(
            entry_date=movement.entry_date,
            source_type=movement.source_type.value,
            source_id=movement.source_id,
            source_number=numbers.get(movement.source_id),
            reason=movement.reason,
            item_id=item.id,
            sku=item.sku,
            item_name=item.name,
            base_unit_code=unit_code,
            warehouse_code=warehouse.code,
            lot_number=lots.get(movement.lot_id) if movement.lot_id else None,
            movement_type=movement.movement_type,
            quantity=movement.quantity_base,
            value_minor=movement.value_minor if with_value else None,
        )
        for movement, item, warehouse, unit_code in rows
    ]
    gains = sum(m.value_minor for m, _, _, _ in rows if m.value_minor > 0)
    losses = -sum(m.value_minor for m, _, _, _ in rows if m.value_minor < 0)
    return VarianceReportOut(
        date_from=date_from,
        date_to=date_to,
        rows=out,
        gain_value_minor=gains if with_value else None,
        loss_value_minor=losses if with_value else None,
    )


# --- purchase orders outstanding --------------------------------------------


def outstanding_orders(db: Session) -> OutstandingOrdersOut:
    """Order lines issued to vendors and not yet fully received, valued at
    their net price (before tax)."""
    rows = list(
        db.execute(
            select(InventoryPurchaseOrderLine, InventoryPurchaseOrder, Vendor.name, InventoryItem)
            .join(
                InventoryPurchaseOrder,
                InventoryPurchaseOrder.id == InventoryPurchaseOrderLine.purchase_order_id,
            )
            .join(Vendor, Vendor.id == InventoryPurchaseOrder.vendor_id)
            .join(InventoryItem, InventoryItem.id == InventoryPurchaseOrderLine.item_id)
            .where(
                InventoryPurchaseOrder.status.in_(OUTSTANDING),
                InventoryPurchaseOrderLine.received_quantity_base
                < InventoryPurchaseOrderLine.quantity_base,
            )
            .order_by(
                InventoryPurchaseOrder.expected_date.asc().nulls_last(),
                InventoryPurchaseOrder.po_number,
                InventoryPurchaseOrderLine.line_no,
            )
        ).tuples()
    )
    units = _units(db, {item.base_unit_id for _, _, _, item in rows})
    out = []
    for line, order, vendor_name, item in rows:
        outstanding = line.quantity_base - line.received_quantity_base
        net = line_net_minor(line.quantity, line.unit_price_minor, line.discount_minor)
        out.append(
            OutstandingOrderRowOut(
                purchase_order_id=order.id,
                po_number=order.po_number,
                vendor_name=vendor_name,
                order_date=order.order_date,
                expected_date=order.expected_date,
                status=order.status.value,
                item_id=item.id,
                sku=item.sku,
                item_name=item.name,
                base_unit_code=units[item.base_unit_id].code,
                ordered=line.quantity_base,
                received=line.received_quantity_base,
                outstanding=outstanding,
                outstanding_value_minor=round_minor(
                    Decimal(net) * outstanding / line.quantity_base
                ),
            )
        )
    return OutstandingOrdersOut(
        rows=out, total_value_minor=sum(r.outstanding_value_minor for r in out)
    )
