"""Purchase orders and goods receipts (GRNs).

Purchase order: draft -> (submit) -> pending_approval -> approved | rejected;
approved -> (issue) -> issued -> partially_received -> received, as goods
receipts post. An issued or partially received order can be short-closed
(the rest won't come); anything not yet received can be cancelled. An order
never moves stock or posts a journal.

Goods receipt: draft -> posted -> reversed, always against an issued order.
Posting locks the order, so two receipts for the same order run one after
the other: the second sees the first's received quantities, and nothing can
be received twice. Accepted quantities enter stock at the order line's net
price; rejected quantities are recorded only. A receipt may not take a line
past its ordered quantity plus the organisation's over-receipt tolerance
(D4, default 0%).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.domain.inventory.purchasing import (
    line_net_minor,
    max_receivable_base,
    receipt_progress,
    receipt_value_minor,
)
from app.domain.inventory.quantities import QuantityError, normalise, require_whole_if_needed
from app.models.approval import ApprovalRequestType
from app.models.inventory import StockMovementType, StockSourceType
from app.models.inventory_documents import (
    GoodsReceiptStatus,
    InventoryGoodsReceipt,
    InventoryGoodsReceiptLine,
    InventoryPurchaseOrder,
    InventoryPurchaseOrderLine,
    PurchaseOrderStatus,
)
from app.models.vendor import Vendor
from app.schemas.inventory_documents import (
    GoodsReceiptCreate,
    GoodsReceiptUpdate,
    PurchaseOrderCreate,
)
from app.services import inventory_accounting as accounting
from app.services.inventory import (
    InventoryConflict,
    InventoryNotFound,
    get_inventory_settings,
    get_item,
    get_unit,
    owned,
)
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

_PO = PurchaseOrderStatus
_GRN = GoodsReceiptStatus
RECEIVABLE = (_PO.ISSUED, _PO.PARTIALLY_RECEIVED)


# --- purchase orders --------------------------------------------------------


def _lock_po(db: Session, po_id: uuid.UUID) -> InventoryPurchaseOrder:
    return lock(db, InventoryPurchaseOrder, po_id, "purchase order")


def po_lines(db: Session, po_id: uuid.UUID) -> list[InventoryPurchaseOrderLine]:
    return list(
        db.scalars(
            select(InventoryPurchaseOrderLine)
            .where(InventoryPurchaseOrderLine.purchase_order_id == po_id)
            .order_by(InventoryPurchaseOrderLine.line_no)
        )
    )


def _check_po_header(db: Session, org_id: uuid.UUID, body: PurchaseOrderCreate) -> None:
    if owned(db, Vendor, body.vendor_id, org_id) is None:
        raise InventoryNotFound("vendor not found")
    if body.warehouse_id is not None:
        require_operational_warehouse(db, body.warehouse_id, "delivery warehouse")
    if body.expected_date is not None and body.expected_date < body.order_date:
        raise ValueError("the expected delivery date can't be before the order date")


def _write_po_lines(db: Session, po: InventoryPurchaseOrder, body: PurchaseOrderCreate) -> None:
    for line_no, line in enumerate(body.lines, start=1):
        # Any active item can be ordered, including non-stock items and
        # services; only stock and consumables are counted when received.
        resolved = resolve_quantity(
            db,
            line_no=line_no,
            item_id=line.item_id,
            unit_id=line.unit_id,
            quantity=line.quantity,
            tracked_only=False,
        )
        try:
            line_net_minor(resolved.quantity, line.unit_price_minor, line.discount_minor)
        except ValueError as exc:
            raise ValueError(f"line {line_no} ({resolved.item.sku}): {exc}") from exc
        db.add(
            InventoryPurchaseOrderLine(
                org_id=po.org_id,
                purchase_order_id=po.id,
                line_no=line_no,
                item_id=resolved.item.id,
                unit_id=resolved.unit.id,
                quantity=resolved.quantity,
                quantity_base=resolved.quantity_base,
                unit_price_minor=line.unit_price_minor,
                discount_minor=line.discount_minor,
                tax_minor=line.tax_minor,
                received_quantity_base=Decimal(0),
                notes=line.notes,
            )
        )


def create_purchase_order(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_account_id: uuid.UUID | None,
    body: PurchaseOrderCreate,
) -> InventoryPurchaseOrder:
    _check_po_header(db, org_id, body)
    po = InventoryPurchaseOrder(
        id=uuid.uuid4(),
        org_id=org_id,
        po_number=next_document_number(db, org_id, DocumentKind.PURCHASE_ORDER),
        vendor_id=body.vendor_id,
        warehouse_id=body.warehouse_id,
        order_date=body.order_date,
        expected_date=body.expected_date,
        vendor_reference=body.vendor_reference,
        notes=body.notes,
        status=_PO.DRAFT,
        created_by=actor_account_id,
    )
    db.add(po)
    db.flush()
    _write_po_lines(db, po, body)
    db.flush()
    return po


def update_purchase_order(
    db: Session, po_id: uuid.UUID, body: PurchaseOrderCreate
) -> InventoryPurchaseOrder:
    po = _lock_po(db, po_id)
    require_status(po, po.po_number, _PO.DRAFT, action="edited")
    _check_po_header(db, po.org_id, body)
    for old in po_lines(db, po.id):
        db.delete(old)
    db.flush()
    po.vendor_id = body.vendor_id
    po.warehouse_id = body.warehouse_id
    po.order_date = body.order_date
    po.expected_date = body.expected_date
    po.vendor_reference = body.vendor_reference
    po.notes = body.notes
    _write_po_lines(db, po, body)
    db.flush()
    return po


def delete_purchase_order(db: Session, po_id: uuid.UUID) -> InventoryPurchaseOrder:
    """Deletes a draft or rejected order. Anything approved is cancelled
    instead, so its history stays."""
    po = _lock_po(db, po_id)
    require_status(po, po.po_number, _PO.DRAFT, _PO.REJECTED, action="deleted")
    db.delete(po)
    db.flush()
    return po


def submit_purchase_order(
    db: Session, po_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryPurchaseOrder:
    po = _lock_po(db, po_id)
    require_status(po, po.po_number, _PO.DRAFT, action="submitted")
    if not po_lines(db, po.id):
        raise ValueError(f"{po.po_number} has no lines")
    po.status = _PO.PENDING_APPROVAL
    stamp(po, "submitted", actor_account_id)
    open_approval(
        db,
        org_id=po.org_id,
        request_type=ApprovalRequestType.PURCHASE_ORDER,
        request_id=po.id,
    )
    db.flush()
    return po


def decide_purchase_order(
    db: Session,
    po_id: uuid.UUID,
    *,
    claims: TokenClaims,
    approve: bool,
    comment: str | None = None,
) -> InventoryPurchaseOrder:
    po = _lock_po(db, po_id)
    require_status(
        po, po.po_number, _PO.PENDING_APPROVAL, action="approved" if approve else "rejected"
    )
    if record_decision(
        db,
        claims=claims,
        request_type=ApprovalRequestType.PURCHASE_ORDER,
        request_id=po.id,
        requester_employee_id=None,
        approve=approve,
        comment=comment,
    ):
        po.status = _PO.APPROVED if approve else _PO.REJECTED
        stamp(po, "decided", None)
    db.flush()
    return po


def issue_purchase_order(
    db: Session, po_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryPurchaseOrder:
    """Marks an approved order as sent to the vendor; goods can then be
    received against it."""
    po = _lock_po(db, po_id)
    require_status(po, po.po_number, _PO.APPROVED, action="issued to the vendor")
    if owned(db, Vendor, po.vendor_id, po.org_id) is None:
        raise InventoryNotFound("vendor not found")
    po.status = _PO.ISSUED
    stamp(po, "issued", actor_account_id)
    db.flush()
    return po


def _has_draft_receipts(db: Session, po_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    InventoryGoodsReceipt.purchase_order_id == po_id,
                    InventoryGoodsReceipt.status == _GRN.DRAFT,
                )
            )
        )
    )


def cancel_purchase_order(
    db: Session, po_id: uuid.UUID, *, actor_account_id: uuid.UUID | None, reason: str
) -> InventoryPurchaseOrder:
    """Cancels an order nothing has been received against."""
    reason = clean_reason(reason, "cancel an order")
    po = _lock_po(db, po_id)
    require_status(
        po,
        po.po_number,
        _PO.DRAFT,
        _PO.PENDING_APPROVAL,
        _PO.APPROVED,
        _PO.ISSUED,
        action="cancelled",
    )
    if any(line.received_quantity_base > 0 for line in po_lines(db, po.id)):
        raise InventoryConflict(f"{po.po_number} has received goods; close it instead")
    if _has_draft_receipts(db, po.id):
        raise InventoryConflict(f"{po.po_number} has draft goods receipts; delete them first")
    po.status = _PO.CANCELLED
    po.close_reason = reason
    stamp(po, "closed", actor_account_id)
    db.flush()
    return po


def close_purchase_order(
    db: Session, po_id: uuid.UUID, *, actor_account_id: uuid.UUID | None, reason: str
) -> InventoryPurchaseOrder:
    """Short-closes a partially received order: the outstanding quantities
    won't be delivered. Receipts already posted are untouched."""
    reason = clean_reason(reason, "close an order")
    po = _lock_po(db, po_id)
    require_status(po, po.po_number, _PO.PARTIALLY_RECEIVED, action="closed")
    if _has_draft_receipts(db, po.id):
        raise InventoryConflict(f"{po.po_number} has draft goods receipts; delete them first")
    po.status = _PO.CLOSED
    po.close_reason = reason
    stamp(po, "closed", actor_account_id)
    db.flush()
    return po


