"""Inter-warehouse transfers, with the in-transit step explicit (D5).

Lifecycle: draft -> (submit) -> pending_approval -> approved | rejected;
approved -> (dispatch) -> in_transit -> (receive) -> received; anything not
yet dispatched can be cancelled. With transfer approval switched off (the
default), submitting approves at once and a draft can be dispatched
directly.

Dispatch moves each line out of the source and into the organisation's
in-transit location; receipt moves what arrived out of transit into the
destination, and writes any shortfall off as a transit loss (a reason is
required). Each pair of movements carries the same value, so the move
itself never changes stock value (one average per item, D1); only a
recorded loss does. A dispatched transfer is corrected by a transfer back,
not reversed.
"""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.domain.inventory.quantities import QuantityError, normalise, require_whole_if_needed
from app.models.approval import ApprovalRequestType
from app.models.inventory import InventoryStockMovement, StockMovementType, StockSourceType
from app.models.inventory_control import InventoryLot
from app.models.inventory_documents import (
    InventoryStockTransfer,
    InventoryStockTransferLine,
    StockTransferStatus,
)
from app.schemas.inventory_documents import (
    StockTransferCreate,
    TransferDispatchIn,
    TransferReceiveIn,
)
from app.services import inventory_accounting as accounting
from app.services.inventory import get_inventory_settings, get_item, get_unit
from app.services.inventory_common import (
    DocumentKind,
    lock,
    next_document_number,
    open_approval,
    record_decision,
    require_not_future,
    require_operational_warehouse,
    require_status,
    resolve_quantity,
    stamp,
    transit_warehouse,
)
from app.services.inventory_posting import PlannedMovement, post_movements
from app.services.posting import today_lagos

_S = StockTransferStatus


def _lock_transfer(db: Session, transfer_id: uuid.UUID) -> InventoryStockTransfer:
    return lock(db, InventoryStockTransfer, transfer_id, "transfer")


def transfer_lines(db: Session, transfer_id: uuid.UUID) -> list[InventoryStockTransferLine]:
    return list(
        db.scalars(
            select(InventoryStockTransferLine)
            .where(InventoryStockTransferLine.transfer_id == transfer_id)
            .order_by(InventoryStockTransferLine.line_no)
        )
    )


def _check_header(db: Session, body: StockTransferCreate) -> None:
    if body.from_warehouse_id == body.to_warehouse_id:
        raise ValueError("a transfer needs two different warehouses")
    require_operational_warehouse(db, body.from_warehouse_id, "source warehouse")
    require_operational_warehouse(db, body.to_warehouse_id, "destination warehouse")
    require_not_future(body.transfer_date, "a transfer")


def _write_lines(db: Session, transfer: InventoryStockTransfer, body: StockTransferCreate) -> None:
    for line_no, line in enumerate(body.lines, start=1):
        resolved = resolve_quantity(
            db, line_no=line_no, item_id=line.item_id, unit_id=line.unit_id, quantity=line.quantity
        )
        db.add(
            InventoryStockTransferLine(
                org_id=transfer.org_id,
                transfer_id=transfer.id,
                line_no=line_no,
                item_id=resolved.item.id,
                unit_id=resolved.unit.id,
                quantity=resolved.quantity,
                notes=line.notes,
            )
        )


def create_transfer(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_account_id: uuid.UUID | None,
    body: StockTransferCreate,
) -> InventoryStockTransfer:
    _check_header(db, body)
    transfer = InventoryStockTransfer(
        id=uuid.uuid4(),
        org_id=org_id,
        transfer_number=next_document_number(db, org_id, DocumentKind.TRANSFER),
        from_warehouse_id=body.from_warehouse_id,
        to_warehouse_id=body.to_warehouse_id,
        transfer_date=body.transfer_date,
        notes=body.notes,
        status=_S.DRAFT,
        created_by=actor_account_id,
    )
    db.add(transfer)
    db.flush()
    _write_lines(db, transfer, body)
    db.flush()
    return transfer


