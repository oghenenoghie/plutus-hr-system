import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.inventory import (
    InventoryAdjustmentReason,
    InventoryAdjustmentStatus,
    InventoryItemType,
    StockMovementType,
    StockSourceType,
)

# Quantities travel as decimal strings in JSON (never floats) and are capped
# at the column's NUMERIC(18, 4) precision.
Quantity = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]
Factor = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
MinorAmount = Annotated[int, Field(ge=0, le=10**15)]


# --- settings ---------------------------------------------------------------


class InventorySettingsOut(BaseModel):
    enabled: bool
    costing_method: str
    over_receipt_tolerance_bp: int
    adjustment_gain_approval_limit_minor: int | None
    require_issue_approval: bool
    require_transfer_approval: bool
    # Phase 3: whether posted documents also post journals, and since when.
    post_to_gl: bool
    gl_started_at: datetime | None

    model_config = {"from_attributes": True}


class InventorySettingsUpdate(BaseModel):
    """Partial update: only the fields sent change. Send null for
    adjustment_gain_approval_limit_minor to remove the limit."""

    enabled: bool | None = None
    # Basis points of the ordered quantity: 500 = 5% (D4).
    over_receipt_tolerance_bp: int | None = Field(default=None, ge=0, le=10_000)
    adjustment_gain_approval_limit_minor: MinorAmount | None = None
    require_issue_approval: bool | None = None
    require_transfer_approval: bool | None = None


# --- categories -------------------------------------------------------------


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    # D18: the expense account issues from this category are charged to.
    # None inherits the parent's, then falls back to inventory_consumption.
    expense_account_code: str | None = Field(default=None, min_length=1, max_length=64)


class CategoryUpdate(BaseModel):
    """Partial update; send null for expense_account_code to inherit again."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None
    expense_account_code: str | None = Field(default=None, min_length=1, max_length=64)


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    is_active: bool
    expense_account_code: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- units ------------------------------------------------------------------


class UnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=64)
    allows_fraction: bool = False


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    allows_fraction: bool | None = None
    is_active: bool | None = None


class UnitOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    allows_fraction: bool
    is_active: bool

    model_config = {"from_attributes": True}


# --- items ------------------------------------------------------------------


class ItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    item_type: InventoryItemType = InventoryItemType.STOCK
    base_unit_id: uuid.UUID
    description: str | None = Field(default=None, max_length=1000)
    category_id: uuid.UUID | None = None
    reorder_level: Quantity | None = None
    max_level: Quantity | None = None
    default_cost_minor: MinorAmount | None = None
    preferred_vendor_id: uuid.UUID | None = None
    barcode: str | None = Field(default=None, max_length=64)


class ItemUpdate(BaseModel):
    """Partial update: only the fields sent are changed. Send null to clear
    an optional field."""

    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    item_type: InventoryItemType | None = None
    base_unit_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=1000)
    category_id: uuid.UUID | None = None
    reorder_level: Quantity | None = None
    max_level: Quantity | None = None
    default_cost_minor: MinorAmount | None = None
    preferred_vendor_id: uuid.UUID | None = None
    barcode: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None


class ItemUnitIn(BaseModel):
    unit_id: uuid.UUID
    factor_to_base: Factor


class ItemUnitsReplace(BaseModel):
    units: list[ItemUnitIn] = Field(max_length=20)


class ItemUnitOut(BaseModel):
    unit_id: uuid.UUID
    unit_code: str
    unit_name: str
    factor_to_base: Decimal


class ItemOut(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    item_type: InventoryItemType
    category_id: uuid.UUID | None
    category_name: str | None
    base_unit_id: uuid.UUID
    base_unit_code: str
    base_unit_allows_fraction: bool
    reorder_level: Decimal | None
    max_level: Decimal | None
    default_cost_minor: int | None
    preferred_vendor_id: uuid.UUID | None
    barcode: str | None
    is_active: bool
    created_at: datetime
    units: list[ItemUnitOut]
    quantity_on_hand: Decimal
    # Present only for callers holding inventory.valuation.
    value_minor: int | None
    average_cost_minor: int | None


# --- warehouses -------------------------------------------------------------


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=120)
    branch_id: uuid.UUID | None = None
    address: str | None = Field(default=None, max_length=500)


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    branch_id: uuid.UUID | None = None
    address: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class WarehouseOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    branch_id: uuid.UUID | None
    address: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# --- adjustments ------------------------------------------------------------


class AdjustmentLineIn(BaseModel):
    """`quantity` is signed, in `unit_id` (the item's base unit when
    omitted): positive adds stock, negative removes it. Increases need
    `unit_cost_minor` per that unit (defaults to the item's default cost);
    decreases must not send one — they leave at the average cost."""

    item_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    quantity: Quantity
    unit_cost_minor: MinorAmount | None = None
    notes: str | None = Field(default=None, max_length=500)


class AdjustmentCreate(BaseModel):
    warehouse_id: uuid.UUID
    reason: InventoryAdjustmentReason
    adjustment_date: date
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[AdjustmentLineIn] = Field(min_length=1, max_length=500)


class AdjustmentReverse(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AdjustmentLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_sku: str
    item_name: str
    unit_id: uuid.UUID
    unit_code: str
    quantity: Decimal
    quantity_base: Decimal | None  # None when the conversion no longer resolves
    unit_cost_minor: int | None
    notes: str | None


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    adjustment_number: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    warehouse_name: str
    reason: InventoryAdjustmentReason
    adjustment_date: date
    notes: str | None
    status: InventoryAdjustmentStatus
    # Whether posting needs approval first (D8); worked out from the lines.
    requires_approval: bool
    created_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    posted_at: datetime | None
    reversed_at: datetime | None
    reversal_reason: str | None
    line_count: int
    lines: list[AdjustmentLineOut] | None  # only on the single-adjustment endpoints
    # Net value posted (signed), for callers holding inventory.valuation.
    value_minor: int | None


# --- stock and movements ----------------------------------------------------


class StockRowOut(BaseModel):
    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    warehouse_name: str
    quantity: Decimal
    reorder_level: Decimal | None
    # quantity x the item's average cost; None without inventory.valuation.
    value_minor: int | None


class MovementOut(BaseModel):
    id: uuid.UUID
    entry_date: date
    created_at: datetime
    item_id: uuid.UUID
    sku: str
    item_name: str
    base_unit_code: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    movement_type: StockMovementType
    quantity: Decimal
    value_minor: int | None
    unit_cost_minor: int | None
    source_type: StockSourceType
    source_id: uuid.UUID
    source_number: str | None
    reversal_of_id: uuid.UUID | None
    reason: str | None


class MovementPage(BaseModel):
    items: list[MovementOut]
    total: int


class InventorySummaryOut(BaseModel):
    enabled: bool
    tracked_items: int
    out_of_stock: int
    low_stock: int
    active_warehouses: int
    draft_adjustments: int
    pending_approvals: int  # documents of every kind awaiting a decision
    open_purchase_orders: int  # issued or partially received
    transfers_in_transit: int
    total_value_minor: int | None
    recent_movements: list[MovementOut]