def _refresh_receipt_status(db: Session, po: InventoryPurchaseOrder) -> None:
    progress = receipt_progress(
        (line.quantity_base, line.received_quantity_base) for line in po_lines(db, po.id)
    )
    po.status = {
        "none": _PO.ISSUED,
        "partial": _PO.PARTIALLY_RECEIVED,
        "full": _PO.RECEIVED,
    }[progress]


# --- goods receipts ---------------------------------------------------------


@dataclass(frozen=True)
class _ReceiptLine:
    po_line: InventoryPurchaseOrderLine
    accepted: Decimal
    rejected: Decimal
    accepted_base: Decimal
    tracked: bool
    base_unit_code: str


def _lock_grn(db: Session, grn_id: uuid.UUID) -> InventoryGoodsReceipt:
    return lock(db, InventoryGoodsReceipt, grn_id, "goods receipt")


def grn_lines(db: Session, grn_id: uuid.UUID) -> list[InventoryGoodsReceiptLine]:
    return list(
        db.scalars(
            select(InventoryGoodsReceiptLine)
            .where(InventoryGoodsReceiptLine.goods_receipt_id == grn_id)
            .order_by(InventoryGoodsReceiptLine.line_no)
        )
    )


def accepted_base(po_line: InventoryPurchaseOrderLine, accepted: Decimal) -> Decimal:
    """`accepted` (in the order line's unit) in base units, at the
    conversion the order was placed with."""
    return normalise(accepted * po_line.quantity_base / po_line.quantity)


