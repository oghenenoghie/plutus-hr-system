"""Building blocks shared by every inventory document (adjustments, purchase
orders, goods receipts, issues, transfers): line validation, document
numbering, warehouse rules, the in-transit location, generic reversal and
the approval-engine steps.

Errors follow app.services.inventory: InventoryNotFound -> 404,
InventoryConflict -> 409, PermissionError -> 403, any other ValueError ->
400.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.domain.inventory.quantities import (
    QuantityError,
    normalise,
    require_whole_if_needed,
    to_base_quantity,
)
from app.models.approval import ApprovalInstance, ApprovalRequestType
from app.models.inventory import (
    InventoryItem,
    InventoryItemUnit,
    InventorySettings,
    InventoryStockMovement,
    InventoryUnit,
    InventoryWarehouse,
    StockMovementType,
    StockSourceType,
)
from app.models.inventory_control import InventoryLot
from app.services import approvals
from app.services.inventory import (
    InventoryConflict,
    InventoryNotFound,
    get_item,
    get_unit,
    get_warehouse,
)
from app.services.inventory_posting import PlannedMovement
from app.services.posting import today_lagos

TRANSIT_WAREHOUSE_CODE = "IN-TRANSIT"


# --- lines ------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedQuantity:
    item: InventoryItem
    unit: InventoryUnit
    factor: Decimal  # base units per `unit`
    quantity: Decimal  # in `unit`, normalised to 4 places
    quantity_base: Decimal  # in the item's base unit


def factor_to_base(db: Session, item: InventoryItem, unit: InventoryUnit) -> Decimal | None:
    if unit.id == item.base_unit_id:
        return Decimal(1)
    return db.scalar(
        select(InventoryItemUnit.factor_to_base).where(
            InventoryItemUnit.item_id == item.id, InventoryItemUnit.unit_id == unit.id
        )
    )


def resolve_quantity(
    db: Session,
    *,
    line_no: int,
    item_id: uuid.UUID,
    unit_id: uuid.UUID | None,
    quantity: Decimal,
    tracked_only: bool = True,
    allow_negative: bool = False,
    allow_zero: bool = False,
) -> ResolvedQuantity:
    """Validates one document line: the item exists in this organisation and
    is active (and holds stock, unless `tracked_only` is off), the unit is
    the item's base unit or one of its conversions, and the quantity fits
    NUMERIC(18,4) and the unit's whole-number rule in both units."""
    item = get_item(db, item_id)
    where = f"line {line_no} ({item.sku})"
    if not item.is_active:
        raise ValueError(f"{where}: this item is archived")
    if tracked_only and not item.item_type.is_tracked:
        raise ValueError(
            f"{where}: {item.item_type.value.replace('_', '-')} items don't hold stock"
        )
    unit = get_unit(db, unit_id or item.base_unit_id)
    if not unit.is_active:
        raise ValueError(f"{where}: unit {unit.code} is inactive")
    factor = factor_to_base(db, item, unit)
    if factor is None:
        raise ValueError(f"{where}: {unit.code} is not one of this item's units")
    try:
        qty = normalise(quantity)
        if qty == 0 and not allow_zero:
            raise ValueError(f"{where}: quantity can't be zero")
        if qty < 0 and not allow_negative:
            raise ValueError(f"{where}: quantity must be positive")
        require_whole_if_needed(qty, allows_fraction=unit.allows_fraction, unit_code=unit.code)
        base_qty = to_base_quantity(qty, factor)
        base_unit = unit if unit.id == item.base_unit_id else get_unit(db, item.base_unit_id)
        require_whole_if_needed(
            base_qty, allows_fraction=base_unit.allows_fraction, unit_code=base_unit.code
        )
    except QuantityError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return ResolvedQuantity(
        item=item, unit=unit, factor=factor, quantity=qty, quantity_base=base_qty
    )


# --- lots (D9) --------------------------------------------------------------


@dataclass(frozen=True)
class LotInput:
    """A line's lot fields after validation: both None for an item that
    doesn't track lots, or a loss that lets FEFO choose the lot."""

    lot_number: str | None
    expiry_date: date | None


def find_lot(db: Session, item_id: uuid.UUID, lot_number: str) -> InventoryLot | None:
    return db.scalar(
        select(InventoryLot).where(
            InventoryLot.item_id == item_id, InventoryLot.lot_number == lot_number
        )
    )


