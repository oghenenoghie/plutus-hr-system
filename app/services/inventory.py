"""Inventory settings and master data: categories, units, items (with their
unit conversions) and warehouses.

Services raise:
- InventoryNotFound (router -> 404) for an id that does not resolve in the
  caller's organisation. Every foreign id is loaded through the tenant
  session, so RLS makes another org's row indistinguishable from a missing
  one — that is what stops cross-tenant references (docs §2).
- InventoryConflict (-> 409) for a state conflict (duplicate code, a change
  history forbids).
- ValueError (-> 400) for any other invalid input.
"""

import uuid
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.domain.inventory.quantities import normalise
from app.models.branch import Branch
from app.models.inventory import (
    InventoryAdjustmentLine,
    InventoryCategory,
    InventoryItem,
    InventoryItemCost,
    InventoryItemType,
    InventoryItemUnit,
    InventorySettings,
    InventoryStockBalance,
    InventoryStockMovement,
    InventoryUnit,
    InventoryWarehouse,
)
from app.models.vendor import Vendor
from app.schemas.inventory import CategoryUpdate, ItemUpdate, UnitUpdate, WarehouseUpdate


class InventoryNotFound(LookupError):
    pass


class InventoryConflict(ValueError):
    pass


# Seeded when an organisation first switches inventory on; ordinary rows it
# can rename, deactivate or add to.
DEFAULT_UNITS: tuple[tuple[str, str, bool], ...] = (
    ("PCS", "Pieces", False),
    ("BOX", "Box", False),
    ("KG", "Kilogram", True),
    ("L", "Litre", True),
    ("M", "Metre", True),
)


# --- settings ---------------------------------------------------------------


def get_inventory_settings(db: Session, *, org_id: uuid.UUID) -> InventorySettings:
    """The org's settings row, or an unsaved disabled default."""
    row = db.get(InventorySettings, org_id)
    if row is None:
        return InventorySettings(
            org_id=org_id,
            enabled=False,
            costing_method="weighted_average",
            next_adjustment_number=1,
        )
    return row


def inventory_enabled(db: Session, *, org_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(select(InventorySettings.enabled).where(InventorySettings.org_id == org_id))
    )


def update_inventory_settings(
    db: Session, *, org_id: uuid.UUID, actor_account_id: uuid.UUID | None, enabled: bool
) -> InventorySettings:
    """Switching inventory on seeds the default units (idempotent). Switching
    it off hides the module but keeps every record."""
    row = db.get(InventorySettings, org_id)
    if row is None:
        row = InventorySettings(
            org_id=org_id,
            enabled=False,
            costing_method="weighted_average",
            next_adjustment_number=1,
        )
        db.add(row)
    if enabled:
        _seed_default_units(db, org_id=org_id)
    row.enabled = enabled
    row.updated_by = actor_account_id
    db.flush()
    db.refresh(row)
    return row


def _seed_default_units(db: Session, *, org_id: uuid.UUID) -> None:
    existing = set(db.scalars(select(InventoryUnit.code).where(InventoryUnit.org_id == org_id)))
    for code, name, allows_fraction in DEFAULT_UNITS:
        if code not in existing:
            db.add(
                InventoryUnit(org_id=org_id, code=code, name=name, allows_fraction=allows_fraction)
            )
    db.flush()


# --- lookups ----------------------------------------------------------------


def get_category(db: Session, category_id: uuid.UUID) -> InventoryCategory:
    row = db.get(InventoryCategory, category_id)
    if row is None:
        raise InventoryNotFound("category not found")
    return row


def get_unit(db: Session, unit_id: uuid.UUID) -> InventoryUnit:
    row = db.get(InventoryUnit, unit_id)
    if row is None:
        raise InventoryNotFound("unit not found")
    return row


def get_item(db: Session, item_id: uuid.UUID) -> InventoryItem:
    row = db.get(InventoryItem, item_id)
    if row is None:
        raise InventoryNotFound("item not found")
    return row


def get_warehouse(db: Session, warehouse_id: uuid.UUID) -> InventoryWarehouse:
    row = db.get(InventoryWarehouse, warehouse_id)
    if row is None:
        raise InventoryNotFound("warehouse not found")
    return row


def _clean_code(code: str) -> str:
    cleaned = code.strip().upper()
    if not cleaned:
        raise ValueError("code is required")
    return cleaned


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("name is required")
    return cleaned


