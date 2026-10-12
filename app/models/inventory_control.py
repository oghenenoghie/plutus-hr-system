"""Inventory Phase 4 (stock control): lots with expiry dates (D9) and
stocktakes counted against a snapshot taken at their cutoff (D6). See
docs/architecture/inventory-integration.md §16.

Lots track *quantity* only: value stays on the item's weighted-average cost
pool (D1), so a lot has no cost of its own. For a lot-tracked item, the
lot balances of each (item, warehouse) always add up to its stock balance.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped
from app.models.inventory import QUANTITY, _enum
from app.models.inventory_documents import _id, _org_id, _ref, _when, _who


class StocktakeStatus(str, enum.Enum):
    DRAFT = "draft"
    COUNTING = "counting"  # snapshot taken at cutoff_at; counts being entered
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    CANCELLED = "cancelled"


class InventoryLot(Base, OrgScoped):
    """One lot (batch) of an item, identified by the number on its packaging.
    Created when stock of a lot-tracked item first arrives under that number;
    its expiry date is fixed then."""

    __tablename__ = "inventory_lots"
    __table_args__ = (
        UniqueConstraint("org_id", "item_id", "lot_number", name="uq_inventory_lot_number"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    item_id: Mapped[uuid.UUID] = _ref("inventory_items")
    lot_number: Mapped[str] = mapped_column(String(64), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryLotBalance(Base, OrgScoped):
    """Quantity of one lot in one warehouse; a projection of the movements,
    like inventory_stock_balances, and updated only by the posting engine."""

    __tablename__ = "inventory_lot_balances"
    __table_args__ = (
        UniqueConstraint("item_id", "warehouse_id", "lot_id", name="uq_inventory_lot_balance"),
        CheckConstraint("quantity_base >= 0", name="ck_inventory_lot_balance_quantity"),
        Index("ix_inventory_lot_balances_item_wh", "item_id", "warehouse_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    item_id: Mapped[uuid.UUID] = _ref("inventory_items")
    warehouse_id: Mapped[uuid.UUID] = _ref("inventory_warehouses")
    lot_id: Mapped[uuid.UUID] = _ref("inventory_lots")
    quantity_base: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=Decimal(0))


class InventoryStocktake(Base, OrgScoped):
    """A physical count of one warehouse (D6). Starting it snapshots the
    expected quantities at cutoff_at; counts are compared with that
    snapshot, and posting applies only the variances, so stock that moved
    after the cutoff is never overwritten."""

    __tablename__ = "inventory_stocktakes"
    __table_args__ = (
        UniqueConstraint("org_id", "stocktake_number", name="uq_inventory_stocktake_number"),
        Index("ix_inventory_stocktake_status", "org_id", "status"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    stocktake_number: Mapped[str] = mapped_column(String(32), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = _ref("inventory_warehouses")
    # Optional scope: count only this category's items (None: every item).
    category_id: Mapped[uuid.UUID | None] = _ref("inventory_categories", nullable=True)
    count_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[StocktakeStatus] = mapped_column(
        _enum(StocktakeStatus, "inventory_stocktake_status"),
        nullable=False,
        default=StocktakeStatus.DRAFT,
    )
    cutoff_at: Mapped[datetime | None] = _when()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = _who()
    started_by: Mapped[uuid.UUID | None] = _who()
    submitted_at: Mapped[datetime | None] = _when()
    submitted_by: Mapped[uuid.UUID | None] = _who()
    decided_at: Mapped[datetime | None] = _when()
    posted_at: Mapped[datetime | None] = _when()
    posted_by: Mapped[uuid.UUID | None] = _who()
    cancelled_at: Mapped[datetime | None] = _when()
    cancelled_by: Mapped[uuid.UUID | None] = _who()


class InventoryStocktakeLine(Base, OrgScoped):
    """One item (and, for a lot-tracked item, one lot) to count. Quantities
    are in the item's base unit. expected_quantity_base is the snapshot at
    the cutoff; counted_quantity_base stays NULL until counted. A lot found
    during the count that the system doesn't know yet carries its number
    and expiry date here, and gets its lot_id when the stocktake posts."""

    __tablename__ = "inventory_stocktake_lines"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "line_no", name="uq_inventory_stocktake_line_no"),
        CheckConstraint("expected_quantity_base >= 0", name="ck_inventory_stocktake_line_expected"),
        CheckConstraint(
            "counted_quantity_base IS NULL OR counted_quantity_base >= 0",
            name="ck_inventory_stocktake_line_counted",
        ),
        Index(
            "uq_inventory_stocktake_item_lot",
            "stocktake_id",
            "item_id",
            text("coalesce(lot_number, '')"),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    stocktake_id: Mapped[uuid.UUID] = _ref("inventory_stocktakes", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[uuid.UUID] = _ref("inventory_items")
    lot_id: Mapped[uuid.UUID | None] = _ref("inventory_lots", nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(64))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    expected_quantity_base: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    counted_quantity_base: Mapped[Decimal | None] = mapped_column(QUANTITY)
    notes: Mapped[str | None] = mapped_column(String(500))