def check_lot(
    db: Session,
    *,
    item: InventoryItem,
    lot_number: str | None,
    expiry_date: date | None,
    where: str,
    incoming: bool,
) -> LotInput:
    """Validates a line's lot fields. Stock coming in (a receipt or a gain)
    of a lot-tracked item must say which lot it is, and a new lot of an
    expiry-tracked item needs its expiry date; an existing lot's expiry is
    fixed, so a different date is refused. Stock going out may name a lot
    (it must exist) or leave it to first-expiry-first-out."""
    number = (lot_number or "").strip() or None
    if not item.track_lots:
        if number or expiry_date:
            raise ValueError(f"{where}: this item doesn't track lots")
        return LotInput(None, None)
    if expiry_date is not None and not item.track_expiry:
        raise ValueError(f"{where}: this item doesn't track expiry dates")
    if number is None:
        if incoming:
            raise ValueError(f"{where}: this item tracks lots; enter the lot number")
        if expiry_date is not None:
            raise ValueError(f"{where}: an expiry date needs a lot number")
        return LotInput(None, None)
    if len(number) > 64:
        raise ValueError(f"{where}: lot numbers are at most 64 characters")
    existing = find_lot(db, item.id, number)
    if existing is None:
        if not incoming:
            raise ValueError(f"{where}: there is no lot {number} of {item.sku}")
        if item.track_expiry and expiry_date is None:
            raise ValueError(f"{where}: lot {number} is new; enter its expiry date")
    elif expiry_date is not None and expiry_date != existing.expiry_date:
        held = existing.expiry_date.isoformat() if existing.expiry_date else "no expiry date"
        raise ValueError(f"{where}: lot {number} is already recorded with {held}")
    return LotInput(number, expiry_date)


def resolve_lot(
    db: Session,
    *,
    org_id: uuid.UUID,
    item: InventoryItem,
    lot_number: str | None,
    expiry_date: date | None,
    where: str,
    incoming: bool,
) -> uuid.UUID | None:
    """check_lot again at posting time (another document may have created
    the lot since), then the lot's id, creating a new incoming lot. A
    concurrent first receipt of the same lot is a no-op insert, not a
    duplicate."""
    checked = check_lot(
        db,
        item=item,
        lot_number=lot_number,
        expiry_date=expiry_date,
        where=where,
        incoming=incoming,
    )
    if checked.lot_number is None:
        return None
    db.execute(
        pg_insert(InventoryLot)
        .values(
            id=uuid.uuid4(),
            org_id=org_id,
            item_id=item.id,
            lot_number=checked.lot_number,
            expiry_date=checked.expiry_date,
        )
        .on_conflict_do_nothing(constraint="uq_inventory_lot_number")
    )
    lot = find_lot(db, item.id, checked.lot_number)
    assert lot is not None
    if checked.expiry_date is not None and lot.expiry_date != checked.expiry_date:
        # Lost a race with a receipt that created the lot with another date.
        raise InventoryConflict(f"{where}: lot {lot.lot_number} has a different expiry date")
    return lot.id


def require_not_future(day: date, label: str) -> None:
    if day > today_lagos():
        raise ValueError(f"{label} can't be dated in the future")


# --- numbering --------------------------------------------------------------


class DocumentKind(str, Enum):
    ADJUSTMENT = "adjustment"
    PURCHASE_ORDER = "po"
    GOODS_RECEIPT = "grn"
    ISSUE = "issue"
    TRANSFER = "transfer"
    STOCKTAKE = "stocktake"


_PREFIX = {
    DocumentKind.ADJUSTMENT: "ADJ",
    DocumentKind.PURCHASE_ORDER: "PO",
    DocumentKind.GOODS_RECEIPT: "GRN",
    DocumentKind.ISSUE: "ISS",
    DocumentKind.TRANSFER: "TRF",
    DocumentKind.STOCKTAKE: "STK",
}


