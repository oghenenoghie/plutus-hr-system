"""Read models for purchase orders, goods receipts, stock issues and
transfers. Lists are built with a fixed number of queries per page."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.domain.inventory.accounting import GRNI_ACCOUNT
from app.domain.inventory.purchasing import line_net_minor
from app.domain.inventory.quantities import QuantityError, to_base_quantity
from app.models.bill import Bill, BillStatus
from app.models.department import Department
from app.models.employee import Employee
from app.models.inventory import (
    InventoryItem,
    InventoryItemUnit,
    InventoryStockMovement,
    InventoryUnit,
    InventoryWarehouse,
    StockMovementType,
    StockSourceType,
)
from app.models.inventory_documents import (
    GoodsReceiptStatus,
    InventoryGoodsReceipt,
    InventoryGoodsReceiptLine,
    InventoryPurchaseOrder,
    InventoryPurchaseOrderLine,
    InventoryStockIssue,
    InventoryStockIssueLine,
    InventoryStockTransfer,
    InventoryStockTransferLine,
    PurchaseOrderStatus,
    StockIssueStatus,
    StockTransferStatus,
)
from app.models.journal_entry import JournalEntry, JournalSourceType
from app.models.ledger import LedgerEntry
from app.models.vendor import Vendor
from app.schemas.inventory_documents import (
    GoodsReceiptBrief,
    GoodsReceiptLineOut,
    GoodsReceiptOut,
    PurchaseOrderLineOut,
    PurchaseOrderOut,
    StockIssueOut,
    StockLineOut,
    StockTransferLineOut,
    StockTransferOut,
)
from app.services.inventory_issues import IssueScope
from app.services.inventory_purchasing import accepted_base


def _by_id[M](db: Session, model: type[M], ids: set[uuid.UUID]) -> dict[uuid.UUID, M]:
    if not ids:
        return {}
    return {
        row.id: row  # type: ignore[attr-defined]
        for row in db.scalars(select(model).where(model.id.in_(ids)))  # type: ignore[attr-defined]
    }


def _org_rows[M](
    db: Session, model: type[M], ids: set[uuid.UUID], org_id: uuid.UUID
) -> dict[uuid.UUID, M]:
    """Rows of a non-inventory table, checked against the org (they aren't
    OrgScoped; see app.services.inventory.owned)."""
    if not ids:
        return {}
    return {
        row.id: row  # type: ignore[attr-defined]
        for row in db.scalars(
            select(model).where(
                model.id.in_(ids),  # type: ignore[attr-defined]
                model.org_id == org_id,  # type: ignore[attr-defined]
            )
        )
    }


def _units(db: Session) -> dict[uuid.UUID, InventoryUnit]:
    return {unit.id: unit for unit in db.scalars(select(InventoryUnit))}


def _counts(
    db: Session, column: InstrumentedAttribute[uuid.UUID], ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    return dict(
        db.execute(select(column, func.count()).where(column.in_(ids)).group_by(column))
        .tuples()
        .all()
    )


def _posted_values(
    db: Session, source_type: StockSourceType, ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Value each document moved (its own movements, before any reversal)."""
    if not ids:
        return {}
    return {
        source_id: int(total)
        for source_id, total in db.execute(
            select(InventoryStockMovement.source_id, func.sum(InventoryStockMovement.value_minor))
            .where(
                InventoryStockMovement.source_type == source_type,
                InventoryStockMovement.source_id.in_(ids),
                InventoryStockMovement.movement_type != StockMovementType.REVERSAL,
            )
            .group_by(InventoryStockMovement.source_id)
        ).tuples()
    }


# --- purchase orders --------------------------------------------------------