# --- categories -------------------------------------------------------------


def create_category(
    db: Session, *, org_id: uuid.UUID, name: str, parent_id: uuid.UUID | None
) -> InventoryCategory:
    name = _clean_name(name)
    if parent_id is not None:
        _require_active_parent(db, parent_id)
    _require_unique_category_name(db, org_id=org_id, name=name)
    category = InventoryCategory(org_id=org_id, name=name, parent_id=parent_id)
    db.add(category)
    db.flush()
    return category


def update_category(
    db: Session, category: InventoryCategory, body: CategoryUpdate
) -> InventoryCategory:
    sent = body.model_fields_set
    if body.name is not None:
        name = _clean_name(body.name)
        if name != category.name:
            _require_unique_category_name(db, org_id=category.org_id, name=name)
        category.name = name
    if "parent_id" in sent:
        if body.parent_id is not None:
            _require_active_parent(db, body.parent_id)
            if _is_self_or_descendant(db, ancestor_id=category.id, candidate_id=body.parent_id):
                raise ValueError("a category cannot be placed under itself or its own subcategory")
        category.parent_id = body.parent_id
    if body.is_active is not None:
        category.is_active = body.is_active
    db.flush()
    return category


def _require_active_parent(db: Session, parent_id: uuid.UUID) -> None:
    parent = get_category(db, parent_id)
    if not parent.is_active:
        raise ValueError("the parent category is inactive")


def _require_unique_category_name(db: Session, *, org_id: uuid.UUID, name: str) -> None:
    taken = db.scalar(
        select(exists().where(InventoryCategory.org_id == org_id, InventoryCategory.name == name))
    )
    if taken:
        raise InventoryConflict(f"a category named {name!r} already exists")


def _is_self_or_descendant(db: Session, *, ancestor_id: uuid.UUID, candidate_id: uuid.UUID) -> bool:
    """Walks up from `candidate_id`; true if it reaches `ancestor_id`."""
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = candidate_id
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        current = db.scalar(
            select(InventoryCategory.parent_id).where(InventoryCategory.id == current)
        )
    return False


# --- units ------------------------------------------------------------------


def create_unit(
    db: Session, *, org_id: uuid.UUID, code: str, name: str, allows_fraction: bool
) -> InventoryUnit:
    code = _clean_code(code)
    taken = db.scalar(
        select(exists().where(InventoryUnit.org_id == org_id, InventoryUnit.code == code))
    )
    if taken:
        raise InventoryConflict(f"a unit with code {code!r} already exists")
    unit = InventoryUnit(
        org_id=org_id, code=code, name=_clean_name(name), allows_fraction=allows_fraction
    )
    db.add(unit)
    db.flush()
    return unit


def update_unit(db: Session, unit: InventoryUnit, body: UnitUpdate) -> InventoryUnit:
    if body.name is not None:
        unit.name = _clean_name(body.name)
    if body.allows_fraction is not None:
        if body.allows_fraction != unit.allows_fraction and _unit_in_use(db, unit.id):
            raise InventoryConflict(
                "this unit is already used by items or adjustments, so whether it allows "
                "fractions can no longer change"
            )
        unit.allows_fraction = body.allows_fraction
    if body.is_active is not None:
        unit.is_active = body.is_active
    db.flush()
    return unit


def _unit_in_use(db: Session, unit_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(select(exists().where(InventoryItem.base_unit_id == unit_id)))
        or db.scalar(select(exists().where(InventoryItemUnit.unit_id == unit_id)))
        or db.scalar(select(exists().where(InventoryAdjustmentLine.unit_id == unit_id)))
    )


# --- items ------------------------------------------------------------------


def create_item(
    db: Session,
    *,
    org_id: uuid.UUID,
    sku: str,
    name: str,
    item_type: InventoryItemType,
    base_unit_id: uuid.UUID,
    description: str | None = None,
    category_id: uuid.UUID | None = None,
    reorder_level: Decimal | None = None,
    max_level: Decimal | None = None,
    default_cost_minor: int | None = None,
    preferred_vendor_id: uuid.UUID | None = None,
    barcode: str | None = None,
) -> InventoryItem:
    sku = sku.strip()
    if not sku:
        raise ValueError("SKU is required")
    taken = db.scalar(
        select(exists().where(InventoryItem.org_id == org_id, InventoryItem.sku == sku))
    )
    if taken:
        raise InventoryConflict(f"an item with SKU {sku!r} already exists")

    item = InventoryItem(
        org_id=org_id,
        sku=sku,
        name=_clean_name(name),
        item_type=item_type,
        description=description,
        barcode=barcode,
        default_cost_minor=default_cost_minor,
    )
    _apply_item_references(
        db,
        item,
        category_id=category_id,
        base_unit_id=base_unit_id,
        preferred_vendor_id=preferred_vendor_id,
    )
    _apply_levels(item, reorder_level=reorder_level, max_level=max_level)
    db.add(item)
    db.flush()
    return item