def _resolve_receipt_line(
    db: Session,
    po: InventoryPurchaseOrder,
    *,
    line_no: int,
    po_line_id: uuid.UUID,
    accepted: Decimal,
    rejected: Decimal,
) -> _ReceiptLine:
    po_line = db.get(InventoryPurchaseOrderLine, po_line_id)
    if po_line is None or po_line.purchase_order_id != po.id:
        raise InventoryNotFound(f"line {line_no}: that line is not on {po.po_number}")
    item = get_item(db, po_line.item_id)
    unit = get_unit(db, po_line.unit_id)
    where = f"line {line_no} ({item.sku})"
    try:
        accepted_q = normalise(accepted)
        rejected_q = normalise(rejected)
        if accepted_q < 0 or rejected_q < 0:
            raise ValueError(f"{where}: quantities can't be negative")
        if accepted_q + rejected_q == 0:
            raise ValueError(f"{where}: enter an accepted or rejected quantity")
        for qty in (accepted_q, rejected_q):
            require_whole_if_needed(qty, allows_fraction=unit.allows_fraction, unit_code=unit.code)
        base = accepted_base(po_line, accepted_q)
        base_unit = get_unit(db, item.base_unit_id)
        require_whole_if_needed(
            base, allows_fraction=base_unit.allows_fraction, unit_code=base_unit.code
        )
    except QuantityError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return _ReceiptLine(
        po_line=po_line,
        accepted=accepted_q,
        rejected=rejected_q,
        accepted_base=base,
        tracked=item.item_type.is_tracked,
        base_unit_code=base_unit.code,
    )


def _check_receipt_header(
    db: Session, po: InventoryPurchaseOrder, body: GoodsReceiptUpdate
) -> None:
    require_operational_warehouse(db, body.warehouse_id, "receiving warehouse")
    require_not_future(body.receipt_date, "a goods receipt")
    if body.receipt_date < po.order_date:
        raise ValueError("a goods receipt can't be dated before its order")


def _check_receivable(
    po: InventoryPurchaseOrder, lines: list[_ReceiptLine], tolerance_bp: int
) -> None:
    for index, line in enumerate(lines, start=1):
        limit = max_receivable_base(line.po_line.quantity_base, tolerance_bp)
        after = line.po_line.received_quantity_base + line.accepted_base
        if after > limit:
            remaining = max(limit - line.po_line.received_quantity_base, Decimal(0))
            tolerance = " including the over-receipt tolerance" if tolerance_bp else ""
            raise InventoryConflict(
                f"line {index}: that would receive more than {po.po_number} allows on this "
                f"line: {_fmt(remaining)} {line.base_unit_code} left{tolerance}"
            )