def list_purchase_orders(
    db: Session,
    *,
    status: PurchaseOrderStatus | None = None,
    vendor_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[InventoryPurchaseOrder]:
    query: Select[tuple[InventoryPurchaseOrder]] = (
        select(InventoryPurchaseOrder)
        .order_by(
            InventoryPurchaseOrder.order_date.desc(), InventoryPurchaseOrder.created_at.desc()
        )
        .limit(limit)
    )
    if status is not None:
        query = query.where(InventoryPurchaseOrder.status == status)
    if vendor_id is not None:
        query = query.where(InventoryPurchaseOrder.vendor_id == vendor_id)
    return list(db.scalars(query))


def purchase_order_views(
    db: Session, orders: Sequence[InventoryPurchaseOrder], *, with_lines: bool
) -> list[PurchaseOrderOut]:
    if not orders:
        return []
    ids = [order.id for order in orders]
    org_id = orders[0].org_id
    vendors = _org_rows(db, Vendor, {o.vendor_id for o in orders}, org_id)
    warehouses = _by_id(db, InventoryWarehouse, {o.warehouse_id for o in orders if o.warehouse_id})
    lines = list(
        db.scalars(
            select(InventoryPurchaseOrderLine)
            .where(InventoryPurchaseOrderLine.purchase_order_id.in_(ids))
            .order_by(InventoryPurchaseOrderLine.line_no)
        )
    )
    items = _by_id(db, InventoryItem, {line.item_id for line in lines})
    units = _units(db)
    by_order: dict[uuid.UUID, list[PurchaseOrderLineOut]] = {}
    for line in lines:
        item = items[line.item_id]
        net = line_net_minor(line.quantity, line.unit_price_minor, line.discount_minor)
        by_order.setdefault(line.purchase_order_id, []).append(
            PurchaseOrderLineOut(
                id=line.id,
                line_no=line.line_no,
                item_id=item.id,
                item_sku=item.sku,
                item_name=item.name,
                item_type=item.item_type,
                unit_id=line.unit_id,
                unit_code=units[line.unit_id].code,
                base_unit_code=units[item.base_unit_id].code,
                quantity=line.quantity,
                quantity_base=line.quantity_base,
                unit_price_minor=line.unit_price_minor,
                discount_minor=line.discount_minor,
                tax_minor=line.tax_minor,
                net_minor=net,
                total_minor=net + line.tax_minor,
                received_quantity_base=line.received_quantity_base,
                outstanding_quantity_base=max(
                    line.quantity_base - line.received_quantity_base, Decimal(0)
                ),
                notes=line.notes,
            )
        )
    receipts: dict[uuid.UUID, list[GoodsReceiptBrief]] = {}
    if with_lines:
        grns = list(
            db.scalars(
                select(InventoryGoodsReceipt)
                .where(InventoryGoodsReceipt.purchase_order_id.in_(ids))
                .order_by(InventoryGoodsReceipt.receipt_date, InventoryGoodsReceipt.created_at)
            )
        )
        grn_warehouses = _by_id(db, InventoryWarehouse, {g.warehouse_id for g in grns})
        for grn in grns:
            receipts.setdefault(grn.purchase_order_id, []).append(
                GoodsReceiptBrief(
                    id=grn.id,
                    grn_number=grn.grn_number,
                    receipt_date=grn.receipt_date,
                    status=grn.status,
                    warehouse_code=grn_warehouses[grn.warehouse_id].code,
                )
            )

    views = []
    for order in orders:
        order_lines = by_order.get(order.id, [])
        subtotal = sum(line.net_minor for line in order_lines)
        tax = sum(line.tax_minor for line in order_lines)
        warehouse = warehouses.get(order.warehouse_id) if order.warehouse_id else None
        vendor = vendors.get(order.vendor_id)
        views.append(
            PurchaseOrderOut(
                id=order.id,
                po_number=order.po_number,
                vendor_id=order.vendor_id,
                vendor_name=vendor.name if vendor else "—",
                warehouse_id=order.warehouse_id,
                warehouse_code=warehouse.code if warehouse else None,
                order_date=order.order_date,
                expected_date=order.expected_date,
                vendor_reference=order.vendor_reference,
                notes=order.notes,
                status=order.status,
                created_at=order.created_at,
                submitted_at=order.submitted_at,
                decided_at=order.decided_at,
                issued_at=order.issued_at,
                closed_at=order.closed_at,
                close_reason=order.close_reason,
                line_count=len(order_lines),
                subtotal_minor=subtotal,
                tax_minor=tax,
                total_minor=subtotal + tax,
                lines=order_lines if with_lines else None,
                receipts=receipts.get(order.id, []) if with_lines else None,
            )
        )
    return views


# --- goods receipts ---------------------------------------------------------


def list_goods_receipts(
    db: Session,
    *,
    status: GoodsReceiptStatus | None = None,
    purchase_order_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    unbilled: bool = False,
    limit: int = 200,
) -> list[InventoryGoodsReceipt]:
    """`unbilled` keeps posted receipts that no bill (other than a void one)
    invoices yet: the ones a new bill can be linked to."""
    query: Select[tuple[InventoryGoodsReceipt]] = (
        select(InventoryGoodsReceipt)
        .order_by(
            InventoryGoodsReceipt.receipt_date.desc(), InventoryGoodsReceipt.created_at.desc()
        )
        .limit(limit)
    )
    if status is not None:
        query = query.where(InventoryGoodsReceipt.status == status)
    if purchase_order_id is not None:
        query = query.where(InventoryGoodsReceipt.purchase_order_id == purchase_order_id)
    if vendor_id is not None:
        query = query.where(
            InventoryGoodsReceipt.purchase_order_id.in_(
                select(InventoryPurchaseOrder.id).where(
                    InventoryPurchaseOrder.vendor_id == vendor_id
                )
            )
        )
    if unbilled:
        query = query.where(
            InventoryGoodsReceipt.status == GoodsReceiptStatus.POSTED,
            ~select(Bill.id)
            .where(
                Bill.goods_receipt_id == InventoryGoodsReceipt.id, Bill.status != BillStatus.VOID
            )
            .exists(),
        )
    return list(db.scalars(query))


def _receipt_accruals(db: Session, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Per receipt, what its posting journal credited to
    goods-received-not-invoiced."""
    rows = db.execute(
        select(
            JournalEntry.source_id,
            func.sum(LedgerEntry.credit_minor - LedgerEntry.debit_minor),
        )
        .join(LedgerEntry, LedgerEntry.journal_entry_id == JournalEntry.id)
        .where(
            JournalEntry.source_type == JournalSourceType.GOODS_RECEIPT,
            JournalEntry.source_event == "posted",
            JournalEntry.source_id.in_(ids),
            LedgerEntry.account == GRNI_ACCOUNT,
        )
        .group_by(JournalEntry.source_id)
    ).all()
    return {source_id: int(total) for source_id, total in rows if source_id is not None}


def goods_receipt_views(
    db: Session,
    receipts: Sequence[InventoryGoodsReceipt],
    *,
    with_lines: bool,
    with_value: bool,
) -> list[GoodsReceiptOut]:
    if not receipts:
        return []
    ids = [grn.id for grn in receipts]
    org_id = receipts[0].org_id
    orders = _by_id(db, InventoryPurchaseOrder, {g.purchase_order_id for g in receipts})
    vendors = _org_rows(db, Vendor, {o.vendor_id for o in orders.values()}, org_id)
    warehouses = _by_id(db, InventoryWarehouse, {g.warehouse_id for g in receipts})
    counts = _counts(db, InventoryGoodsReceiptLine.goods_receipt_id, ids)
    values = _posted_values(db, StockSourceType.GOODS_RECEIPT, ids) if with_value else {}
    accruals = _receipt_accruals(db, ids) if with_value else {}
    bills = {
        bill.goods_receipt_id: bill
        for bill in db.scalars(
            select(Bill).where(Bill.goods_receipt_id.in_(ids), Bill.status != BillStatus.VOID)
        )
    }

    lines: dict[uuid.UUID, list[GoodsReceiptLineOut]] = {}
    if with_lines:
        stored = list(
            db.scalars(
                select(InventoryGoodsReceiptLine)
                .where(InventoryGoodsReceiptLine.goods_receipt_id.in_(ids))
                .order_by(InventoryGoodsReceiptLine.line_no)
            )
        )
        po_lines = _by_id(db, InventoryPurchaseOrderLine, {line.po_line_id for line in stored})
        items = _by_id(db, InventoryItem, {line.item_id for line in po_lines.values()})
        units = _units(db)
        for line in stored:
            po_line = po_lines[line.po_line_id]
            item = items[po_line.item_id]
            lines.setdefault(line.goods_receipt_id, []).append(
                GoodsReceiptLineOut(
                    id=line.id,
                    line_no=line.line_no,
                    po_line_id=po_line.id,
                    item_id=item.id,
                    item_sku=item.sku,
                    item_name=item.name,
                    unit_code=units[po_line.unit_id].code,
                    base_unit_code=units[item.base_unit_id].code,
                    accepted_quantity=line.accepted_quantity,
                    rejected_quantity=line.rejected_quantity,
                    accepted_quantity_base=accepted_base(po_line, line.accepted_quantity),
                    rejection_reason=line.rejection_reason,
                    notes=line.notes,
                    lot_number=line.lot_number,
                    expiry_date=line.expiry_date,
                )
            )

    views = []
    for grn in receipts:
        order = orders[grn.purchase_order_id]
        vendor = vendors.get(order.vendor_id)
        warehouse = warehouses[grn.warehouse_id]
        views.append(
            GoodsReceiptOut(
                id=grn.id,
                grn_number=grn.grn_number,
                purchase_order_id=order.id,
                po_number=order.po_number,
                vendor_name=vendor.name if vendor else "—",
                warehouse_id=warehouse.id,
                warehouse_code=warehouse.code,
                warehouse_name=warehouse.name,
                receipt_date=grn.receipt_date,
                supplier_reference=grn.supplier_reference,
                notes=grn.notes,
                status=grn.status,
                created_at=grn.created_at,
                posted_at=grn.posted_at,
                reversed_at=grn.reversed_at,
                reversal_reason=grn.reversal_reason,
                line_count=counts.get(grn.id, 0),
                lines=lines.get(grn.id, []) if with_lines else None,
                value_minor=values.get(grn.id, 0 if grn.posted_at else None)
                if with_value
                else None,
                vendor_id=order.vendor_id,
                accrued_minor=accruals.get(grn.id),
                bill_id=bill.id if (bill := bills.get(grn.id)) else None,
                bill_number=bill.bill_number if bill else None,
                bill_status=bill.status.value if bill else None,
            )
        )
    return views


# --- shared stock lines -----------------------------------------------------


_Factors = dict[tuple[uuid.UUID, uuid.UUID], Decimal]


def _stock_lines(
    db: Session, lines: Sequence[InventoryStockIssueLine] | Sequence[InventoryStockTransferLine]
) -> tuple[dict[uuid.UUID, InventoryItem], dict[uuid.UUID, InventoryUnit], _Factors]:
    items = _by_id(db, InventoryItem, {line.item_id for line in lines})
    units = _units(db)
    factors = {
        (row.item_id, row.unit_id): row.factor_to_base
        for row in db.scalars(
            select(InventoryItemUnit).where(InventoryItemUnit.item_id.in_(set(items)))
        )
    }
    return items, units, factors


def _line_base(
    item: InventoryItem,
    unit_id: uuid.UUID,
    quantity: Decimal,
    factors: _Factors,
) -> Decimal | None:
    factor = Decimal(1) if unit_id == item.base_unit_id else factors.get((item.id, unit_id))
    if factor is None:
        return None
    try:
        return to_base_quantity(quantity, factor)
    except QuantityError:
        return None


# --- stock issues -----------------------------------------------------------


def list_issues(
    db: Session,
    scope: IssueScope,
    *,
    status: StockIssueStatus | None = None,
    warehouse_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[InventoryStockIssue]:
    query: Select[tuple[InventoryStockIssue]] = (
        select(InventoryStockIssue)
        .order_by(InventoryStockIssue.issue_date.desc(), InventoryStockIssue.created_at.desc())
        .limit(limit)
    )
    if not scope.everything:
        query = query.where(InventoryStockIssue.department_id.in_(scope.department_ids))
    if status is not None:
        query = query.where(InventoryStockIssue.status == status)
    if warehouse_id is not None:
        query = query.where(InventoryStockIssue.warehouse_id == warehouse_id)
    if department_id is not None:
        query = query.where(InventoryStockIssue.department_id == department_id)
    return list(db.scalars(query))


def issue_views(
    db: Session,
    issues: Sequence[InventoryStockIssue],
    *,
    with_lines: bool,
    with_value: bool,
) -> list[StockIssueOut]:
    if not issues:
        return []
    ids = [issue.id for issue in issues]
    org_id = issues[0].org_id
    warehouses = _by_id(db, InventoryWarehouse, {i.warehouse_id for i in issues})
    departments = _org_rows(
        db, Department, {i.department_id for i in issues if i.department_id}, org_id
    )
    employees = _org_rows(
        db,
        Employee,
        {i.requested_by_employee_id for i in issues if i.requested_by_employee_id},
        org_id,
    )
    counts = _counts(db, InventoryStockIssueLine.issue_id, ids)
    values = _posted_values(db, StockSourceType.STOCK_ISSUE, ids) if with_value else {}

    lines: dict[uuid.UUID, list[StockLineOut]] = {}
    if with_lines:
        stored = list(
            db.scalars(
                select(InventoryStockIssueLine)
                .where(InventoryStockIssueLine.issue_id.in_(ids))
                .order_by(InventoryStockIssueLine.line_no)
            )
        )
        items, units, factors = _stock_lines(db, stored)
        for line in stored:
            item = items[line.item_id]
            lines.setdefault(line.issue_id, []).append(
                StockLineOut(
                    id=line.id,
                    line_no=line.line_no,
                    item_id=item.id,
                    item_sku=item.sku,
                    item_name=item.name,
                    unit_id=line.unit_id,
                    unit_code=units[line.unit_id].code,
                    base_unit_code=units[item.base_unit_id].code,
                    quantity=line.quantity,
                    quantity_base=_line_base(item, line.unit_id, line.quantity, factors),
                    notes=line.notes,
                )
            )

    views = []
    for issue in issues:
        warehouse = warehouses[issue.warehouse_id]
        department = departments.get(issue.department_id) if issue.department_id else None
        requester = (
            employees.get(issue.requested_by_employee_id)
            if issue.requested_by_employee_id
            else None
        )
        views.append(
            StockIssueOut(
                id=issue.id,
                issue_number=issue.issue_number,
                warehouse_id=warehouse.id,
                warehouse_code=warehouse.code,
                warehouse_name=warehouse.name,
                department_id=issue.department_id,
                department_name=department.name if department else None,
                requested_by_employee_id=issue.requested_by_employee_id,
                requested_by_name=requester.full_name if requester else None,
                issue_date=issue.issue_date,
                purpose=issue.purpose,
                notes=issue.notes,
                status=issue.status,
                created_at=issue.created_at,
                submitted_at=issue.submitted_at,
                decided_at=issue.decided_at,
                posted_at=issue.posted_at,
                reversed_at=issue.reversed_at,
                reversal_reason=issue.reversal_reason,
                cancelled_at=issue.cancelled_at,
                line_count=counts.get(issue.id, 0),
                lines=lines.get(issue.id, []) if with_lines else None,
                value_minor=values.get(issue.id) if with_value else None,
            )
        )
    return views


# --- transfers --------------------------------------------------------------


def list_transfers(
    db: Session,
    *,
    status: StockTransferStatus | None = None,
    warehouse_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[InventoryStockTransfer]:
    query: Select[tuple[InventoryStockTransfer]] = (
        select(InventoryStockTransfer)
        .order_by(
            InventoryStockTransfer.transfer_date.desc(), InventoryStockTransfer.created_at.desc()
        )
        .limit(limit)
    )
    if status is not None:
        query = query.where(InventoryStockTransfer.status == status)
    if warehouse_id is not None:
        query = query.where(
            (InventoryStockTransfer.from_warehouse_id == warehouse_id)
            | (InventoryStockTransfer.to_warehouse_id == warehouse_id)
        )
    return list(db.scalars(query))


def transfer_views(
    db: Session, transfers: Sequence[InventoryStockTransfer], *, with_lines: bool
) -> list[StockTransferOut]:
    if not transfers:
        return []
    ids = [transfer.id for transfer in transfers]
    warehouses = _by_id(
        db,
        InventoryWarehouse,
        {t.from_warehouse_id for t in transfers} | {t.to_warehouse_id for t in transfers},
    )
    counts = _counts(db, InventoryStockTransferLine.transfer_id, ids)

    lines: dict[uuid.UUID, list[StockTransferLineOut]] = {}
    if with_lines:
        stored = list(
            db.scalars(
                select(InventoryStockTransferLine)
                .where(InventoryStockTransferLine.transfer_id.in_(ids))
                .order_by(InventoryStockTransferLine.line_no)
            )
        )
        items, units, factors = _stock_lines(db, stored)
        for line in stored:
            item = items[line.item_id]
            lines.setdefault(line.transfer_id, []).append(
                StockTransferLineOut(
                    id=line.id,
                    line_no=line.line_no,
                    item_id=item.id,
                    item_sku=item.sku,
                    item_name=item.name,
                    unit_id=line.unit_id,
                    unit_code=units[line.unit_id].code,
                    base_unit_code=units[item.base_unit_id].code,
                    quantity=line.quantity,
                    quantity_base=_line_base(item, line.unit_id, line.quantity, factors),
                    notes=line.notes,
                    dispatched_quantity_base=line.dispatched_quantity_base,
                    received_quantity_base=line.received_quantity_base,
                )
            )

    views = []
    for transfer in transfers:
        source = warehouses[transfer.from_warehouse_id]
        destination = warehouses[transfer.to_warehouse_id]
        views.append(
            StockTransferOut(
                id=transfer.id,
                transfer_number=transfer.transfer_number,
                from_warehouse_id=source.id,
                from_warehouse_code=source.code,
                from_warehouse_name=source.name,
                to_warehouse_id=destination.id,
                to_warehouse_code=destination.code,
                to_warehouse_name=destination.name,
                transfer_date=transfer.transfer_date,
                notes=transfer.notes,
                status=transfer.status,
                discrepancy_reason=transfer.discrepancy_reason,
                created_at=transfer.created_at,
                submitted_at=transfer.submitted_at,
                decided_at=transfer.decided_at,
                dispatched_at=transfer.dispatched_at,
                received_at=transfer.received_at,
                cancelled_at=transfer.cancelled_at,
                line_count=counts.get(transfer.id, 0),
                lines=lines.get(transfer.id, []) if with_lines else None,
            )
        )
    return views