def update_transfer(
    db: Session, transfer_id: uuid.UUID, body: StockTransferCreate
) -> InventoryStockTransfer:
    transfer = _lock_transfer(db, transfer_id)
    require_status(transfer, transfer.transfer_number, _S.DRAFT, action="edited")
    _check_header(db, body)
    for old in transfer_lines(db, transfer.id):
        db.delete(old)
    db.flush()
    transfer.from_warehouse_id = body.from_warehouse_id
    transfer.to_warehouse_id = body.to_warehouse_id
    transfer.transfer_date = body.transfer_date
    transfer.notes = body.notes
    _write_lines(db, transfer, body)
    db.flush()
    return transfer


def delete_transfer(db: Session, transfer_id: uuid.UUID) -> InventoryStockTransfer:
    transfer = _lock_transfer(db, transfer_id)
    require_status(transfer, transfer.transfer_number, _S.DRAFT, _S.REJECTED, action="deleted")
    db.delete(transfer)
    db.flush()
    return transfer


def submit_transfer(
    db: Session, transfer_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryStockTransfer:
    transfer = _lock_transfer(db, transfer_id)
    require_status(transfer, transfer.transfer_number, _S.DRAFT, action="submitted")
    if not transfer_lines(db, transfer.id):
        raise ValueError(f"{transfer.transfer_number} has no lines")
    stamp(transfer, "submitted", actor_account_id)
    if get_inventory_settings(db, org_id=transfer.org_id).require_transfer_approval:
        transfer.status = _S.PENDING_APPROVAL
        open_approval(
            db,
            org_id=transfer.org_id,
            request_type=ApprovalRequestType.STOCK_TRANSFER,
            request_id=transfer.id,
        )
    else:
        transfer.status = _S.APPROVED
        stamp(transfer, "decided", None)
    db.flush()
    return transfer


def decide_transfer(
    db: Session,
    transfer_id: uuid.UUID,
    *,
    claims: TokenClaims,
    approve: bool,
    comment: str | None = None,
) -> InventoryStockTransfer:
    transfer = _lock_transfer(db, transfer_id)
    require_status(
        transfer,
        transfer.transfer_number,
        _S.PENDING_APPROVAL,
        action="approved" if approve else "rejected",
    )
    if record_decision(
        db,
        claims=claims,
        request_type=ApprovalRequestType.STOCK_TRANSFER,
        request_id=transfer.id,
        requester_employee_id=None,
        approve=approve,
        comment=comment,
    ):
        transfer.status = _S.APPROVED if approve else _S.REJECTED
        stamp(transfer, "decided", None)
    db.flush()
    return transfer


def cancel_transfer(
    db: Session, transfer_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryStockTransfer:
    transfer = _lock_transfer(db, transfer_id)
    require_status(
        transfer,
        transfer.transfer_number,
        _S.DRAFT,
        _S.PENDING_APPROVAL,
        _S.APPROVED,
        action="cancelled",
    )
    transfer.status = _S.CANCELLED
    stamp(transfer, "cancelled", actor_account_id)
    db.flush()
    return transfer


def _movement_date(day: date | None, transfer: InventoryStockTransfer) -> date:
    when = day or today_lagos()
    require_not_future(when, "a transfer movement")
    if when < transfer.transfer_date:
        raise ValueError("stock can't move before the transfer's date")
    return when


def dispatch_transfer(
    db: Session,
    transfer_id: uuid.UUID,
    *,
    actor_account_id: uuid.UUID | None,
    body: TransferDispatchIn,
) -> InventoryStockTransfer:
    """Sends the stock: out of the source, into transit, at the items'
    current average. Refused if the source hasn't got it."""
    transfer = _lock_transfer(db, transfer_id)
    require_status(transfer, transfer.transfer_number, _S.DRAFT, _S.APPROVED, action="dispatched")
    if (
        transfer.status == _S.DRAFT
        and get_inventory_settings(db, org_id=transfer.org_id).require_transfer_approval
    ):
        raise ValueError(
            f"{transfer.transfer_number} needs approval before it can be dispatched: "
            "submit it for approval"
        )
    require_operational_warehouse(db, transfer.from_warehouse_id, "source warehouse")
    require_operational_warehouse(db, transfer.to_warehouse_id, "destination warehouse")
    entry_date = _movement_date(body.dispatch_date, transfer)
    lines = transfer_lines(db, transfer.id)
    if not lines:
        raise ValueError(f"{transfer.transfer_number} has no lines")
    transit = transit_warehouse(db, transfer.org_id)

    outs = []
    for line in lines:
        resolved = resolve_quantity(
            db,
            line_no=line.line_no,
            item_id=line.item_id,
            unit_id=line.unit_id,
            quantity=line.quantity,
        )
        line.dispatched_quantity_base = resolved.quantity_base
        outs.append(
            PlannedMovement(
                source_line_id=line.id,
                item_id=line.item_id,
                warehouse_id=transfer.from_warehouse_id,
                quantity_base=-resolved.quantity_base,
                movement_type=StockMovementType.TRANSFER_OUT,
                reason=f"dispatched on {transfer.transfer_number}",
                # Lot-tracked stock leaves first-expiry-first-out; expired
                # lots stay behind to be written off (D9).
                skip_expired=True,
            )
        )
    _move_pairs(
        db,
        transfer,
        outs,
        destination_id=transit.id,
        entry_date=entry_date,
        actor_account_id=actor_account_id,
    )
    transfer.status = _S.IN_TRANSIT
    stamp(transfer, "dispatched", actor_account_id)
    db.flush()
    return transfer


def receive_transfer(
    db: Session,
    transfer_id: uuid.UUID,
    *,
    actor_account_id: uuid.UUID | None,
    body: TransferReceiveIn,
) -> InventoryStockTransfer:
    """Books what arrived into the destination. Every line must be
    accounted for; a line received short has the difference written off
    from transit as a loss, with the reason given."""
    transfer = _lock_transfer(db, transfer_id)
    require_status(transfer, transfer.transfer_number, _S.IN_TRANSIT, action="received")
    require_operational_warehouse(db, transfer.to_warehouse_id, "destination warehouse")
    entry_date = _movement_date(body.receipt_date, transfer)
    lines = {line.id: line for line in transfer_lines(db, transfer.id)}
    given = {entry.line_id: entry.received_quantity_base for entry in body.lines}
    if len(given) != len(body.lines):
        raise ValueError("each transfer line can appear only once")
    if set(given) != set(lines):
        raise ValueError("enter the quantity received for every line of the transfer")
    transit = transit_warehouse(db, transfer.org_id)

    outs: list[PlannedMovement] = []
    losses: list[PlannedMovement] = []
    for line_id, line in sorted(lines.items(), key=lambda pair: pair[1].line_no):
        dispatched = line.dispatched_quantity_base
        assert dispatched is not None
        received = _received_base(db, line, given[line_id])
        if received > dispatched:
            raise ValueError(f"line {line.line_no}: more received than was dispatched")
        line.received_quantity_base = received
        # Take out of transit exactly the lots this line put in, earliest
        # expiry first: what arrived first, what's missing from the rest.
        remaining = received
        for lot_id, quantity in _dispatched_lots(db, transfer, line, transit.id):
            arrived = min(quantity, remaining)
            remaining -= arrived
            if arrived > 0:
                outs.append(
                    PlannedMovement(
                        source_line_id=line.id,
                        item_id=line.item_id,
                        warehouse_id=transit.id,
                        quantity_base=-arrived,
                        movement_type=StockMovementType.TRANSFER_OUT,
                        reason=f"received on {transfer.transfer_number}",
                        lot_id=lot_id,
                    )
                )
            if quantity > arrived:
                losses.append(
                    PlannedMovement(
                        source_line_id=line.id,
                        item_id=line.item_id,
                        warehouse_id=transit.id,
                        quantity_base=-(quantity - arrived),
                        movement_type=StockMovementType.ADJUSTMENT_LOSS,
                        lot_id=lot_id,
                    )
                )
    if losses:
        reason = (body.discrepancy_reason or "").strip()
        if not reason:
            raise ValueError("less arrived than was sent: give a reason for the shortfall")
        transfer.discrepancy_reason = reason
        losses = [replace(loss, reason=f"transit loss: {reason}") for loss in losses]
        lost = post_movements(
            db,
            org_id=transfer.org_id,
            entry_date=entry_date,
            source_type=StockSourceType.STOCK_TRANSFER,
            source_id=transfer.id,
            planned=losses,
            actor_account_id=actor_account_id,
        )
        accounting.post_transfer_journal(
            db,
            org_id=transfer.org_id,
            transfer_id=transfer.id,
            transfer_number=transfer.transfer_number,
            source_event="transit_loss",
            entry_date=entry_date,
            movements=lost,
            actor_account_id=actor_account_id,
        )
    if outs:
        _move_pairs(
            db,
            transfer,
            outs,
            destination_id=transfer.to_warehouse_id,
            entry_date=entry_date,
            actor_account_id=actor_account_id,
        )
    transfer.status = _S.RECEIVED
    stamp(transfer, "received", actor_account_id)
    db.flush()
    return transfer


def _dispatched_lots(
    db: Session,
    transfer: InventoryStockTransfer,
    line: InventoryStockTransferLine,
    transit_id: uuid.UUID,
) -> list[tuple[uuid.UUID | None, Decimal]]:
    """(lot, quantity) this line put into transit, earliest expiry first. A
    line of an item without lots is one (None, quantity) pair."""
    rows = db.execute(
        select(InventoryStockMovement.lot_id, InventoryStockMovement.quantity_base)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryStockMovement.lot_id)
        .where(
            InventoryStockMovement.source_type == StockSourceType.STOCK_TRANSFER,
            InventoryStockMovement.source_id == transfer.id,
            InventoryStockMovement.source_line_id == line.id,
            InventoryStockMovement.movement_type == StockMovementType.TRANSFER_IN,
            InventoryStockMovement.warehouse_id == transit_id,
        )
        .order_by(
            InventoryLot.expiry_date.asc().nulls_last(),
            InventoryLot.created_at,
            InventoryStockMovement.created_at,
        )
    ).all()
    return [(lot_id, quantity) for lot_id, quantity in rows]


def _received_base(db: Session, line: InventoryStockTransferLine, quantity: Decimal) -> Decimal:
    item = get_item(db, line.item_id)
    unit = get_unit(db, item.base_unit_id)
    try:
        received = normalise(quantity)
        if received < 0:
            raise ValueError(f"line {line.line_no}: quantity can't be negative")
        require_whole_if_needed(received, allows_fraction=unit.allows_fraction, unit_code=unit.code)
    except QuantityError as exc:
        raise ValueError(f"line {line.line_no} ({item.sku}): {exc}") from exc
    return received


def _move_pairs(
    db: Session,
    transfer: InventoryStockTransfer,
    outs: list[PlannedMovement],
    *,
    destination_id: uuid.UUID,
    entry_date: date,
    actor_account_id: uuid.UUID | None,
) -> None:
    """Posts the outgoing movements, then the matching incoming ones at
    exactly the value that went out, so the pair is value-neutral."""
    posted = post_movements(
        db,
        org_id=transfer.org_id,
        entry_date=entry_date,
        source_type=StockSourceType.STOCK_TRANSFER,
        source_id=transfer.id,
        planned=outs,
        actor_account_id=actor_account_id,
    )
    post_movements(
        db,
        org_id=transfer.org_id,
        entry_date=entry_date,
        source_type=StockSourceType.STOCK_TRANSFER,
        source_id=transfer.id,
        planned=[
            PlannedMovement(
                source_line_id=out.source_line_id,
                item_id=out.item_id,
                warehouse_id=destination_id,
                quantity_base=-out.quantity_base,
                movement_type=StockMovementType.TRANSFER_IN,
                increase_value_minor=-out.value_minor,
                reason=out.reason,
                lot_id=out.lot_id,
            )
            for out in posted
        ],
        actor_account_id=actor_account_id,
    )
