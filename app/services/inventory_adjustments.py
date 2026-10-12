"""Stock adjustment documents: opening balances, found stock, damage,
expiry, loss, write-offs and corrections.

Lifecycle: draft -> (submit) -> pending_approval -> approved | rejected,
then approved -> posted -> reversed. D8: an adjustment that removes any
stock always needs approval; one that only adds stock needs it when its
value reaches the organisation's limit (no limit set: never). An
adjustment that needs no approval can be posted straight from draft.
Approval runs through the shared approval engine (request type
stock_adjustment).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.domain.inventory.costing import increase_value, round_minor
from app.models.approval import ApprovalRequestType
from app.models.inventory import (
    InventoryAdjustment,
    InventoryAdjustmentLine,
    InventoryAdjustmentReason,
    InventoryAdjustmentStatus,
    InventoryItem,
    InventoryUnit,
    StockMovementType,
    StockSourceType,
)
from app.schemas.inventory import AdjustmentCreate
from app.services import inventory_accounting as accounting
from app.services.inventory import get_inventory_settings
from app.services.inventory_common import (
    DocumentKind,
    clean_reason,
    lock,
    next_document_number,
    open_approval,
    record_decision,
    require_not_future,
    require_operational_warehouse,
    require_status,
    resolve_quantity,
    reversal_plan,
    stamp,
)
from app.services.inventory_posting import PlannedMovement, post_movements
from app.services.posting import today_lagos

# +1: the reason only ever adds stock; -1: only ever removes it; 0: either.
REASON_DIRECTION: dict[InventoryAdjustmentReason, int] = {
    InventoryAdjustmentReason.OPENING_BALANCE: 1,
    InventoryAdjustmentReason.FOUND: 1,
    InventoryAdjustmentReason.DAMAGE: -1,
    InventoryAdjustmentReason.EXPIRY: -1,
    InventoryAdjustmentReason.LOSS: -1,
    InventoryAdjustmentReason.WRITE_OFF: -1,
    InventoryAdjustmentReason.CORRECTION: 0,
}

_S = InventoryAdjustmentStatus


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
    resolved = resolve_quantity(
        db,
        line_no=line_no,
        item_id=item_id,
        unit_id=unit_id,
        quantity=quantity,
        allow_negative=True,
    )
    item, qty = resolved.item, resolved.quantity
    where = f"line {line_no} ({item.sku})"
    direction = REASON_DIRECTION[reason]
    label = reason.value.replace("_", " ")
    if direction > 0 and qty < 0:
        raise ValueError(f"{where}: a {label} adjustment can only add stock")
    if direction < 0 and qty > 0:
        raise ValueError(f"{where}: a {label} adjustment can only remove stock")

    cost: int | None
    if qty > 0:
        cost = (
            unit_cost_minor if unit_cost_minor is not None else _default_cost(item, resolved.factor)
        )
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
        unit=resolved.unit,
        quantity=qty,
        quantity_base=resolved.quantity_base,
        unit_cost_minor=cost,
        notes=notes,
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
    require_operational_warehouse(db, body.warehouse_id)
    require_not_future(body.adjustment_date, "an adjustment")


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


def _stored_lines(db: Session, adjustment_id: uuid.UUID) -> list[InventoryAdjustmentLine]:
    return list(
        db.scalars(
            select(InventoryAdjustmentLine)
            .where(InventoryAdjustmentLine.adjustment_id == adjustment_id)
            .order_by(InventoryAdjustmentLine.line_no)
        )
    )


def _lock_adjustment(db: Session, adjustment_id: uuid.UUID) -> InventoryAdjustment:
    return lock(db, InventoryAdjustment, adjustment_id, "adjustment")


# --- drafts -----------------------------------------------------------------


def create_adjustment(
    db: Session, *, org_id: uuid.UUID, actor_account_id: uuid.UUID | None, body: AdjustmentCreate
) -> InventoryAdjustment:
    _check_header(db, body)
    lines = _resolve_body(db, body)
    adjustment = InventoryAdjustment(
        id=uuid.uuid4(),
        org_id=org_id,
        adjustment_number=next_document_number(db, org_id, DocumentKind.ADJUSTMENT),
        warehouse_id=body.warehouse_id,
        reason=body.reason,
        adjustment_date=body.adjustment_date,
        notes=body.notes,
        status=_S.DRAFT,
        created_by=actor_account_id,
    )
    db.add(adjustment)
    db.flush()
    _write_lines(db, adjustment, lines)
    db.flush()
    return adjustment


def update_adjustment(
    db: Session, adjustment_id: uuid.UUID, body: AdjustmentCreate
) -> InventoryAdjustment:
    """Replaces a draft's header and lines."""
    adjustment = _lock_adjustment(db, adjustment_id)
    require_status(adjustment, adjustment.adjustment_number, _S.DRAFT, action="edited")
    _check_header(db, body)
    lines = _resolve_body(db, body)
    for old in _stored_lines(db, adjustment.id):
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
    """Deletes a draft or a rejected adjustment (its lines go with it).
    Anything approved or posted is kept."""
    adjustment = _lock_adjustment(db, adjustment_id)
    require_status(
        adjustment, adjustment.adjustment_number, _S.DRAFT, _S.REJECTED, action="deleted"
    )
    db.delete(adjustment)
    db.flush()
    return adjustment


# --- approval (D8) ----------------------------------------------------------