def lock_settings(db: Session, org_id: uuid.UUID) -> InventorySettings:
    settings = db.scalar(
        select(InventorySettings)
        .where(InventorySettings.org_id == org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if settings is None or not settings.enabled:
        raise InventoryConflict("inventory is not enabled for this organisation")
    return settings


def next_document_number(db: Session, org_id: uuid.UUID, kind: DocumentKind) -> str:
    """The next number for this kind of document, e.g. PO-000042. Taken
    under a lock on the settings row, so concurrent drafts never share a
    number; a rolled-back draft leaves a gap, which is expected."""
    settings = lock_settings(db, org_id)
    field = f"next_{kind.value}_number"
    number: int = getattr(settings, field)
    setattr(settings, field, number + 1)
    return f"{_PREFIX[kind]}-{number:06d}"


# --- rows -------------------------------------------------------------------


def lock[T](db: Session, model: type[T], row_id: uuid.UUID, label: str) -> T:
    """Loads a document FOR UPDATE (fresh from the database), so a status
    change and the stock it moves happen once even under concurrent
    requests."""
    row = db.scalar(
        select(model)
        .where(model.id == row_id)  # type: ignore[attr-defined]
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise InventoryNotFound(f"{label} not found")
    return row


def require_status(document: Any, number: str, *allowed: Enum, action: str) -> None:
    if document.status not in allowed:
        raise InventoryConflict(f"{number} is {document.status.value}; it can't be {action}")


def stamp(document: Any, prefix: str, actor_account_id: uuid.UUID | None) -> None:
    """Sets `<prefix>_at` (now) and, when the model has it, `<prefix>_by`."""
    setattr(document, f"{prefix}_at", datetime.now(UTC))
    if hasattr(document, f"{prefix}_by"):
        setattr(document, f"{prefix}_by", actor_account_id)


# --- warehouses -------------------------------------------------------------


def require_operational_warehouse(
    db: Session, warehouse_id: uuid.UUID, label: str = "warehouse"
) -> InventoryWarehouse:
    """A warehouse a document can name: in this organisation, active, and
    not the system in-transit location."""
    warehouse = get_warehouse(db, warehouse_id)
    if warehouse.is_transit:
        raise ValueError(f"the {label} can't be the in-transit location")
    if not warehouse.is_active:
        raise ValueError(f"{label} {warehouse.code} is inactive")
    return warehouse


def transit_warehouse(db: Session, org_id: uuid.UUID) -> InventoryWarehouse:
    """The organisation's in-transit location, created on first use. The
    partial unique index makes a concurrent first use a no-op, not a
    duplicate."""
    db.execute(
        pg_insert(InventoryWarehouse)
        .values(
            id=uuid.uuid4(),
            org_id=org_id,
            code=TRANSIT_WAREHOUSE_CODE,
            name="In transit",
            is_active=True,
            is_transit=True,
        )
        .on_conflict_do_nothing(index_elements=["org_id"], index_where=text("is_transit"))
    )
    warehouse = db.scalar(select(InventoryWarehouse).where(InventoryWarehouse.is_transit.is_(True)))
    if warehouse is None:  # pragma: no cover - the insert above guarantees one
        raise InventoryConflict("could not create the in-transit location")
    return warehouse


# --- reversal ---------------------------------------------------------------


def reversal_plan(
    db: Session, *, source_type: StockSourceType, source_id: uuid.UUID, reason: str
) -> list[PlannedMovement]:
    """Compensating movements for every movement a document posted. Stock
    the document took out comes back at the value it left at; stock it put
    in leaves at the current average (any difference is a cost variance,
    posted to the GL in Phase 3). Stock goes back in first, so a reversal
    never fails for a shortage it would itself have refilled."""
    originals = list(
        db.scalars(
            select(InventoryStockMovement)
            .where(
                InventoryStockMovement.source_type == source_type,
                InventoryStockMovement.source_id == source_id,
                InventoryStockMovement.movement_type != StockMovementType.REVERSAL,
            )
            .order_by(InventoryStockMovement.created_at, InventoryStockMovement.id)
        )
    )
    originals.sort(key=lambda m: m.quantity_base > 0)
    return [
        PlannedMovement(
            source_line_id=original.source_line_id,
            item_id=original.item_id,
            warehouse_id=original.warehouse_id,
            quantity_base=-original.quantity_base,
            movement_type=StockMovementType.REVERSAL,
            increase_value_minor=-original.value_minor if original.quantity_base < 0 else None,
            reversal_of_id=original.id,
            reason=reason,
            lot_id=original.lot_id,
        )
        for original in originals
    ]


def clean_reason(reason: str, action: str) -> str:
    cleaned = reason.strip()
    if not cleaned:
        raise ValueError(f"a reason is required to {action}")
    return cleaned


# --- approvals --------------------------------------------------------------


def open_approval(
    db: Session,
    *,
    org_id: uuid.UUID,
    request_type: ApprovalRequestType,
    request_id: uuid.UUID,
    requester_employee_id: uuid.UUID | None = None,
) -> ApprovalInstance:
    return approvals.get_or_create_instance(
        db,
        org_id=org_id,
        request_type=request_type,
        request_id=request_id,
        requester_employee_id=requester_employee_id,
    )


def record_decision(
    db: Session,
    *,
    claims: TokenClaims,
    request_type: ApprovalRequestType,
    request_id: uuid.UUID,
    requester_employee_id: uuid.UUID | None,
    approve: bool,
    comment: str | None,
) -> bool:
    """Records the caller's decision at the current step through the shared
    approval engine (which checks they may decide that step: PermissionError
    otherwise). True when this decision finished the approval: approved at
    the last step, or rejected at any step."""
    _, is_final = approvals.decide(
        db,
        claims=claims,
        request_type=request_type,
        request_id=request_id,
        requester_employee_id=requester_employee_id,
        approve=approve,
        comment=comment.strip() if comment and comment.strip() else None,
    )
    return is_final
