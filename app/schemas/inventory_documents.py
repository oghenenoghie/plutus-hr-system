"""Request and response models for the Phase 2 inventory documents:
purchase orders, goods receipts, stock issues and transfers. Quantities are
decimal strings in JSON; money is integer minor units."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.inventory import InventoryItemType
from app.models.inventory_documents import (
    GoodsReceiptStatus,
    PurchaseOrderStatus,
    StockIssueStatus,
    StockTransferStatus,
)
from app.schemas.inventory import MinorAmount

PositiveQuantity = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
NonNegativeQuantity = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]


# --- shared actions ---------------------------------------------------------


class DecisionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


# --- purchase orders --------------------------------------------------------


class PurchaseOrderLineIn(BaseModel):
    """`quantity` and `unit_price_minor` are in `unit_id` (the item's base
    unit when omitted). Discount and tax are amounts for the whole line."""

    item_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    quantity: PositiveQuantity
    unit_price_minor: MinorAmount
    discount_minor: MinorAmount = 0
    tax_minor: MinorAmount = 0
    notes: str | None = Field(default=None, max_length=500)


class PurchaseOrderCreate(BaseModel):
    vendor_id: uuid.UUID
    warehouse_id: uuid.UUID | None = None
    order_date: date
    expected_date: date | None = None
    vendor_reference: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[PurchaseOrderLineIn] = Field(min_length=1, max_length=200)


class PurchaseOrderLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_sku: str
    item_name: str
    item_type: InventoryItemType
    unit_id: uuid.UUID
    unit_code: str
    base_unit_code: str
    quantity: Decimal
    quantity_base: Decimal
    unit_price_minor: int
    discount_minor: int
    tax_minor: int
    net_minor: int
    total_minor: int
    received_quantity_base: Decimal
    outstanding_quantity_base: Decimal
    notes: str | None


class GoodsReceiptBrief(BaseModel):
    id: uuid.UUID
    grn_number: str
    receipt_date: date
    status: GoodsReceiptStatus
    warehouse_code: str


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    po_number: str
    vendor_id: uuid.UUID
    vendor_name: str
    warehouse_id: uuid.UUID | None
    warehouse_code: str | None
    order_date: date
    expected_date: date | None
    vendor_reference: str | None
    notes: str | None
    status: PurchaseOrderStatus
    created_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    issued_at: datetime | None
    closed_at: datetime | None
    close_reason: str | None
    line_count: int
    subtotal_minor: int  # sum of line net amounts
    tax_minor: int
    total_minor: int
    lines: list[PurchaseOrderLineOut] | None  # single-order endpoints only
    receipts: list[GoodsReceiptBrief] | None


# --- goods receipts ---------------------------------------------------------


class GoodsReceiptLineIn(BaseModel):
    """Quantities are in the order line's unit."""

    po_line_id: uuid.UUID
    accepted_quantity: NonNegativeQuantity
    rejected_quantity: NonNegativeQuantity = Decimal(0)
    rejection_reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)
    # Required for a lot-tracked item receiving stock; a new lot of an
    # expiry-tracked item also needs its expiry date (D9).
    lot_number: str | None = Field(default=None, max_length=64)
    expiry_date: date | None = None


class GoodsReceiptUpdate(BaseModel):
    warehouse_id: uuid.UUID
    receipt_date: date
    supplier_reference: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[GoodsReceiptLineIn] = Field(min_length=1, max_length=200)


class GoodsReceiptCreate(GoodsReceiptUpdate):
    purchase_order_id: uuid.UUID


class GoodsReceiptLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    po_line_id: uuid.UUID
    item_id: uuid.UUID
    item_sku: str
    item_name: str
    unit_code: str
    base_unit_code: str
    accepted_quantity: Decimal
    rejected_quantity: Decimal
    accepted_quantity_base: Decimal
    rejection_reason: str | None
    notes: str | None
    lot_number: str | None
    expiry_date: date | None


