"""Inventory Phase 4 (stock control): lots, stocktakes, reorder suggestions
and reports. Quantities are in the item's base unit; values are in minor
units (kobo) and are None for callers without inventory.valuation."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.inventory import StockMovementType
from app.models.inventory_control import StocktakeStatus
from app.schemas.inventory_documents import NonNegativeQuantity

# --- lots -------------------------------------------------------------------


class LotStockOut(BaseModel):
    """One lot's quantity in one warehouse."""

    lot_id: uuid.UUID
    lot_number: str
    expiry_date: date | None
    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    quantity: Decimal
    expired: bool
    days_to_expiry: int | None
    value_minor: int | None  # at the item's average cost


# --- stocktakes -------------------------------------------------------------


class StocktakeCreate(BaseModel):
    warehouse_id: uuid.UUID
    count_date: date
    category_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)


class StocktakeCountIn(BaseModel):
    """`counted_quantity` in the item's base unit; null clears the count."""

    line_id: uuid.UUID
    counted_quantity: NonNegativeQuantity | None
    notes: str | None = Field(default=None, max_length=500)


class StocktakeCountsIn(BaseModel):
    counts: list[StocktakeCountIn] = Field(min_length=1, max_length=2000)


class StocktakeLineAdd(BaseModel):
    """An item (or lot) found during the count that the snapshot didn't
    list: the books held none of it here at the cutoff."""

    item_id: uuid.UUID
    counted_quantity: NonNegativeQuantity
    lot_number: str | None = Field(default=None, max_length=64)
    expiry_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class StocktakeLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    base_unit_allows_fraction: bool
    lot_id: uuid.UUID | None
    lot_number: str | None
    expiry_date: date | None
    expected_quantity: Decimal
    counted_quantity: Decimal | None
    variance: Decimal | None  # None until counted
    # Posted: what the variance moved. Before: an estimate at today's average.
    variance_value_minor: int | None
    added_during_count: bool
    notes: str | None


class StocktakeOut(BaseModel):
    id: uuid.UUID
    stocktake_number: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    warehouse_name: str
    category_id: uuid.UUID | None
    category_name: str | None
    count_date: date
    notes: str | None
    status: StocktakeStatus
    cutoff_at: datetime | None
    created_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    posted_at: datetime | None
    cancelled_at: datetime | None
    line_count: int
    counted_count: int
    variance_count: int
    gain_value_minor: int | None
    loss_value_minor: int | None
    # Whether submitting will need approval (D8 rule); None until fully counted.
    needs_approval: bool | None
    lines: list[StocktakeLineOut] | None = None


# --- reorder ----------------------------------------------------------------


class ReorderSuggestionOut(BaseModel):
    """An item at or below its reorder level once what's already on order
    is counted. Expired lots don't count as stock on hand."""

    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    reorder_level: Decimal
    max_level: Decimal | None
    on_hand: Decimal
    expired: Decimal
    on_order: Decimal
    available: Decimal  # on_hand - expired + on_order
    suggested_quantity: Decimal
    preferred_vendor_id: uuid.UUID | None
    preferred_vendor_name: str | None
    # From the latest purchase order line for the item, per base unit.
    last_unit_cost_minor: int | None
    estimated_cost_minor: int | None


# --- reports ----------------------------------------------------------------


class ValuationRowOut(BaseModel):
    item_id: uuid.UUID
    sku: str
    item_name: str
    category_name: str | None
    base_unit_code: str
    warehouse_id: uuid.UUID | None  # None when not split by warehouse
    warehouse_code: str | None
    quantity: Decimal
    value_minor: int
    average_cost_minor: int | None


class ValuationReportOut(BaseModel):
    """Stock and its value at the end of `as_of`, rebuilt from the movement
    ledger, against the inventory account's balance on the same date."""

    as_of: date
    by_warehouse: bool
    rows: list[ValuationRowOut]
    total_quantity: Decimal
    total_value_minor: int
    posts_to_gl: bool
    gl_started_at: datetime | None
    gl_balance_minor: int | None
    difference_minor: int | None


class MovementSummaryRowOut(BaseModel):
    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    opening_quantity: Decimal
    received: Decimal
    issued: Decimal
    transferred_in: Decimal
    transferred_out: Decimal
    adjusted: Decimal  # adjustments and stocktake variances, net
    reversed: Decimal
    closing_quantity: Decimal
    opening_value_minor: int | None
    closing_value_minor: int | None


class MovementSummaryOut(BaseModel):
    date_from: date
    date_to: date
    warehouse_id: uuid.UUID | None
    rows: list[MovementSummaryRowOut]


class VarianceRowOut(BaseModel):
    entry_date: date
    source_type: str
    source_id: uuid.UUID
    source_number: str | None
    reason: str | None
    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    warehouse_code: str
    lot_number: str | None
    movement_type: StockMovementType
    quantity: Decimal
    value_minor: int | None


class VarianceReportOut(BaseModel):
    """Every adjustment and stocktake movement in the period."""

    date_from: date
    date_to: date
    rows: list[VarianceRowOut]
    gain_value_minor: int | None
    loss_value_minor: int | None


class ExpiryReportOut(BaseModel):
    as_of: date
    within_days: int
    rows: list[LotStockOut]
    expired_value_minor: int | None
    expiring_value_minor: int | None


class OutstandingOrderRowOut(BaseModel):
    purchase_order_id: uuid.UUID
    po_number: str
    vendor_name: str
    order_date: date
    expected_date: date | None
    status: str
    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    ordered: Decimal
    received: Decimal
    outstanding: Decimal
    outstanding_value_minor: int


class OutstandingOrdersOut(BaseModel):
    rows: list[OutstandingOrderRowOut]
    total_value_minor: int
