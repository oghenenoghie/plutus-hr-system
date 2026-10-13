"""Inventory: master data, adjustment documents and the stock ledger.

Design and the decisions behind it: docs/architecture/inventory-integration.md.
Every table is organisation-owned with RLS, and every model is OrgScoped
(the ORM repeats the org filter, so isolation doesn't depend on the
database role). Quantities are NUMERIC(18, 4)
in the item's base unit; money is BIGINT minor units, like the rest of the
codebase.

The stock ledger (`inventory_stock_movements`) is append-only and is the
source of truth. `inventory_stock_balances` (quantity per item and
warehouse) and `inventory_item_costs` (quantity and value per item, the
weighted-average pool) are projections written only by
app/services/inventory_posting.py in the same transaction as the movements
they summarise.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped

QUANTITY = Numeric(18, 4)

# Stands in for "no lot" in unique indexes, where NULLs would otherwise
# never collide (Phase 4).
NO_LOT = "00000000-0000-0000-0000-000000000000"
FACTOR = Numeric(18, 6)


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda m: [x.value for x in m])


class InventoryItemType(str, enum.Enum):
    STOCK = "stock"  # tracked: has quantities, movements and a cost
    CONSUMABLE = "consumable"  # tracked like stock; expensed when issued
    NON_STOCK = "non_stock"  # bought but never counted
    SERVICE = "service"  # never physical

    @property
    def is_tracked(self) -> bool:
        return self in (InventoryItemType.STOCK, InventoryItemType.CONSUMABLE)


class StockMovementType(str, enum.Enum):
    """Declared in full up front (only the first three plus REVERSAL are
    written in Phase 1) so later phases never need an enum migration."""

    OPENING_BALANCE = "opening_balance"
    ADJUSTMENT_GAIN = "adjustment_gain"
    ADJUSTMENT_LOSS = "adjustment_loss"
    REVERSAL = "reversal"
    RECEIPT = "receipt"
    ISSUE = "issue"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"


class StockSourceType(str, enum.Enum):
    """The document a movement came from. Phase 1 writes only adjustments."""

    INVENTORY_ADJUSTMENT = "inventory_adjustment"
    GOODS_RECEIPT = "goods_receipt"
    STOCK_ISSUE = "stock_issue"
    STOCK_TRANSFER = "stock_transfer"
    STOCKTAKE = "stocktake"


class InventoryAdjustmentReason(str, enum.Enum):
    OPENING_BALANCE = "opening_balance"  # increase only
    FOUND = "found"  # increase only
    DAMAGE = "damage"  # decrease only
    EXPIRY = "expiry"  # decrease only
    LOSS = "loss"  # decrease only
    WRITE_OFF = "write_off"  # decrease only
    CORRECTION = "correction"  # either direction


class InventoryAdjustmentStatus(str, enum.Enum):
    DRAFT = "draft"
    # Phase 2 (D8): an adjustment that removes stock, or adds more value
    # than the organisation's auto-approval limit, goes through approval.
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    REVERSED = "reversed"


class InventorySettings(Base, OrgScoped):
    """One row per organisation, created when inventory is switched on. A
    missing row means inventory is off (D15)."""

    __tablename__ = "inventory_settings"
    __table_args__ = (
        CheckConstraint("costing_method = 'weighted_average'", name="ck_inventory_costing_method"),
        CheckConstraint("next_adjustment_number > 0", name="ck_inventory_next_adjustment_number"),
        CheckConstraint(
            "next_po_number > 0 AND next_grn_number > 0 AND next_issue_number > 0 "
            "AND next_transfer_number > 0 AND next_stocktake_number > 0",
            name="ck_inventory_next_document_numbers",
        ),
        CheckConstraint(
            "over_receipt_tolerance_bp BETWEEN 0 AND 10000",
            name="ck_inventory_over_receipt_tolerance",
        ),
        CheckConstraint(
            "adjustment_gain_approval_limit_minor IS NULL "
            "OR adjustment_gain_approval_limit_minor >= 0",
            name="ck_inventory_adjustment_gain_limit",
        ),
        CheckConstraint(
            "NOT post_to_gl OR gl_started_at IS NOT NULL", name="ck_inventory_gl_started"
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Moving weighted average per item (D1). The only method today; stored
    # so the policy is explicit and visible rather than implied by code.
    costing_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default="weighted_average"
    )
    # Document numbering counter, advanced under this row's lock so two
    # concurrent drafts can never be given the same number.
    next_adjustment_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_po_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_grn_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_issue_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_transfer_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_stocktake_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # How far a goods receipt may exceed the ordered quantity, in basis
    # points of the ordered quantity (D4: 0 = never).
    over_receipt_tolerance_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # D8: adjustments that remove stock always need approval. Adjustments
    # that only add stock need it when their value reaches this limit;
    # NULL means gains never need approval.
    adjustment_gain_approval_limit_minor: Mapped[int | None] = mapped_column(BigInteger)
    require_issue_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_transfer_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase 3: posted documents also post journals. Once on, it stays on.
    # gl_started_at is when it was switched on; documents posted before it
    # are covered by the opening journal posted at that moment.
    post_to_gl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gl_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class InventoryCategory(Base, OrgScoped):
    __tablename__ = "inventory_categories"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_inventory_category_org_name"),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_inventory_category_parent"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_categories.id", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # D18: the expense account stock issued from this category is charged
    # to; a category without one inherits its parent's, and the top falls
    # back to inventory_consumption. A chart-of-accounts code, like
    # bills.expense_account_code.
    expense_account_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryUnit(Base, OrgScoped):
    __tablename__ = "inventory_units"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_inventory_unit_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    allows_fraction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryItem(Base, OrgScoped):
    """The item (SKU) master. Archived (is_active = false), never deleted, so
    posted history always resolves. item_type and base_unit_id are frozen
    once the item has a stock movement (enforced in the service)."""

    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("org_id", "sku", name="uq_inventory_item_org_sku"),
        CheckConstraint(
            "reorder_level IS NULL OR reorder_level >= 0", name="ck_inventory_item_reorder"
        ),
        CheckConstraint(
            "max_level IS NULL OR (max_level > 0 AND "
            "(reorder_level IS NULL OR max_level >= reorder_level))",
            name="ck_inventory_item_max_level",
        ),
        CheckConstraint(
            "default_cost_minor IS NULL OR default_cost_minor >= 0",
            name="ck_inventory_item_default_cost",
        ),
        CheckConstraint("track_lots OR NOT track_expiry", name="ck_inventory_item_expiry_lots"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    item_type: Mapped[InventoryItemType] = mapped_column(
        _enum(InventoryItemType, "inventory_item_type"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_categories.id", ondelete="RESTRICT")
    )
    base_unit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_units.id", ondelete="RESTRICT"), nullable=False
    )
    reorder_level: Mapped[Decimal | None] = mapped_column(QUANTITY)
    max_level: Mapped[Decimal | None] = mapped_column(QUANTITY)
    # Suggested unit cost (per base unit) for new stock; prefilled on
    # adjustment lines, never used to value stock already held.
    default_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    preferred_vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL")
    )
    barcode: Mapped[str | None] = mapped_column(String(64))
    # D9 (Phase 4): stock of a lot-tracked item is held per lot; with
    # track_expiry every lot also carries an expiry date. Frozen once the
    # item has stock movements, like its type and base unit.
    track_lots: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    track_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InventoryItemUnit(Base, OrgScoped):
    """An alternative unit for one item and how many base units it holds,
    e.g. CARTON = 24 PCS."""

    __tablename__ = "inventory_item_units"
    __table_args__ = (
        UniqueConstraint("item_id", "unit_id", name="uq_inventory_item_unit"),
        CheckConstraint("factor_to_base > 0", name="ck_inventory_item_unit_factor"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_units.id", ondelete="RESTRICT"), nullable=False
    )
    factor_to_base: Mapped[Decimal] = mapped_column(FACTOR, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryWarehouse(Base, OrgScoped):
    """A stock location. Optionally belongs to a branch; a branch can hold
    several warehouses, and a warehouse is not itself a branch.

    One per organisation is the system "in transit" location (is_transit):
    stock dispatched on a transfer sits there until it is received (D5), so
    the item's quantity always equals the sum of its warehouse balances.
    It is created on the first dispatch and can't be edited or chosen on a
    document."""

    __tablename__ = "inventory_warehouses"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_inventory_warehouse_org_code"),
        Index(
            "uq_inventory_warehouse_transit",
            "org_id",
            unique=True,
            postgresql_where=text("is_transit"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL")
    )
    address: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_transit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryAdjustment(Base, OrgScoped):
    """A stock adjustment document: opening balances, found stock, damage,
    expiry, loss, write-offs and corrections. Drafts change nothing;
    posting writes the stock movements; a posted adjustment is corrected by
    reversing it, never by editing."""

    __tablename__ = "inventory_adjustments"
    __table_args__ = (
        UniqueConstraint("org_id", "adjustment_number", name="uq_inventory_adjustment_number"),
        CheckConstraint(
            "status <> 'reversed' OR reversal_reason IS NOT NULL",
            name="ck_inventory_adjustment_reversal_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    adjustment_number: Mapped[str] = mapped_column(String(32), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("inventory_warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[InventoryAdjustmentReason] = mapped_column(
        _enum(InventoryAdjustmentReason, "inventory_adjustment_reason"), nullable=False
    )
    adjustment_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[InventoryAdjustmentStatus] = mapped_column(
        _enum(InventoryAdjustmentStatus, "inventory_adjustment_status"),
        nullable=False,
        default=InventoryAdjustmentStatus.DRAFT,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # When approval finished, either way (the decisions themselves live in
    # approval_instance_decisions).
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reversal_reason: Mapped[str | None] = mapped_column(String(500))


class InventoryAdjustmentLine(Base, OrgScoped):
    """One item on an adjustment. `quantity` is signed and in `unit_id`:
    positive adds stock, negative removes it. An increase carries the unit
    cost it enters at; a decrease is valued at the item's average cost when
    posted, so it carries none."""

    __tablename__ = "inventory_adjustment_lines"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "line_no", name="uq_inventory_adjustment_line_no"),
        CheckConstraint("quantity <> 0", name="ck_inventory_adjustment_line_quantity"),
        CheckConstraint(
            "(quantity > 0 AND unit_cost_minor IS NOT NULL AND unit_cost_minor >= 0) "
            "OR (quantity < 0 AND unit_cost_minor IS NULL)",
            name="ck_inventory_adjustment_line_cost",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    adjustment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("inventory_adjustments.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_units.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unit_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    # Phase 4 (D9), lot-tracked items: the lot a gain arrives as (required)
    # or a loss is taken from (optional: first-expiry-first-out otherwise).
    lot_number: Mapped[str | None] = mapped_column(String(64))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(500))


class InventoryStockMovement(Base, OrgScoped):
    """The stock ledger. Append-only (a trigger forbids UPDATE and DELETE).
    One row per stock change: signed base quantity and signed value. A
    mistake is undone by a REVERSAL row pointing at the original."""

    __tablename__ = "inventory_stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_base <> 0", name="ck_inventory_movement_quantity"),
        CheckConstraint(
            "(quantity_base > 0 AND value_minor >= 0) OR (quantity_base < 0 AND value_minor <= 0)",
            name="ck_inventory_movement_value_sign",
        ),
        CheckConstraint(
            "(movement_type = 'reversal') = (reversal_of_id IS NOT NULL)",
            name="ck_inventory_movement_reversal",
        ),
        # Posting the same document line twice is structurally impossible;
        # so is reversing one movement twice. The warehouse is part of the
        # key because a transfer line moves twice of each kind: out of the
        # source and into transit on dispatch, out of transit and into the
        # destination on receipt. The lot is part of it because one line of
        # a lot-tracked item can move several lots (Phase 4).
        Index(
            "uq_inventory_movement_source_line",
            "org_id",
            "source_type",
            "source_line_id",
            "movement_type",
            "warehouse_id",
            text(f"coalesce(lot_id, '{NO_LOT}'::uuid)"),
            unique=True,
        ),
        Index("uq_inventory_movement_reversal_of", "reversal_of_id", unique=True),
        Index(
            "ix_inventory_movements_item_wh_date", "org_id", "item_id", "warehouse_id", "entry_date"
        ),
        Index("ix_inventory_movements_source", "org_id", "source_type", "source_id"),
        # Phase 5: the movement list's order (newest first, walked backwards)
        # and date-bounded reports; the overview's latest-posted feed.
        Index("ix_inventory_movements_org_date", "org_id", "entry_date", "created_at", "id"),
        Index("ix_inventory_movements_org_created", "org_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("inventory_warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    movement_type: Mapped[StockMovementType] = mapped_column(
        _enum(StockMovementType, "inventory_movement_type"), nullable=False
    )
    quantity_base: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    # Authoritative signed value. unit_cost_minor is the per-base-unit cost
    # it implies, rounded, for display only.
    value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[StockSourceType] = mapped_column(
        _enum(StockSourceType, "inventory_source_type"), nullable=False
    )
    # Polymorphic pointers at the originating document and line — no FK,
    # same reasoning as journal_entries.source_id.
    source_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_line_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_stock_movements.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    # Phase 4 (D9): the lot moved, for a lot-tracked item; NULL otherwise.
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_lots.id", ondelete="RESTRICT")
    )
    posted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryStockBalance(Base, OrgScoped):
    """Quantity on hand per item and warehouse: the running sum of that
    pair's movements. Value is not held per warehouse — the item has one
    average cost (D1), so a warehouse's value is quantity x that average."""

    __tablename__ = "inventory_stock_balances"
    __table_args__ = (
        UniqueConstraint("item_id", "warehouse_id", name="uq_inventory_balance_item_warehouse"),
        CheckConstraint("quantity_base >= 0", name="ck_inventory_balance_not_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("inventory_warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity_base: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InventoryItemCost(Base, OrgScoped):
    """The item's weighted-average cost pool across all warehouses: total
    quantity and total value. Locked FOR UPDATE by every posting that
    touches the item, which also serialises those postings."""

    __tablename__ = "inventory_item_costs"
    __table_args__ = (
        CheckConstraint("quantity_base >= 0", name="ck_inventory_cost_quantity"),
        CheckConstraint("value_minor >= 0", name="ck_inventory_cost_value"),
        CheckConstraint(
            "quantity_base > 0 OR value_minor = 0", name="ck_inventory_cost_no_orphan_value"
        ),
        # Phase 5: the overview's totals read one organisation's pools.
        Index("ix_inventory_item_costs_org", "org_id"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    quantity_base: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=Decimal(0))
    value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
