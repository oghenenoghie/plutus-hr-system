import enum
from datetime import date, datetime

from pydantic import BaseModel


class InventoryDocumentType(str, enum.Enum):
    """The inventory documents that post journals."""

    GOODS_RECEIPT = "goods_receipt"
    STOCK_ISSUE = "stock_issue"
    STOCK_ADJUSTMENT = "stock_adjustment"
    STOCK_TRANSFER = "stock_transfer"
    STOCKTAKE = "stocktake"


class InventoryReconciliationOut(BaseModel):
    """Inventory against the GL (docs/architecture/inventory-integration.md
    §15). Both differences are zero while every stock change has posted."""

    post_to_gl: bool
    gl_started_at: datetime | None
    lock_date: date | None
    stock_value_minor: int
    gl_inventory_minor: int
    inventory_difference_minor: int
    unbilled_receipts: int
    unbilled_receipts_minor: int
    gl_grni_minor: int
    grni_difference_minor: int
