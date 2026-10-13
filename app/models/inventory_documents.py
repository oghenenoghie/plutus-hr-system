"""Inventory operations documents (Phase 2): purchase orders, goods
receipts, stock issues and inter-warehouse transfers.

A document never changes stock by itself. Stock moves only when a document
is posted (goods receipt, issue) or dispatched/received (transfer), through
app/services/inventory_posting.post_movements, in the same transaction as
the document's status change. Every table is org-owned with RLS and
OrgScoped. Status changes happen only in the service layer.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped
from app.models.inventory import QUANTITY, _enum


class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ISSUED = "issued"  # sent to the vendor; goods can now be received
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CLOSED = "closed"  # short-closed: the rest will not be delivered
    CANCELLED = "cancelled"


class GoodsReceiptStatus(str, enum.Enum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class StockIssueStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    REVERSED = "reversed"
    CANCELLED = "cancelled"


class StockTransferStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    CANCELLED = "cancelled"


def _org_id() -> Any:
    return mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )


def _id() -> Any:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ref(table: str, *, nullable: bool = False, ondelete: str = "RESTRICT") -> Any:
    return mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable
    )


def _when() -> Any:
    return mapped_column(DateTime(timezone=True))


def _who() -> Any:
    return mapped_column(PGUUID(as_uuid=True))


# --- purchase orders --------------------------------------------------------


class InventoryPurchaseOrder(Base, OrgScoped):
    """An order to a vendor (vendors are reused as suppliers). Approved
    through the approval engine (request type purchase_order), issued to
    the vendor, then received in one or more goods receipts. An order never
    changes stock or posts a journal itself."""

    __tablename__ = "inventory_purchase_orders"
    __table_args__ = (
        UniqueConstraint("org_id", "po_number", name="uq_inventory_po_number"),
        Index("ix_inventory_po_status", "org_id", "status"),
        CheckConstraint(
            "expected_date IS NULL OR expected_date >= order_date",
            name="ck_inventory_po_expected_date",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    po_number: Mapped[str] = mapped_column(String(32), nullable=False)
    vendor_id: Mapped[uuid.UUID] = _ref("vendors")
    # Where the goods are expected; a receipt may still go elsewhere.
    warehouse_id: Mapped[uuid.UUID | None] = _ref("inventory_warehouses", nullable=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date)
    vendor_reference: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        _enum(PurchaseOrderStatus, "inventory_po_status"),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT,
    )
    created_by: Mapped[uuid.UUID | None] = _who()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = _when()
    submitted_by: Mapped[uuid.UUID | None] = _who()
    decided_at: Mapped[datetime | None] = _when()
    issued_at: Mapped[datetime | None] = _when()
    issued_by: Mapped[uuid.UUID | None] = _who()
    closed_at: Mapped[datetime | None] = _when()
    closed_by: Mapped[uuid.UUID | None] = _who()
    close_reason: Mapped[str | None] = mapped_column(String(500))


class InventoryPurchaseOrderLine(Base, OrgScoped):
    """One item on an order, in the unit it is bought in. quantity_base is
    the ordered quantity converted when the order was saved, so a later
    change to the item's conversion never changes what was ordered.
    received_quantity_base is the running total of posted receipts."""

    __tablename__ = "inventory_purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "line_no", name="uq_inventory_po_line_no"),
        CheckConstraint("quantity > 0 AND quantity_base > 0", name="ck_inventory_po_line_qty"),
        CheckConstraint(
            "unit_price_minor >= 0 AND discount_minor >= 0 AND tax_minor >= 0",
            name="ck_inventory_po_line_amounts",
        ),
        CheckConstraint(
            "discount_minor <= quantity * unit_price_minor", name="ck_inventory_po_line_discount"
        ),
        CheckConstraint("received_quantity_base >= 0", name="ck_inventory_po_line_received"),
        # Phase 5: reorder suggestions (quantity on order, last unit cost).
        Index("ix_inventory_po_lines_org_item", "org_id", "item_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    purchase_order_id: Mapped[uuid.UUID] = _ref("inventory_purchase_orders", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[uuid.UUID] = _ref("inventory_items")
    unit_id: Mapped[uuid.UUID] = _ref("inventory_units")
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    # Agreed price per `unit_id`, before the line discount. Tax is the
    # amount the vendor will charge on this line, entered as an amount (no
    # rate is assumed); it is informational until the bill (D14).
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    received_quantity_base: Mapped[Decimal] = mapped_column(
        QUANTITY, nullable=False, default=Decimal(0)
    )
    notes: Mapped[str | None] = mapped_column(String(500))


# --- goods receipts ---------------------------------------------------------


class InventoryGoodsReceipt(Base, OrgScoped):
    """A delivery received against an issued purchase order (a GRN).
    Posting adds the accepted quantities to stock at the order's net price
    and raises the order's received quantities, under a lock on the order
    so two receipts can never receive the same quantity twice. Corrected
    by reversal, never by editing."""

    __tablename__ = "inventory_goods_receipts"
    __table_args__ = (
        UniqueConstraint("org_id", "grn_number", name="uq_inventory_grn_number"),
        Index("ix_inventory_grn_purchase_order", "purchase_order_id"),
        CheckConstraint(
            "status <> 'reversed' OR reversal_reason IS NOT NULL",
            name="ck_inventory_grn_reversal_reason",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    grn_number: Mapped[str] = mapped_column(String(32), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = _ref("inventory_purchase_orders")
    warehouse_id: Mapped[uuid.UUID] = _ref("inventory_warehouses")
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_reference: Mapped[str | None] = mapped_column(String(64))  # delivery note
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[GoodsReceiptStatus] = mapped_column(
        _enum(GoodsReceiptStatus, "inventory_grn_status"),
        nullable=False,
        default=GoodsReceiptStatus.DRAFT,
    )
    created_by: Mapped[uuid.UUID | None] = _who()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    posted_at: Mapped[datetime | None] = _when()
    posted_by: Mapped[uuid.UUID | None] = _who()
    reversed_at: Mapped[datetime | None] = _when()
    reversed_by: Mapped[uuid.UUID | None] = _who()
    reversal_reason: Mapped[str | None] = mapped_column(String(500))


class InventoryGoodsReceiptLine(Base, OrgScoped):
    """What arrived for one order line, in that line's unit. Accepted
    quantity goes into stock; rejected quantity is recorded only (returned
    to the vendor) and does not count as received."""

    __tablename__ = "inventory_goods_receipt_lines"
    __table_args__ = (
        UniqueConstraint("goods_receipt_id", "line_no", name="uq_inventory_grn_line_no"),
        UniqueConstraint("goods_receipt_id", "po_line_id", name="uq_inventory_grn_po_line"),
        CheckConstraint(
            "accepted_quantity >= 0 AND rejected_quantity >= 0 "
            "AND accepted_quantity + rejected_quantity > 0",
            name="ck_inventory_grn_line_qty",
        ),
        # Phase 5: deleting a draft order's lines checks this foreign key.
        Index("ix_inventory_grn_lines_po_line", "po_line_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    goods_receipt_id: Mapped[uuid.UUID] = _ref("inventory_goods_receipts", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    po_line_id: Mapped[uuid.UUID] = _ref("inventory_purchase_order_lines")
    accepted_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    rejected_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=Decimal(0))
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    # Phase 4 (D9): the lot the accepted goods arrive as, for a lot-tracked
    # item (with its expiry date when the item tracks expiry).
    lot_number: Mapped[str | None] = mapped_column(String(64))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(500))


# --- stock issues -----------------------------------------------------------


class InventoryStockIssue(Base, OrgScoped):
    """Stock handed out for consumption — to a department, a project, or
    maintenance. A department manager can request one for their own
    department; it is approved through the approval engine (request type
    stock_issue, unless the organisation turned issue approval off) and
    takes stock out only when posted."""

    __tablename__ = "inventory_stock_issues"
    __table_args__ = (
        UniqueConstraint("org_id", "issue_number", name="uq_inventory_issue_number"),
        Index("ix_inventory_issue_status", "org_id", "status"),
        CheckConstraint(
            "status <> 'reversed' OR reversal_reason IS NOT NULL",
            name="ck_inventory_issue_reversal_reason",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    issue_number: Mapped[str] = mapped_column(String(32), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = _ref("inventory_warehouses")
    department_id: Mapped[uuid.UUID | None] = _ref("departments", nullable=True)
    # The employee who asked for the stock; resolves the direct-manager and
    # department-head approval steps.
    requested_by_employee_id: Mapped[uuid.UUID | None] = _ref(
        "employees", nullable=True, ondelete="SET NULL"
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[StockIssueStatus] = mapped_column(
        _enum(StockIssueStatus, "inventory_issue_status"),
        nullable=False,
        default=StockIssueStatus.DRAFT,
    )
    created_by: Mapped[uuid.UUID | None] = _who()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = _when()
    submitted_by: Mapped[uuid.UUID | None] = _who()
    decided_at: Mapped[datetime | None] = _when()
    posted_at: Mapped[datetime | None] = _when()
    posted_by: Mapped[uuid.UUID | None] = _who()
    reversed_at: Mapped[datetime | None] = _when()
    reversed_by: Mapped[uuid.UUID | None] = _who()
    reversal_reason: Mapped[str | None] = mapped_column(String(500))
    cancelled_at: Mapped[datetime | None] = _when()
    cancelled_by: Mapped[uuid.UUID | None] = _who()


class InventoryStockIssueLine(Base, OrgScoped):
    __tablename__ = "inventory_stock_issue_lines"
    __table_args__ = (
        UniqueConstraint("issue_id", "line_no", name="uq_inventory_issue_line_no"),
        CheckConstraint("quantity > 0", name="ck_inventory_issue_line_qty"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    issue_id: Mapped[uuid.UUID] = _ref("inventory_stock_issues", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[uuid.UUID] = _ref("inventory_items")
    unit_id: Mapped[uuid.UUID] = _ref("inventory_units")
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))


# --- transfers --------------------------------------------------------------


class InventoryStockTransfer(Base, OrgScoped):
    """Stock moved between two of the organisation's warehouses, with the
    in-transit step explicit (D5): dispatch moves it from the source into
    the in-transit location; receipt moves what arrived into the
    destination and writes any shortfall off as a transit loss. Value is
    unchanged by the move itself (one average per item, D1)."""

    __tablename__ = "inventory_stock_transfers"
    __table_args__ = (
        UniqueConstraint("org_id", "transfer_number", name="uq_inventory_transfer_number"),
        Index("ix_inventory_transfer_status", "org_id", "status"),
        CheckConstraint(
            "from_warehouse_id <> to_warehouse_id", name="ck_inventory_transfer_warehouses"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    transfer_number: Mapped[str] = mapped_column(String(32), nullable=False)
    from_warehouse_id: Mapped[uuid.UUID] = _ref("inventory_warehouses")
    to_warehouse_id: Mapped[uuid.UUID] = _ref("inventory_warehouses")
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[StockTransferStatus] = mapped_column(
        _enum(StockTransferStatus, "inventory_transfer_status"),
        nullable=False,
        default=StockTransferStatus.DRAFT,
    )
    # Why less arrived than was sent; required when there is a shortfall.
    discrepancy_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = _who()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = _when()
    submitted_by: Mapped[uuid.UUID | None] = _who()
    decided_at: Mapped[datetime | None] = _when()
    dispatched_at: Mapped[datetime | None] = _when()
    dispatched_by: Mapped[uuid.UUID | None] = _who()
    received_at: Mapped[datetime | None] = _when()
    received_by: Mapped[uuid.UUID | None] = _who()
    cancelled_at: Mapped[datetime | None] = _when()
    cancelled_by: Mapped[uuid.UUID | None] = _who()


class InventoryStockTransferLine(Base, OrgScoped):
    """quantity is what was asked for, in unit_id. dispatched and received
    quantities are in the item's base unit, set by the dispatch and receipt
    steps."""

    __tablename__ = "inventory_stock_transfer_lines"
    __table_args__ = (
        UniqueConstraint("transfer_id", "line_no", name="uq_inventory_transfer_line_no"),
        CheckConstraint("quantity > 0", name="ck_inventory_transfer_line_qty"),
        CheckConstraint(
            "received_quantity_base IS NULL OR (dispatched_quantity_base IS NOT NULL "
            "AND received_quantity_base >= 0 "
            "AND received_quantity_base <= dispatched_quantity_base)",
            name="ck_inventory_transfer_line_received",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    transfer_id: Mapped[uuid.UUID] = _ref("inventory_stock_transfers", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[uuid.UUID] = _ref("inventory_items")
    unit_id: Mapped[uuid.UUID] = _ref("inventory_units")
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    dispatched_quantity_base: Mapped[Decimal | None] = mapped_column(QUANTITY)
    received_quantity_base: Mapped[Decimal | None] = mapped_column(QUANTITY)
    notes: Mapped[str | None] = mapped_column(String(500))