def requires_approval(db: Session, adjustment: InventoryAdjustment) -> bool:
    """Any line removing stock needs approval; otherwise the value added is
    compared with the organisation's limit."""
    lines = _stored_lines(db, adjustment.id)
    if any(line.quantity < 0 for line in lines):
        return True
    limit = get_inventory_settings(
        db, org_id=adjustment.org_id
    ).adjustment_gain_approval_limit_minor
    if limit is None:
        return False
    gained = sum(
        increase_value(line.quantity, line.unit_cost_minor)
        for line in lines
        if line.unit_cost_minor is not None
    )
    return gained >= limit


def submit_adjustment(
    db: Session, adjustment_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryAdjustment:
    """Sends a draft for approval. One that needs none is approved at once
    and can then be posted."""
    adjustment = _lock_adjustment(db, adjustment_id)
    require_status(adjustment, adjustment.adjustment_number, _S.DRAFT, action="submitted")
    if not _stored_lines(db, adjustment.id):
        raise ValueError(f"{adjustment.adjustment_number} has no lines")
    stamp(adjustment, "submitted", actor_account_id)
    if requires_approval(db, adjustment):
        adjustment.status = _S.PENDING_APPROVAL
        open_approval(
            db,
            org_id=adjustment.org_id,
            request_type=ApprovalRequestType.STOCK_ADJUSTMENT,
            request_id=adjustment.id,
        )
    else:
        adjustment.status = _S.APPROVED
        stamp(adjustment, "decided", None)
    db.flush()
    return adjustment


def decide_adjustment(
    db: Session,
    adjustment_id: uuid.UUID,
    *,
    claims: TokenClaims,
    approve: bool,
    comment: str | None = None,
) -> InventoryAdjustment:
    adjustment = _lock_adjustment(db, adjustment_id)
    require_status(
        adjustment,
        adjustment.adjustment_number,
        _S.PENDING_APPROVAL,
        action="approved" if approve else "rejected",
    )
    if record_decision(
        db,
        claims=claims,
        request_type=ApprovalRequestType.STOCK_ADJUSTMENT,
        request_id=adjustment.id,
        requester_employee_id=None,
        approve=approve,
        comment=comment,
    ):
        adjustment.status = _S.APPROVED if approve else _S.REJECTED
        stamp(adjustment, "decided", None)
    db.flush()
    return adjustment


# --- posting ----------------------------------------------------------------


def post_adjustment(
    db: Session, adjustment_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryAdjustment:
    adjustment = _lock_adjustment(db, adjustment_id)
    require_status(adjustment, adjustment.adjustment_number, _S.DRAFT, _S.APPROVED, action="posted")
    stored = _stored_lines(db, adjustment.id)
    if not stored:
        raise ValueError(f"{adjustment.adjustment_number} has no lines")
    if adjustment.status == _S.DRAFT and requires_approval(db, adjustment):
        raise ValueError(
            f"{adjustment.adjustment_number} needs approval before it can be posted: "
            "submit it for approval"
        )
    require_operational_warehouse(db, adjustment.warehouse_id)
    require_not_future(adjustment.adjustment_date, "an adjustment")

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
        value: int | None = None
        if resolved.quantity > 0:
            assert resolved.unit_cost_minor is not None
            movement_type = (
                StockMovementType.OPENING_BALANCE
                if adjustment.reason == InventoryAdjustmentReason.OPENING_BALANCE
                else StockMovementType.ADJUSTMENT_GAIN
            )
            value = increase_value(resolved.quantity, resolved.unit_cost_minor)
        else:
            movement_type = StockMovementType.ADJUSTMENT_LOSS
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

    movements = post_movements(
        db,
        org_id=adjustment.org_id,
        entry_date=adjustment.adjustment_date,
        source_type=StockSourceType.INVENTORY_ADJUSTMENT,
        source_id=adjustment.id,
        planned=planned,
        actor_account_id=actor_account_id,
    )
    accounting.post_adjustment_journal(
        db, adjustment=adjustment, movements=movements, actor_account_id=actor_account_id
    )
    adjustment.status = _S.POSTED
    stamp(adjustment, "posted", actor_account_id)
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
    today (see inventory_common.reversal_plan for how they are valued)."""
    reason = clean_reason(reason, "reverse an adjustment")
    adjustment = _lock_adjustment(db, adjustment_id)
    require_status(adjustment, adjustment.adjustment_number, _S.POSTED, action="reversed")
    movements = post_movements(
        db,
        org_id=adjustment.org_id,
        entry_date=today_lagos(),
        source_type=StockSourceType.INVENTORY_ADJUSTMENT,
        source_id=adjustment.id,
        planned=reversal_plan(
            db,
            source_type=StockSourceType.INVENTORY_ADJUSTMENT,
            source_id=adjustment.id,
            reason=reason,
        ),
        actor_account_id=actor_account_id,
    )
    accounting.post_reversal_journal(
        db,
        org_id=adjustment.org_id,
        stock_source=StockSourceType.INVENTORY_ADJUSTMENT,
        source_id=adjustment.id,
        document_number=adjustment.adjustment_number,
        posted_at=adjustment.posted_at,
        reason=reason,
        movements=movements,
        actor_account_id=actor_account_id,
    )
    adjustment.status = _S.REVERSED
    adjustment.reversal_reason = reason
    stamp(adjustment, "reversed", actor_account_id)
    db.flush()
    return adjustment
