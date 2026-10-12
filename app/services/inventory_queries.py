"""Read models for the inventory API: items with their stock, adjustments,
stock on hand, the movement ledger and the overview.

Values and costs are only worked out when the caller may see them
(`with_value`, from inventory.valuation); otherwise those fields are None.
A warehouse's value is its quantity at the item's average cost — the
average is held per item, not per warehouse (D1).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.domain.inventory.costing import (
    CostPool,
    average_unit_cost,
    increase_value,
    round_minor,
    valued_at_average,
)
from app.domain.inventory.quantities import to_base_quantity
from app.models.inventory import (
    InventoryAdjustment,
    InventoryAdjustmentLine,
    InventoryAdjustmentStatus,
    InventoryCategory,
    InventoryItem,
    InventoryItemCost,
    InventoryItemType,
    InventoryItemUnit,
    InventoryStockBalance,
    InventoryStockMovement,
    InventoryUnit,
    InventoryWarehouse,
    StockMovementType,
    StockSourceType,
)
from app.models.inventory_control import InventoryLot, InventoryStocktake
from app.models.inventory_documents import (
    InventoryGoodsReceipt,
    InventoryPurchaseOrder,
    InventoryStockIssue,
    InventoryStockTransfer,
    PurchaseOrderStatus,
    StockIssueStatus,
    StockTransferStatus,
)
from app.schemas.inventory import (
    AdjustmentLineOut,
    AdjustmentOut,
    InventorySummaryOut,
    ItemOut,
    ItemUnitOut,
    MovementOut,
    MovementPage,
    StockRowOut,
)
from app.services.inventory import get_inventory_settings

TRACKED_TYPES = (InventoryItemType.STOCK, InventoryItemType.CONSUMABLE)


def _like(text: str) -> str:
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _pools(db: Session, item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, CostPool]:
    if not item_ids:
        return {}
    rows = db.scalars(select(InventoryItemCost).where(InventoryItemCost.item_id.in_(item_ids)))
    return {
        row.item_id: CostPool(quantity=row.quantity_base, value_minor=row.value_minor)
        for row in rows
    }


def _average_minor(pool: CostPool | None) -> int | None:
    average = average_unit_cost(pool) if pool is not None else None
    return round_minor(average) if average is not None else None


# --- items ------------------------------------------------------------------


def list_items(
    db: Session,
    *,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    item_type: InventoryItemType | None = None,
    include_inactive: bool = False,
) -> list[InventoryItem]:
    query = select(InventoryItem).order_by(InventoryItem.sku)
    if q and q.strip():
        pattern = _like(q)
        query = query.where(
            or_(
                InventoryItem.sku.ilike(pattern, escape="\\"),
                InventoryItem.name.ilike(pattern, escape="\\"),
                InventoryItem.barcode.ilike(pattern, escape="\\"),
            )
        )
    if category_id is not None:
        query = query.where(InventoryItem.category_id == category_id)
    if item_type is not None:
        query = query.where(InventoryItem.item_type == item_type)
    if not include_inactive:
        query = query.where(InventoryItem.is_active.is_(True))
    return list(db.scalars(query))


def item_views(db: Session, items: Sequence[InventoryItem], *, with_value: bool) -> list[ItemOut]:
    if not items:
        return []
    item_ids = [item.id for item in items]
    units = {unit.id: unit for unit in db.scalars(select(InventoryUnit))}
    categories = dict(
        db.execute(select(InventoryCategory.id, InventoryCategory.name)).tuples().all()
    )
    conversions: dict[uuid.UUID, list[ItemUnitOut]] = {}
    for row in db.scalars(
        select(InventoryItemUnit)
        .where(InventoryItemUnit.item_id.in_(item_ids))
        .order_by(InventoryItemUnit.created_at)
    ):
        unit = units[row.unit_id]
        conversions.setdefault(row.item_id, []).append(
            ItemUnitOut(
                unit_id=unit.id,
                unit_code=unit.code,
                unit_name=unit.name,
                factor_to_base=row.factor_to_base,
            )
        )
    pools = _pools(db, item_ids)

    views = []
    for item in items:
        base_unit = units[item.base_unit_id]
        pool = pools.get(item.id)
        views.append(
            ItemOut(
                id=item.id,
                sku=item.sku,
                name=item.name,
                description=item.description,
                item_type=item.item_type,
                category_id=item.category_id,
                category_name=categories.get(item.category_id) if item.category_id else None,
                base_unit_id=base_unit.id,
                base_unit_code=base_unit.code,
                base_unit_allows_fraction=base_unit.allows_fraction,
                reorder_level=item.reorder_level,
                max_level=item.max_level,
                default_cost_minor=item.default_cost_minor,
                preferred_vendor_id=item.preferred_vendor_id,
                barcode=item.barcode,
                is_active=item.is_active,
                track_lots=item.track_lots,
                track_expiry=item.track_expiry,
                created_at=item.created_at,
                units=conversions.get(item.id, []),
                quantity_on_hand=pool.quantity if pool else Decimal(0),
                value_minor=(pool.value_minor if pool else 0) if with_value else None,
                average_cost_minor=_average_minor(pool) if with_value else None,
            )
        )
    return views


# --- adjustments ------------------------------------------------------------


def list_adjustments(
    db: Session,
    *,
    status: InventoryAdjustmentStatus | None = None,
    warehouse_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[InventoryAdjustment]:
    query = (
        select(InventoryAdjustment)
        .order_by(InventoryAdjustment.adjustment_date.desc(), InventoryAdjustment.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        query = query.where(InventoryAdjustment.status == status)
    if warehouse_id is not None:
        query = query.where(InventoryAdjustment.warehouse_id == warehouse_id)
    return list(db.scalars(query))


def adjustment_views(
    db: Session,
    adjustments: Sequence[InventoryAdjustment],
    *,
    with_lines: bool,
    with_value: bool,
) -> list[AdjustmentOut]:
    if not adjustments:
        return []
    ids = [adjustment.id for adjustment in adjustments]
    warehouses = {
        row.id: row
        for row in db.scalars(
            select(InventoryWarehouse).where(
                InventoryWarehouse.id.in_({a.warehouse_id for a in adjustments})
            )
        )
    }
    line_counts = dict(
        db.execute(
            select(InventoryAdjustmentLine.adjustment_id, func.count())
            .where(InventoryAdjustmentLine.adjustment_id.in_(ids))
            .group_by(InventoryAdjustmentLine.adjustment_id)
        )
        .tuples()
        .all()
    )
    # Net value the adjustment posted (its original movements; a reversal
    # does not change what the document itself posted).
    values: dict[uuid.UUID, int] = {}
    if with_value:
        values = {
            source_id: int(total)
            for source_id, total in db.execute(
                select(
                    InventoryStockMovement.source_id, func.sum(InventoryStockMovement.value_minor)
                )
                .where(
                    InventoryStockMovement.source_type == StockSourceType.INVENTORY_ADJUSTMENT,
                    InventoryStockMovement.source_id.in_(ids),
                    InventoryStockMovement.movement_type != StockMovementType.REVERSAL,
                )
                .group_by(InventoryStockMovement.source_id)
            ).tuples()
        }
    lines = _adjustment_lines(db, ids) if with_lines else {}
    needs_approval = _adjustments_needing_approval(db, adjustments)

    views = []
    for adjustment in adjustments:
        warehouse = warehouses[adjustment.warehouse_id]
        views.append(
            AdjustmentOut(
                id=adjustment.id,
                adjustment_number=adjustment.adjustment_number,
                warehouse_id=warehouse.id,
                warehouse_code=warehouse.code,
                warehouse_name=warehouse.name,
                reason=adjustment.reason,
                adjustment_date=adjustment.adjustment_date,
                notes=adjustment.notes,
                status=adjustment.status,
                requires_approval=adjustment.id in needs_approval,
                created_at=adjustment.created_at,
                submitted_at=adjustment.submitted_at,
                decided_at=adjustment.decided_at,
                posted_at=adjustment.posted_at,
                reversed_at=adjustment.reversed_at,
                reversal_reason=adjustment.reversal_reason,
                line_count=line_counts.get(adjustment.id, 0),
                lines=lines.get(adjustment.id, []) if with_lines else None,
                value_minor=values.get(adjustment.id) if with_value else None,
            )
        )
    return views


def _adjustments_needing_approval(
    db: Session, adjustments: Sequence[InventoryAdjustment]
) -> set[uuid.UUID]:
    """The same rule as inventory_adjustments.requires_approval (D8), for a
    whole page of adjustments in two queries."""
    limit = get_inventory_settings(
        db, org_id=adjustments[0].org_id
    ).adjustment_gain_approval_limit_minor
    removes: set[uuid.UUID] = set()
    gained: dict[uuid.UUID, int] = {}
    for adjustment_id, quantity, cost in db.execute(
        select(
            InventoryAdjustmentLine.adjustment_id,
            InventoryAdjustmentLine.quantity,
            InventoryAdjustmentLine.unit_cost_minor,
        ).where(InventoryAdjustmentLine.adjustment_id.in_([a.id for a in adjustments]))
    ).tuples():
        if quantity < 0:
            removes.add(adjustment_id)
        elif cost is not None:
            gained[adjustment_id] = gained.get(adjustment_id, 0) + increase_value(quantity, cost)
    if limit is None:
        return removes
    return removes | {adjustment_id for adjustment_id, value in gained.items() if value >= limit}


def _adjustment_lines(
    db: Session, adjustment_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[AdjustmentLineOut]]:
    rows = db.execute(
        select(InventoryAdjustmentLine, InventoryItem, InventoryUnit)
        .join(InventoryItem, InventoryItem.id == InventoryAdjustmentLine.item_id)
        .join(InventoryUnit, InventoryUnit.id == InventoryAdjustmentLine.unit_id)
        .where(InventoryAdjustmentLine.adjustment_id.in_(adjustment_ids))
        .order_by(InventoryAdjustmentLine.adjustment_id, InventoryAdjustmentLine.line_no)
    ).tuples()
    pairs = list(rows)
    factors = {
        (row.item_id, row.unit_id): row.factor_to_base
        for row in db.scalars(
            select(InventoryItemUnit).where(
                InventoryItemUnit.item_id.in_({item.id for _, item, _ in pairs})
            )
        )
    }
    out: dict[uuid.UUID, list[AdjustmentLineOut]] = {}
    for line, item, unit in pairs:
        factor = Decimal(1) if unit.id == item.base_unit_id else factors.get((item.id, unit.id))
        quantity_base: Decimal | None = None
        if factor is not None:
            try:
                quantity_base = to_base_quantity(line.quantity, factor)
            except ValueError:
                quantity_base = None
        out.setdefault(line.adjustment_id, []).append(
            AdjustmentLineOut(
                id=line.id,
                line_no=line.line_no,
                item_id=item.id,
                item_sku=item.sku,
                item_name=item.name,
                unit_id=unit.id,
                unit_code=unit.code,
                quantity=line.quantity,
                quantity_base=quantity_base,
                unit_cost_minor=line.unit_cost_minor,
                notes=line.notes,
                lot_number=line.lot_number,
                expiry_date=line.expiry_date,
            )
        )
    return out


# --- stock on hand ----------------------------------------------------------


def stock_rows(
    db: Session,
    *,
    warehouse_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    q: str | None = None,
    include_zero: bool = False,
    with_value: bool,
) -> list[StockRowOut]:
    query = (
        select(InventoryStockBalance, InventoryItem, InventoryWarehouse, InventoryUnit.code)
        .join(InventoryItem, InventoryItem.id == InventoryStockBalance.item_id)
        .join(InventoryWarehouse, InventoryWarehouse.id == InventoryStockBalance.warehouse_id)
        .join(InventoryUnit, InventoryUnit.id == InventoryItem.base_unit_id)
        .order_by(InventoryItem.sku, InventoryWarehouse.code)
    )
    if warehouse_id is not None:
        query = query.where(InventoryStockBalance.warehouse_id == warehouse_id)
    if item_id is not None:
        query = query.where(InventoryStockBalance.item_id == item_id)
    if category_id is not None:
        query = query.where(InventoryItem.category_id == category_id)
    if q and q.strip():
        pattern = _like(q)
        query = query.where(
            or_(
                InventoryItem.sku.ilike(pattern, escape="\\"),
                InventoryItem.name.ilike(pattern, escape="\\"),
            )
        )
    if not include_zero:
        query = query.where(InventoryStockBalance.quantity_base != 0)
    rows = list(db.execute(query).tuples())
    pools = _pools(db, list({item.id for _, item, _, _ in rows})) if with_value else {}

    out = []
    for balance, item, warehouse, unit_code in rows:
        value: int | None = None
        if with_value:
            pool = pools.get(item.id)
            value = valued_at_average(pool, balance.quantity_base) if pool else 0
        out.append(
            StockRowOut(
                item_id=item.id,
                sku=item.sku,
                item_name=item.name,
                base_unit_code=unit_code,
                warehouse_id=warehouse.id,
                warehouse_code=warehouse.code,
                warehouse_name=warehouse.name,
                quantity=balance.quantity_base,
                reorder_level=item.reorder_level,
                value_minor=value,
            )
        )
    return out


# --- movements --------------------------------------------------------------


_NUMBER_COLUMNS: dict[StockSourceType, tuple[Any, Any]] = {
    StockSourceType.INVENTORY_ADJUSTMENT: (
        InventoryAdjustment.id,
        InventoryAdjustment.adjustment_number,
    ),
    StockSourceType.GOODS_RECEIPT: (InventoryGoodsReceipt.id, InventoryGoodsReceipt.grn_number),
    StockSourceType.STOCK_ISSUE: (InventoryStockIssue.id, InventoryStockIssue.issue_number),
    StockSourceType.STOCK_TRANSFER: (
        InventoryStockTransfer.id,
        InventoryStockTransfer.transfer_number,
    ),
    StockSourceType.STOCKTAKE: (InventoryStocktake.id, InventoryStocktake.stocktake_number),
}


def document_numbers(
    db: Session, sources: set[tuple[StockSourceType, uuid.UUID]]
) -> dict[uuid.UUID, str]:
    """Document number (ADJ-…, GRN-…, ISS-…, TRF-…, STK-…) for each source."""
    numbers: dict[uuid.UUID, str] = {}
    for source_type, (id_column, number_column) in _NUMBER_COLUMNS.items():
        ids = {source_id for kind, source_id in sources if kind == source_type}
        if ids:
            numbers.update(
                db.execute(select(id_column, number_column).where(id_column.in_(ids)))
                .tuples()
                .all()
            )
    return numbers


def _movement_select() -> Select[
    tuple[InventoryStockMovement, InventoryItem, InventoryWarehouse, str]
]:
    return (
        select(InventoryStockMovement, InventoryItem, InventoryWarehouse, InventoryUnit.code)
        .join(InventoryItem, InventoryItem.id == InventoryStockMovement.item_id)
        .join(InventoryWarehouse, InventoryWarehouse.id == InventoryStockMovement.warehouse_id)
        .join(InventoryUnit, InventoryUnit.id == InventoryItem.base_unit_id)
    )


def movement_page(
    db: Session,
    *,
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    movement_type: StockMovementType | None = None,
    source_type: StockSourceType | None = None,
    source_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
    with_value: bool,
) -> MovementPage:
    conditions = []
    if item_id is not None:
        conditions.append(InventoryStockMovement.item_id == item_id)
    if warehouse_id is not None:
        conditions.append(InventoryStockMovement.warehouse_id == warehouse_id)
    if movement_type is not None:
        conditions.append(InventoryStockMovement.movement_type == movement_type)
    if source_type is not None:
        conditions.append(InventoryStockMovement.source_type == source_type)
    if source_id is not None:
        conditions.append(InventoryStockMovement.source_id == source_id)
    if date_from is not None:
        conditions.append(InventoryStockMovement.entry_date >= date_from)
    if date_to is not None:
        conditions.append(InventoryStockMovement.entry_date <= date_to)
    where = and_(True, *conditions)

    total = db.scalar(select(func.count()).select_from(InventoryStockMovement).where(where)) or 0
    rows = list(
        db.execute(
            _movement_select()
            .where(where)
            .order_by(
                InventoryStockMovement.entry_date.desc(),
                InventoryStockMovement.created_at.desc(),
                InventoryStockMovement.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).tuples()
    )
    return MovementPage(items=_movement_views(db, rows, with_value=with_value), total=total)


def _movement_views(
    db: Session,
    rows: Sequence[tuple[InventoryStockMovement, InventoryItem, InventoryWarehouse, str]],
    *,
    with_value: bool,
) -> list[MovementOut]:
    numbers = document_numbers(
        db, {(movement.source_type, movement.source_id) for movement, _, _, _ in rows}
    )
    lots = lot_numbers(db, {movement.lot_id for movement, _, _, _ in rows if movement.lot_id})
    return [
        MovementOut(
            id=movement.id,
            entry_date=movement.entry_date,
            created_at=movement.created_at,
            item_id=item.id,
            sku=item.sku,
            item_name=item.name,
            base_unit_code=unit_code,
            warehouse_id=warehouse.id,
            warehouse_code=warehouse.code,
            movement_type=movement.movement_type,
            quantity=movement.quantity_base,
            value_minor=movement.value_minor if with_value else None,
            unit_cost_minor=movement.unit_cost_minor if with_value else None,
            source_type=movement.source_type,
            source_id=movement.source_id,
            source_number=numbers.get(movement.source_id),
            reversal_of_id=movement.reversal_of_id,
            reason=movement.reason,
            lot_id=movement.lot_id,
            lot_number=lots.get(movement.lot_id) if movement.lot_id else None,
        )
        for movement, item, warehouse, unit_code in rows
    ]


def lot_numbers(db: Session, lot_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not lot_ids:
        return {}
    return dict(
        db.execute(
            select(InventoryLot.id, InventoryLot.lot_number).where(InventoryLot.id.in_(lot_ids))
        )
        .tuples()
        .all()
    )


# --- overview ---------------------------------------------------------------


def inventory_summary(db: Session, *, enabled: bool, with_value: bool) -> InventorySummaryOut:
    on_hand = func.coalesce(InventoryItemCost.quantity_base, 0)
    tracked = (
        select(InventoryItem.id, InventoryItem.reorder_level, on_hand.label("on_hand"))
        .outerjoin(InventoryItemCost, InventoryItemCost.item_id == InventoryItem.id)
        .where(InventoryItem.is_active.is_(True), InventoryItem.item_type.in_(TRACKED_TYPES))
        .subquery()
    )
    tracked_items, out_of_stock, low_stock = db.execute(
        select(
            func.count(),
            func.count().filter(tracked.c.on_hand == 0),
            func.count().filter(
                tracked.c.on_hand > 0,
                tracked.c.reorder_level.is_not(None),
                tracked.c.on_hand <= tracked.c.reorder_level,
            ),
        ).select_from(tracked)
    ).one()
    active_warehouses = db.scalar(
        select(func.count())
        .select_from(InventoryWarehouse)
        .where(InventoryWarehouse.is_active.is_(True), InventoryWarehouse.is_transit.is_(False))
    )
    pending_approvals = sum(
        db.scalar(select(func.count()).select_from(model).where(model.status == status)) or 0
        for model, status in (
            (InventoryAdjustment, InventoryAdjustmentStatus.PENDING_APPROVAL),
            (InventoryPurchaseOrder, PurchaseOrderStatus.PENDING_APPROVAL),
            (InventoryStockIssue, StockIssueStatus.PENDING_APPROVAL),
            (InventoryStockTransfer, StockTransferStatus.PENDING_APPROVAL),
        )
    )
    open_purchase_orders = db.scalar(
        select(func.count())
        .select_from(InventoryPurchaseOrder)
        .where(
            InventoryPurchaseOrder.status.in_(
                (PurchaseOrderStatus.ISSUED, PurchaseOrderStatus.PARTIALLY_RECEIVED)
            )
        )
    )
    transfers_in_transit = db.scalar(
        select(func.count())
        .select_from(InventoryStockTransfer)
        .where(InventoryStockTransfer.status == StockTransferStatus.IN_TRANSIT)
    )
    draft_adjustments = db.scalar(
        select(func.count())
        .select_from(InventoryAdjustment)
        .where(InventoryAdjustment.status == InventoryAdjustmentStatus.DRAFT)
    )
    total_value: int | None = None
    if with_value:
        total_value = int(
            db.scalar(select(func.coalesce(func.sum(InventoryItemCost.value_minor), 0))) or 0
        )
    recent = list(
        db.execute(
            _movement_select()
            .order_by(InventoryStockMovement.created_at.desc(), InventoryStockMovement.id.desc())
            .limit(10)
        ).tuples()
    )
    return InventorySummaryOut(
        enabled=enabled,
        tracked_items=tracked_items,
        out_of_stock=out_of_stock,
        low_stock=low_stock,
        active_warehouses=active_warehouses or 0,
        draft_adjustments=draft_adjustments or 0,
        pending_approvals=pending_approvals,
        open_purchase_orders=open_purchase_orders or 0,
        transfers_in_transit=transfers_in_transit or 0,
        total_value_minor=total_value,
        recent_movements=_movement_views(db, recent, with_value=with_value),
    )