def update_item(db: Session, item: InventoryItem, body: ItemUpdate) -> InventoryItem:
    """Applies a partial update (only the fields sent). item_type and
    base_unit_id are frozen once the item appears on any adjustment or
    stock movement, because every recorded quantity is in that unit."""
    sent = body.model_fields_set
    if body.sku is not None:
        sku = body.sku.strip()
        if not sku:
            raise ValueError("SKU is required")
        if sku != item.sku:
            taken = db.scalar(
                select(
                    exists().where(InventoryItem.org_id == item.org_id, InventoryItem.sku == sku)
                )
            )
            if taken:
                raise InventoryConflict(f"an item with SKU {sku!r} already exists")
        item.sku = sku
    if body.name is not None:
        item.name = _clean_name(body.name)

    frozen_changes = []
    if body.item_type is not None and body.item_type != item.item_type:
        frozen_changes.append("type")
    if body.base_unit_id is not None and body.base_unit_id != item.base_unit_id:
        frozen_changes.append("base unit")
    if frozen_changes and item_has_history(db, item.id):
        raise InventoryConflict(
            f"this item's {' and '.join(frozen_changes)} can't change: it already has "
            "adjustments or stock movements"
        )
    if body.item_type is not None:
        item.item_type = body.item_type

    changed: set[str] = {
        field
        for field in ("category_id", "base_unit_id", "preferred_vendor_id")
        if field in sent and not (field == "base_unit_id" and body.base_unit_id is None)
    }
    _apply_item_references(
        db,
        item,
        category_id=body.category_id if "category_id" in sent else item.category_id,
        base_unit_id=body.base_unit_id or item.base_unit_id,
        preferred_vendor_id=(
            body.preferred_vendor_id if "preferred_vendor_id" in sent else item.preferred_vendor_id
        ),
        changed=changed,
    )
    if "reorder_level" in sent or "max_level" in sent:
        _apply_levels(
            item,
            reorder_level=body.reorder_level if "reorder_level" in sent else item.reorder_level,
            max_level=body.max_level if "max_level" in sent else item.max_level,
        )
    if "description" in sent:
        item.description = body.description
    if "barcode" in sent:
        item.barcode = body.barcode
    if "default_cost_minor" in sent:
        item.default_cost_minor = body.default_cost_minor
    if body.is_active is not None:
        item.is_active = body.is_active
    db.flush()
    return item


def item_has_history(db: Session, item_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(select(exists().where(InventoryStockMovement.item_id == item_id)))
        or db.scalar(select(exists().where(InventoryAdjustmentLine.item_id == item_id)))
    )


def _apply_item_references(
    db: Session,
    item: InventoryItem,
    *,
    category_id: uuid.UUID | None,
    base_unit_id: uuid.UUID,
    preferred_vendor_id: uuid.UUID | None,
    changed: set[str] | None = None,
) -> None:
    """Resolves each reference through the tenant session. On update only
    the fields actually being changed are re-validated, so deactivating a
    category later doesn't block editing an item's name."""

    def checking(field: str) -> bool:
        return changed is None or field in changed

    if checking("category_id"):
        if category_id is not None and not get_category(db, category_id).is_active:
            raise ValueError("that category is inactive")
        item.category_id = category_id
    if checking("base_unit_id"):
        if not get_unit(db, base_unit_id).is_active:
            raise ValueError("that unit is inactive")
        if item.id is not None and db.scalar(
            select(
                exists().where(
                    InventoryItemUnit.item_id == item.id, InventoryItemUnit.unit_id == base_unit_id
                )
            )
        ):
            raise ValueError("that unit is already one of this item's alternative units")
        item.base_unit_id = base_unit_id
    if checking("preferred_vendor_id"):
        if preferred_vendor_id is not None and db.get(Vendor, preferred_vendor_id) is None:
            raise InventoryNotFound("vendor not found")
        item.preferred_vendor_id = preferred_vendor_id