class GoodsReceiptOut(BaseModel):
    id: uuid.UUID
    grn_number: str
    purchase_order_id: uuid.UUID
    po_number: str
    vendor_name: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    warehouse_name: str
    receipt_date: date
    supplier_reference: str | None
    notes: str | None
    status: GoodsReceiptStatus
    created_at: datetime
    posted_at: datetime | None
    reversed_at: datetime | None
    reversal_reason: str | None
    line_count: int
    lines: list[GoodsReceiptLineOut] | None
    # Value added to stock, for callers holding inventory.valuation.
    value_minor: int | None
    vendor_id: uuid.UUID
    # Phase 3 (D2): what the receipt accrued to goods-received-not-invoiced
    # (valuation holders only; None when it posted no journal), and the bill
    # (not void) that invoices it.
    accrued_minor: int | None
    bill_id: uuid.UUID | None
    bill_number: str | None
    bill_status: str | None


# --- stock issues -----------------------------------------------------------


class StockLineIn(BaseModel):
    item_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    quantity: PositiveQuantity
    notes: str | None = Field(default=None, max_length=500)


class StockIssueCreate(BaseModel):
    warehouse_id: uuid.UUID
    department_id: uuid.UUID | None = None
    # Defaults to the caller's own employee record, when they have one.
    requested_by_employee_id: uuid.UUID | None = None
    issue_date: date
    purpose: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[StockLineIn] = Field(min_length=1, max_length=200)


class StockLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_sku: str
    item_name: str
    unit_id: uuid.UUID
    unit_code: str
    base_unit_code: str
    quantity: Decimal
    quantity_base: Decimal | None  # None when the conversion no longer resolves
    notes: str | None


class StockIssueOut(BaseModel):
    id: uuid.UUID
    issue_number: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    warehouse_name: str
    department_id: uuid.UUID | None
    department_name: str | None
    requested_by_employee_id: uuid.UUID | None
    requested_by_name: str | None
    issue_date: date
    purpose: str
    notes: str | None
    status: StockIssueStatus
    created_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    posted_at: datetime | None
    reversed_at: datetime | None
    reversal_reason: str | None
    cancelled_at: datetime | None
    line_count: int
    lines: list[StockLineOut] | None
    value_minor: int | None  # value issued, with inventory.valuation


class IssueDepartmentOut(BaseModel):
    id: uuid.UUID
    name: str


# --- transfers --------------------------------------------------------------


class StockTransferCreate(BaseModel):
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    transfer_date: date
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[StockLineIn] = Field(min_length=1, max_length=200)


class TransferDispatchIn(BaseModel):
    dispatch_date: date | None = None  # defaults to today (Lagos)


class TransferReceiveLineIn(BaseModel):
    line_id: uuid.UUID
    # In the item's base unit; at most what was dispatched on that line.
    received_quantity_base: NonNegativeQuantity


class TransferReceiveIn(BaseModel):
    receipt_date: date | None = None  # defaults to today (Lagos)
    lines: list[TransferReceiveLineIn] = Field(min_length=1, max_length=200)
    # Required when anything arrived short: the shortfall is written off.
    discrepancy_reason: str | None = Field(default=None, max_length=500)


class StockTransferLineOut(StockLineOut):
    dispatched_quantity_base: Decimal | None
    received_quantity_base: Decimal | None


class StockTransferOut(BaseModel):
    id: uuid.UUID
    transfer_number: str
    from_warehouse_id: uuid.UUID
    from_warehouse_code: str
    from_warehouse_name: str
    to_warehouse_id: uuid.UUID
    to_warehouse_code: str
    to_warehouse_name: str
    transfer_date: date
    notes: str | None
    status: StockTransferStatus
    discrepancy_reason: str | None
    created_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    dispatched_at: datetime | None
    received_at: datetime | None
    cancelled_at: datetime | None
    line_count: int
    lines: list[StockTransferLineOut] | None