def _write_receipt_lines(
    db: Session, grn: InventoryGoodsReceipt, po: InventoryPurchaseOrder, body: GoodsReceiptUpdate
) -> list[_ReceiptLine]:
    seen: set[uuid.UUID] = set()
    resolved: list[_ReceiptLine] = []
    for line_no, line in enumerate(body.lines, start=1):
        if line.po_line_id in seen:
            raise ValueError(f"line {line_no}: each order line can appear only once")
        seen.add(line.po_line_id)
        item_line = _resolve_receipt_line(
            db,
            po,
            line_no=line_no,
            po_line_id=line.po_line_id,
            accepted=line.accepted_quantity,
            rejected=line.rejected_quantity,
        )
        if item_line.rejected > 0 and not (line.rejection_reason or "").strip():
            raise ValueError(f"line {line_no}: give a reason for the rejected quantity")
        resolved.append(item_line)
        db.add(
            InventoryGoodsReceiptLine(
                org_id=grn.org_id,
                goods_receipt_id=grn.id,
                line_no=line_no,
                po_line_id=line.po_line_id,
                accepted_quantity=item_line.accepted,
                rejected_quantity=item_line.rejected,
                rejection_reason=(line.rejection_reason or "").strip() or None,
                notes=line.notes,
            )
        )
    return resolved


def create_goods_receipt(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_account_id: uuid.UUID | None,
    body: GoodsReceiptCreate,
) -> InventoryGoodsReceipt:
    po = db.get(InventoryPurchaseOrder, body.purchase_order_id)
    if po is None:
        raise InventoryNotFound("purchase order not found")
    require_status(po, po.po_number, *RECEIVABLE, action="received against")
    _check_receipt_header(db, po, body)
    grn = InventoryGoodsReceipt(
        id=uuid.uuid4(),
        org_id=org_id,
        grn_number=next_document_number(db, org_id, DocumentKind.GOODS_RECEIPT),
        purchase_order_id=po.id,
        warehouse_id=body.warehouse_id,
        receipt_date=body.receipt_date,
        supplier_reference=body.supplier_reference,
        notes=body.notes,
        status=_GRN.DRAFT,
        created_by=actor_account_id,
    )
    db.add(grn)
    db.flush()
    lines = _write_receipt_lines(db, grn, po, body)
    # Advisory at draft time; enforced again under the order's lock on post.
    _check_receivable(
        po, lines, get_inventory_settings(db, org_id=org_id).over_receipt_tolerance_bp
    )
    db.flush()
    return grn


def update_goods_receipt(
    db: Session, grn_id: uuid.UUID, body: GoodsReceiptUpdate
) -> InventoryGoodsReceipt:
    grn = _lock_grn(db, grn_id)
    require_status(grn, grn.grn_number, _GRN.DRAFT, action="edited")
    po = db.get(InventoryPurchaseOrder, grn.purchase_order_id)
    assert po is not None
    _check_receipt_header(db, po, body)
    for old in grn_lines(db, grn.id):
        db.delete(old)
    db.flush()
    grn.warehouse_id = body.warehouse_id
    grn.receipt_date = body.receipt_date
    grn.supplier_reference = body.supplier_reference
    grn.notes = body.notes
    lines = _write_receipt_lines(db, grn, po, body)
    _check_receivable(
        po, lines, get_inventory_settings(db, org_id=grn.org_id).over_receipt_tolerance_bp
    )
    db.flush()
    return grn


def delete_goods_receipt(db: Session, grn_id: uuid.UUID) -> InventoryGoodsReceipt:
    grn = _lock_grn(db, grn_id)
    require_status(grn, grn.grn_number, _GRN.DRAFT, action="deleted")
    db.delete(grn)
    db.flush()
    return grn


