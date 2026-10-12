"""Inventory API: settings, master data, stock adjustments, stock on hand
and the movement ledger. Purchase orders, goods receipts, issues and
transfers are in app/api/v1/inventory_operations.py. See
docs/architecture/inventory-integration.md.

Gated by fine-grained permissions rather than roles (§7.1):
inventory.view to read, inventory.manage for settings and master data,
inventory.adjust for adjustments; values and costs are only included for
callers holding inventory.valuation. Every endpoint except settings and the
overview answers 409 until an admin switches the module on.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.inventory_support import (
    ENABLED,
    audit,
    changes,
    require_any_permission,
    run,
    sees_values,
)
from app.core.deps import get_tenant_db, require_permission
from app.core.security import TokenClaims
from app.domain.permissions import Permission
from app.models.inventory import (
    InventoryAdjustment,
    InventoryAdjustmentStatus,
    InventoryCategory,
    InventoryItem,
    InventoryItemType,
    InventoryUnit,
    InventoryWarehouse,
    StockMovementType,
    StockSourceType,
)
from app.schemas.inventory import (
    AdjustmentCreate,
    AdjustmentOut,
    AdjustmentReverse,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    InventorySettingsOut,
    InventorySettingsUpdate,
    InventorySummaryOut,
    ItemCreate,
    ItemOut,
    ItemUnitsReplace,
    ItemUpdate,
    MovementPage,
    StockRowOut,
    UnitCreate,
    UnitOut,
    UnitUpdate,
    WarehouseCreate,
    WarehouseOut,
    WarehouseUpdate,
)
from app.schemas.inventory_documents import DecisionIn
from app.services import inventory as svc
from app.services import inventory_adjustments as posting
from app.services import inventory_queries as queries

router = APIRouter(prefix="/inventory", tags=["inventory"])

_VIEW = require_permission(Permission.INVENTORY_VIEW)
_MANAGE = require_permission(Permission.INVENTORY_MANAGE)
_ADJUST = require_permission(Permission.INVENTORY_ADJUST)
_APPROVE = require_permission(Permission.INVENTORY_APPROVE)
# Requesters (inventory.request) pick items, units and warehouses on their
# stock requests, so these reads are open to them too. Values stay hidden.
_CATALOG = require_any_permission(Permission.INVENTORY_VIEW, Permission.INVENTORY_REQUEST)
_ENABLED = ENABLED
_sees_values = sees_values
_run = run
_audit = audit
_changes = changes


# --- settings and overview --------------------------------------------------


@router.get("/settings", response_model=InventorySettingsOut)
def read_settings(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW)
) -> Any:
    return svc.get_inventory_settings(db, org_id=claims.org_id)


@router.put("/settings", response_model=InventorySettingsOut)
def change_settings(
    body: InventorySettingsUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Any:
    settings = svc.update_inventory_settings(
        db, org_id=claims.org_id, actor_account_id=claims.account_id, body=body
    )
    _audit(
        db, claims, "inventory_settings.update", "inventory_settings", claims.org_id, _changes(body)
    )
    return settings


@router.get("/summary", response_model=InventorySummaryOut)
def read_summary(
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(_sees_values),
) -> InventorySummaryOut:
    return queries.inventory_summary(
        db, enabled=svc.inventory_enabled(db, org_id=claims.org_id), with_value=with_value
    )


# --- categories -------------------------------------------------------------


@router.get("/categories", response_model=list[CategoryOut], dependencies=_ENABLED)
def list_categories(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    include_inactive: bool = False,
) -> list[InventoryCategory]:
    query = select(InventoryCategory).order_by(InventoryCategory.name)
    if not include_inactive:
        query = query.where(InventoryCategory.is_active.is_(True))
    return list(db.scalars(query))


@router.post(
    "/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_ENABLED,
)
def create_category(
    body: CategoryCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> InventoryCategory:
    category = _run(
        lambda: svc.create_category(
            db,
            org_id=claims.org_id,
            name=body.name,
            parent_id=body.parent_id,
            expense_account_code=body.expense_account_code,
        )
    )
    _audit(
        db, claims, "inventory_category.create", "inventory_category", category.id, _changes(body)
    )
    return category


@router.patch("/categories/{category_id}", response_model=CategoryOut, dependencies=_ENABLED)
def update_category(
    category_id: uuid.UUID,
    body: CategoryUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> InventoryCategory:
    category = _run(lambda: svc.update_category(db, svc.get_category(db, category_id), body))
    _audit(
        db, claims, "inventory_category.update", "inventory_category", category.id, _changes(body)
    )
    return category


# --- units ------------------------------------------------------------------


@router.get("/units", response_model=list[UnitOut], dependencies=_ENABLED)
def list_units(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_CATALOG),
    include_inactive: bool = False,
) -> list[InventoryUnit]:
    query = select(InventoryUnit).order_by(InventoryUnit.code)
    if not include_inactive:
        query = query.where(InventoryUnit.is_active.is_(True))
    return list(db.scalars(query))


@router.post(
    "/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED, dependencies=_ENABLED
)
def create_unit(
    body: UnitCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> InventoryUnit:
    unit = _run(
        lambda: svc.create_unit(
            db,
            org_id=claims.org_id,
            code=body.code,
            name=body.name,
            allows_fraction=body.allows_fraction,
        )
    )
    _audit(db, claims, "inventory_unit.create", "inventory_unit", unit.id, _changes(body))
    return unit


@router.patch("/units/{unit_id}", response_model=UnitOut, dependencies=_ENABLED)
def update_unit(
    unit_id: uuid.UUID,
    body: UnitUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> InventoryUnit:
    unit = _run(lambda: svc.update_unit(db, svc.get_unit(db, unit_id), body))
    _audit(db, claims, "inventory_unit.update", "inventory_unit", unit.id, _changes(body))
    return unit


# --- items ------------------------------------------------------------------


def _item_view(db: Session, item: InventoryItem, with_value: bool) -> ItemOut:
    return queries.item_views(db, [item], with_value=with_value)[0]


@router.get("/items", response_model=list[ItemOut], dependencies=_ENABLED)
def list_items(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_CATALOG),
    with_value: bool = Depends(_sees_values),
    q: str | None = Query(default=None, max_length=100),
    category_id: uuid.UUID | None = None,
    item_type: InventoryItemType | None = None,
    include_inactive: bool = False,
) -> list[ItemOut]:
    items = queries.list_items(
        db, q=q, category_id=category_id, item_type=item_type, include_inactive=include_inactive
    )
    return queries.item_views(db, items, with_value=with_value)


@router.post(
    "/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED, dependencies=_ENABLED
)
def create_item(
    body: ItemCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
    with_value: bool = Depends(_sees_values),
) -> ItemOut:
    item = _run(lambda: svc.create_item(db, org_id=claims.org_id, **body.model_dump()))
    _audit(db, claims, "inventory_item.create", "inventory_item", item.id, _changes(body))
    return _item_view(db, item, with_value)


@router.get("/items/{item_id}", response_model=ItemOut, dependencies=_ENABLED)
def get_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(_sees_values),
) -> ItemOut:
    return _item_view(db, _run(lambda: svc.get_item(db, item_id)), with_value)


@router.patch("/items/{item_id}", response_model=ItemOut, dependencies=_ENABLED)
def update_item(
    item_id: uuid.UUID,
    body: ItemUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
    with_value: bool = Depends(_sees_values),
) -> ItemOut:
    item = _run(lambda: svc.update_item(db, svc.get_item(db, item_id), body))
    _audit(db, claims, "inventory_item.update", "inventory_item", item.id, _changes(body))
    return _item_view(db, item, with_value)


@router.put("/items/{item_id}/units", response_model=ItemOut, dependencies=_ENABLED)
def replace_item_units(
    item_id: uuid.UUID,
    body: ItemUnitsReplace,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
    with_value: bool = Depends(_sees_values),
) -> ItemOut:
    def action() -> InventoryItem:
        item = svc.get_item(db, item_id)
        svc.replace_item_units(db, item, [(u.unit_id, u.factor_to_base) for u in body.units])
        return item

    item = _run(action)
    _audit(db, claims, "inventory_item.units_replace", "inventory_item", item.id, _changes(body))
    return _item_view(db, item, with_value)


# --- warehouses -------------------------------------------------------------


@router.get("/warehouses", response_model=list[WarehouseOut], dependencies=_ENABLED)
def list_warehouses(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_CATALOG),
    include_inactive: bool = False,
    include_transit: bool = False,
) -> list[InventoryWarehouse]:
    query = select(InventoryWarehouse).order_by(InventoryWarehouse.code)
    if not include_inactive:
        query = query.where(InventoryWarehouse.is_active.is_(True))
    if not include_transit:
        query = query.where(InventoryWarehouse.is_transit.is_(False))
    return list(db.scalars(query))


@router.post(
    "/warehouses",
    response_model=WarehouseOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_ENABLED,
)
def create_warehouse(
    body: WarehouseCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> InventoryWarehouse:
    warehouse = _run(lambda: svc.create_warehouse(db, org_id=claims.org_id, **body.model_dump()))
    _audit(
        db,
        claims,
        "inventory_warehouse.create",
        "inventory_warehouse",
        warehouse.id,
        _changes(body),
    )
    return warehouse


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseOut, dependencies=_ENABLED)
def update_warehouse(
    warehouse_id: uuid.UUID,
    body: WarehouseUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> InventoryWarehouse:
    warehouse = _run(lambda: svc.update_warehouse(db, svc.get_warehouse(db, warehouse_id), body))
    _audit(
        db,
        claims,
        "inventory_warehouse.update",
        "inventory_warehouse",
        warehouse.id,
        _changes(body),
    )
    return warehouse


# --- adjustments ------------------------------------------------------------


def _adjustment_view(
    db: Session, adjustment: InventoryAdjustment, with_value: bool
) -> AdjustmentOut:
    return queries.adjustment_views(db, [adjustment], with_lines=True, with_value=with_value)[0]


def _get_adjustment(db: Session, adjustment_id: uuid.UUID) -> InventoryAdjustment:
    adjustment = db.get(InventoryAdjustment, adjustment_id)
    if adjustment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="adjustment not found")
    return adjustment


@router.get("/adjustments", response_model=list[AdjustmentOut], dependencies=_ENABLED)
def list_adjustments(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(_sees_values),
    status_filter: InventoryAdjustmentStatus | None = Query(default=None, alias="status"),
    warehouse_id: uuid.UUID | None = None,
    limit: int = Query(default=200, gt=0, le=500),
) -> list[AdjustmentOut]:
    adjustments = queries.list_adjustments(
        db, status=status_filter, warehouse_id=warehouse_id, limit=limit
    )
    return queries.adjustment_views(db, adjustments, with_lines=False, with_value=with_value)


@router.post(
    "/adjustments",
    response_model=AdjustmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_ENABLED,
)
def create_adjustment(
    body: AdjustmentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    adjustment = _run(
        lambda: posting.create_adjustment(
            db, org_id=claims.org_id, actor_account_id=claims.account_id, body=body
        )
    )
    _audit(
        db,
        claims,
        "inventory_adjustment.create",
        "inventory_adjustment",
        adjustment.id,
        {"adjustment_number": adjustment.adjustment_number, "lines": len(body.lines)},
    )
    return _adjustment_view(db, adjustment, with_value)


@router.get("/adjustments/{adjustment_id}", response_model=AdjustmentOut, dependencies=_ENABLED)
def get_adjustment(
    adjustment_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    return _adjustment_view(db, _get_adjustment(db, adjustment_id), with_value)


@router.put("/adjustments/{adjustment_id}", response_model=AdjustmentOut, dependencies=_ENABLED)
def update_adjustment(
    adjustment_id: uuid.UUID,
    body: AdjustmentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    adjustment = _run(lambda: posting.update_adjustment(db, adjustment_id, body))
    _audit(
        db,
        claims,
        "inventory_adjustment.update",
        "inventory_adjustment",
        adjustment.id,
        {"adjustment_number": adjustment.adjustment_number, "lines": len(body.lines)},
    )
    return _adjustment_view(db, adjustment, with_value)


@router.delete(
    "/adjustments/{adjustment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_ENABLED,
)
def delete_adjustment(
    adjustment_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
) -> Response:
    adjustment = _run(lambda: posting.delete_adjustment(db, adjustment_id))
    _audit(
        db,
        claims,
        "inventory_adjustment.delete",
        "inventory_adjustment",
        adjustment_id,
        {"adjustment_number": adjustment.adjustment_number},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/adjustments/{adjustment_id}/submit", response_model=AdjustmentOut, dependencies=_ENABLED
)
def submit_adjustment(
    adjustment_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    adjustment = _run(
        lambda: posting.submit_adjustment(db, adjustment_id, actor_account_id=claims.account_id)
    )
    _audit(
        db,
        claims,
        "inventory_adjustment.submit",
        "inventory_adjustment",
        adjustment.id,
        {"adjustment_number": adjustment.adjustment_number, "status": adjustment.status.value},
    )
    return _adjustment_view(db, adjustment, with_value)


def _decide_adjustment(
    db: Session, claims: TokenClaims, adjustment_id: uuid.UUID, body: DecisionIn, approve: bool
) -> InventoryAdjustment:
    adjustment = _run(
        lambda: posting.decide_adjustment(
            db, adjustment_id, claims=claims, approve=approve, comment=body.comment
        )
    )
    _audit(
        db,
        claims,
        "inventory_adjustment.approve" if approve else "inventory_adjustment.reject",
        "inventory_adjustment",
        adjustment.id,
        {
            "adjustment_number": adjustment.adjustment_number,
            "status": adjustment.status.value,
            "comment": body.comment,
        },
    )
    return adjustment


@router.post(
    "/adjustments/{adjustment_id}/approve", response_model=AdjustmentOut, dependencies=_ENABLED
)
def approve_adjustment(
    adjustment_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    adjustment = _decide_adjustment(db, claims, adjustment_id, body, approve=True)
    return _adjustment_view(db, adjustment, with_value)


@router.post(
    "/adjustments/{adjustment_id}/reject", response_model=AdjustmentOut, dependencies=_ENABLED
)
def reject_adjustment(
    adjustment_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    adjustment = _decide_adjustment(db, claims, adjustment_id, body, approve=False)
    return _adjustment_view(db, adjustment, with_value)


@router.post(
    "/adjustments/{adjustment_id}/post", response_model=AdjustmentOut, dependencies=_ENABLED
)
def post_adjustment(
    adjustment_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    adjustment = _run(
        lambda: posting.post_adjustment(db, adjustment_id, actor_account_id=claims.account_id)
    )
    _audit(
        db,
        claims,
        "inventory_adjustment.post",
        "inventory_adjustment",
        adjustment.id,
        {"adjustment_number": adjustment.adjustment_number},
    )
    return _adjustment_view(db, adjustment, with_value)


@router.post(
    "/adjustments/{adjustment_id}/reverse", response_model=AdjustmentOut, dependencies=_ENABLED
)
def reverse_adjustment(
    adjustment_id: uuid.UUID,
    body: AdjustmentReverse,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(_sees_values),
) -> AdjustmentOut:
    adjustment = _run(
        lambda: posting.reverse_adjustment(
            db, adjustment_id, actor_account_id=claims.account_id, reason=body.reason
        )
    )
    _audit(
        db,
        claims,
        "inventory_adjustment.reverse",
        "inventory_adjustment",
        adjustment.id,
        {"adjustment_number": adjustment.adjustment_number, "reason": adjustment.reversal_reason},
    )
    return _adjustment_view(db, adjustment, with_value)


# --- stock and movements ----------------------------------------------------


@router.get("/stock", response_model=list[StockRowOut], dependencies=_ENABLED)
def list_stock(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(_sees_values),
    warehouse_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
    include_zero: bool = False,
) -> list[StockRowOut]:
    return queries.stock_rows(
        db,
        warehouse_id=warehouse_id,
        item_id=item_id,
        category_id=category_id,
        q=q,
        include_zero=include_zero,
        with_value=with_value,
    )


@router.get("/movements", response_model=MovementPage, dependencies=_ENABLED)
def list_movements(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(_sees_values),
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    movement_type: StockMovementType | None = None,
    source_type: StockSourceType | None = None,
    source_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=100, gt=0, le=500),
    offset: int = Query(default=0, ge=0),
) -> MovementPage:
    return queries.movement_page(
        db,
        item_id=item_id,
        warehouse_id=warehouse_id,
        movement_type=movement_type,
        source_type=source_type,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
        with_value=with_value,
    )