def _apply_levels(
    item: InventoryItem, *, reorder_level: Decimal | None, max_level: Decimal | None
) -> None:
    reorder = normalise(reorder_level) if reorder_level is not None else None
    maximum = normalise(max_level) if max_level is not None else None
    if reorder is not None and reorder < 0:
        raise ValueError("reorder level cannot be negative")
    if maximum is not None and maximum <= 0:
        raise ValueError("maximum level must be greater than zero")
    if reorder is not None and maximum is not None and maximum < reorder:
        raise ValueError("maximum level cannot be below the reorder level")
    item.reorder_level = reorder
    item.max_level = maximum


def list_item_units(db: Session, item_id: uuid.UUID) -> list[InventoryItemUnit]:
    return list(
        db.scalars(
            select(InventoryItemUnit)
            .where(InventoryItemUnit.item_id == item_id)
            .order_by(InventoryItemUnit.created_at)
        )
    )


def replace_item_units(
    db: Session, item: InventoryItem, conversions: list[tuple[uuid.UUID, Decimal]]
) -> list[InventoryItemUnit]:
    """Replaces the item's alternative units. Changing a factor never
    touches stock already posted: movements store base quantities."""
    seen: set[uuid.UUID] = set()
    for unit_id, factor in conversions:
        if unit_id == item.base_unit_id:
            raise ValueError("the base unit can't also be an alternative unit")
        if unit_id in seen:
            raise ValueError("each alternative unit can appear only once")
        seen.add(unit_id)
        if not get_unit(db, unit_id).is_active:
            raise ValueError("that unit is inactive")
        if factor <= 0:
            raise ValueError("a conversion factor must be greater than zero")
        if factor != factor.quantize(Decimal("0.000001")):
            raise ValueError("a conversion factor can have at most 6 decimal places")

    for existing in list_item_units(db, item.id):
        db.delete(existing)
    db.flush()
    for unit_id, factor in conversions:
        db.add(
            InventoryItemUnit(
                org_id=item.org_id, item_id=item.id, unit_id=unit_id, factor_to_base=factor
            )
        )
    db.flush()
    return list_item_units(db, item.id)


def item_on_hand(db: Session, item_id: uuid.UUID) -> tuple[Decimal, int]:
    """(total quantity, total value) across warehouses, from the cost pool."""
    row = db.get(InventoryItemCost, item_id)
    if row is None:
        return Decimal(0), 0
    return row.quantity_base, row.value_minor


# --- warehouses -------------------------------------------------------------


def create_warehouse(
    db: Session,
    *,
    org_id: uuid.UUID,
    code: str,
    name: str,
    branch_id: uuid.UUID | None = None,
    address: str | None = None,
) -> InventoryWarehouse:
    code = _clean_code(code)
    taken = db.scalar(
        select(exists().where(InventoryWarehouse.org_id == org_id, InventoryWarehouse.code == code))
    )
    if taken:
        raise InventoryConflict(f"a warehouse with code {code!r} already exists")
    if branch_id is not None and db.get(Branch, branch_id) is None:
        raise InventoryNotFound("branch not found")
    warehouse = InventoryWarehouse(
        org_id=org_id, code=code, name=_clean_name(name), branch_id=branch_id, address=address
    )
    db.add(warehouse)
    db.flush()
    return warehouse


def update_warehouse(
    db: Session, warehouse: InventoryWarehouse, body: WarehouseUpdate
) -> InventoryWarehouse:
    sent = body.model_fields_set
    if body.name is not None:
        warehouse.name = _clean_name(body.name)
    if "branch_id" in sent:
        if body.branch_id is not None and db.get(Branch, body.branch_id) is None:
            raise InventoryNotFound("branch not found")
        warehouse.branch_id = body.branch_id
    if "address" in sent:
        warehouse.address = body.address
    if body.is_active is not None:
        if not body.is_active and warehouse.is_active and warehouse_has_stock(db, warehouse.id):
            raise InventoryConflict(
                "this warehouse still holds stock; move or adjust it out before deactivating"
            )
        warehouse.is_active = body.is_active
    db.flush()
    return warehouse


def warehouse_has_stock(db: Session, warehouse_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    InventoryStockBalance.warehouse_id == warehouse_id,
                    InventoryStockBalance.quantity_base > 0,
                )
            )
        )
    )