def post_goods_receipt(
    db: Session, grn_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryGoodsReceipt:
    grn = _lock_grn(db, grn_id)
    require_status(grn, grn.grn_number, _GRN.DRAFT, action="posted")
    # The order's lock serialises every receipt against it.
    po = _lock_po(db, grn.purchase_order_id)
    require_status(po, po.po_number, *RECEIVABLE, action="received against")
    require_operational_warehouse(db, grn.warehouse_id, "receiving warehouse")
    require_not_future(grn.receipt_date, "a goods receipt")

    stored = grn_lines(db, grn.id)
    if not stored:
        raise ValueError(f"{grn.grn_number} has no lines")
    # Fresh order lines: another receipt may have just posted.
    lines = [
        _resolve_receipt_line(
            db,
            po,
            line_no=line.line_no,
            po_line_id=line.po_line_id,
            accepted=line.accepted_quantity,
            rejected=line.rejected_quantity,
        )
        for line in stored
    ]
    for line in lines:
        db.refresh(line.po_line)
    _check_receivable(
        po, lines, get_inventory_settings(db, org_id=grn.org_id).over_receipt_tolerance_bp
    )

    planned = [
        PlannedMovement(
            source_line_id=stored_line.id,
            item_id=line.po_line.item_id,
            warehouse_id=grn.warehouse_id,
            quantity_base=line.accepted_base,
            movement_type=StockMovementType.RECEIPT,
            increase_value_minor=receipt_value_minor(
                line.accepted,
                line.po_line.quantity,
                line.po_line.unit_price_minor,
                line.po_line.discount_minor,
            ),
            reason=f"received on {po.po_number}",
        )
        for stored_line, line in zip(stored, lines, strict=True)
        # Non-stock items and services are recorded as received but hold
        # no stock; nothing accepted means nothing to move.
        if line.tracked and line.accepted_base > 0
    ]
    if planned:
        movements = post_movements(
            db,
            org_id=grn.org_id,
            entry_date=grn.receipt_date,
            source_type=StockSourceType.GOODS_RECEIPT,
            source_id=grn.id,
            planned=planned,
            actor_account_id=actor_account_id,
        )
        accounting.post_receipt_journal(
            db,
            org_id=grn.org_id,
            receipt_id=grn.id,
            receipt_number=grn.grn_number,
            order_number=po.po_number,
            entry_date=grn.receipt_date,
            movements=movements,
            actor_account_id=actor_account_id,
        )
    for line in lines:
        line.po_line.received_quantity_base = normalise(
            line.po_line.received_quantity_base + line.accepted_base
        )
    db.flush()
    _refresh_receipt_status(db, po)
    grn.status = _GRN.POSTED
    stamp(grn, "posted", actor_account_id)
    db.flush()
    return grn


def reverse_goods_receipt(
    db: Session, grn_id: uuid.UUID, *, actor_account_id: uuid.UUID | None, reason: str
) -> InventoryGoodsReceipt:
    """Takes a posted receipt's goods back out of stock (at today's average,
    like any removal) and reopens the order's quantities. Refused once the
    received stock has been used, or when the order is closed."""
    reason = clean_reason(reason, "reverse a goods receipt")
    grn = _lock_grn(db, grn_id)
    require_status(grn, grn.grn_number, _GRN.POSTED, action="reversed")
    po = _lock_po(db, grn.purchase_order_id)
    require_status(po, po.po_number, *RECEIVABLE, _PO.RECEIVED, action="changed")
    bill = accounting.receipt_bill(db, receipt_id=grn.id)
    if bill is not None:
        raise InventoryConflict(
            f"{grn.grn_number} is invoiced by bill {bill.bill_number}"
            + (": void the bill first" if bill.status.value == "draft" else "")
        )
    plan = reversal_plan(
        db, source_type=StockSourceType.GOODS_RECEIPT, source_id=grn.id, reason=reason
    )
    if plan:
        movements = post_movements(
            db,
            org_id=grn.org_id,
            entry_date=today_lagos(),
            source_type=StockSourceType.GOODS_RECEIPT,
            source_id=grn.id,
            planned=plan,
            actor_account_id=actor_account_id,
        )
        accounting.post_reversal_journal(
            db,
            org_id=grn.org_id,
            stock_source=StockSourceType.GOODS_RECEIPT,
            source_id=grn.id,
            document_number=grn.grn_number,
            posted_at=grn.posted_at,
            reason=reason,
            movements=movements,
            actor_account_id=actor_account_id,
        )
    for stored in grn_lines(db, grn.id):
        po_line = db.get(InventoryPurchaseOrderLine, stored.po_line_id)
        assert po_line is not None
        db.refresh(po_line)
        po_line.received_quantity_base = normalise(
            po_line.received_quantity_base - accepted_base(po_line, stored.accepted_quantity)
        )
        if po_line.received_quantity_base < 0:
            raise InventoryConflict(f"{po.po_number}: received quantities are inconsistent")
    db.flush()
    _refresh_receipt_status(db, po)
    grn.status = _GRN.REVERSED
    grn.reversal_reason = reason
    stamp(grn, "reversed", actor_account_id)
    db.flush()
    return grn


def _fmt(quantity: Decimal) -> str:
    return format(quantity.normalize(), "f")
