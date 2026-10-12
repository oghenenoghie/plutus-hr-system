"""Inventory accounting (Phase 3, docs/architecture/inventory-integration.md
§15): the journals inventory documents post, through the one posting engine
(app/services/posting.py), in the same transaction as their stock
movements. A refused journal (locked period, missing or inactive account)
therefore refuses the whole posting: stock and the GL never disagree.

What posts, valued by the stock movements themselves:

| Event | Debit | Credit |
|---|---|---|
| Goods receipt | inventory | grni |
| Stock issue | category expense (D18) | inventory |
| Adjustment gain | inventory | inventory_adjustment (opening balances: inventory_opening_balance) |
| Adjustment loss / write-off | inventory_adjustment | inventory |
| Transfer | nothing: value-neutral pairs net to zero | |
| Transit loss | inventory_adjustment | inventory |
| Reversal | the original journal mirrored (reverse_journal), plus a cost variance to inventory_adjustment when today's average differs | |

Nothing posts while an organisation's inventory accounting is off
(inventory_settings.post_to_gl). Switching it on (start_gl_posting) posts
the stock already held as an opening balance.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.inventory.accounting import (
    ADJUSTMENT_ACCOUNT,
    CONSUMPTION_ACCOUNT,
    GRNI_ACCOUNT,
    INVENTORY_ACCOUNT,
    OPENING_BALANCE_ACCOUNT,
    Leg,
    counter_legs,
    journal_lines,
    reversal_variance_legs,
)
from app.models.bill import Bill, BillStatus
from app.models.inventory import (
    InventoryAdjustment,
    InventoryAdjustmentReason,
    InventoryCategory,
    InventoryItem,
    InventoryItemCost,
    InventorySettings,
    InventoryStockMovement,
    StockSourceType,
)
from app.models.inventory_control import InventoryStocktake
from app.models.inventory_documents import (
    GoodsReceiptStatus,
    InventoryGoodsReceipt,
    InventoryPurchaseOrder,
)
from app.models.journal_entry import JournalEntry, JournalSourceType
from app.models.ledger import LedgerEntry
from app.services.accounting_periods import lock_date
from app.services.chart_accounts import seed_inventory_accounts
from app.services.inventory import get_inventory_settings
from app.services.posting import post_journal, reverse_journal, today_lagos

POSTED = "posted"
REVERSAL_VARIANCE = "reversal_variance"
REVERSED = "reversed"
OPENING_EVENT = "inventory.opening"

JOURNAL_SOURCE: dict[StockSourceType, JournalSourceType] = {
    StockSourceType.GOODS_RECEIPT: JournalSourceType.GOODS_RECEIPT,
    StockSourceType.STOCK_ISSUE: JournalSourceType.STOCK_ISSUE,
    StockSourceType.INVENTORY_ADJUSTMENT: JournalSourceType.STOCK_ADJUSTMENT,
    StockSourceType.STOCK_TRANSFER: JournalSourceType.STOCK_TRANSFER,
    StockSourceType.STOCKTAKE: JournalSourceType.STOCKTAKE,
}


def gl_posting_on(db: Session, *, org_id: uuid.UUID) -> bool:
    return bool(get_inventory_settings(db, org_id=org_id).post_to_gl)


def _delta(movements: Sequence[InventoryStockMovement]) -> int:
    return sum(movement.value_minor for movement in movements)


def _post(
    db: Session,
    *,
    org_id: uuid.UUID,
    entry_date: date,
    source_type: JournalSourceType,
    source_id: uuid.UUID,
    source_event: str,
    description: str,
    reference: str | None,
    legs: Sequence[Leg],
    actor_account_id: uuid.UUID | None,
) -> JournalEntry | None:
    """Posts the legs as one journal, or nothing when they net to zero
    (e.g. a transfer, or zero-cost stock)."""
    lines = journal_lines(legs)
    if not lines:
        return None
    return post_journal(
        db,
        org_id=org_id,
        entry_date=entry_date,
        source_type=source_type,
        source_id=source_id,
        source_event=source_event,
        description=description,
        reference=reference,
        lines=lines,
        actor_account_id=actor_account_id,
    )


# --- posting events -----------------------------------------------------------


def post_receipt_journal(
    db: Session,
    *,
    org_id: uuid.UUID,
    receipt_id: uuid.UUID,
    receipt_number: str,
    order_number: str,
    entry_date: date,
    movements: Sequence[InventoryStockMovement],
    actor_account_id: uuid.UUID | None,
) -> JournalEntry | None:
    """Dr inventory / Cr goods-received-not-invoiced, at the receipt's net
    value (D2). The vendor bill clears the accrual."""
    if not gl_posting_on(db, org_id=org_id):
        return None
    return _post(
        db,
        org_id=org_id,
        entry_date=entry_date,
        source_type=JournalSourceType.GOODS_RECEIPT,
        source_id=receipt_id,
        source_event=POSTED,
        description=f"{receipt_number}: goods received against {order_number}",
        reference=receipt_number,
        legs=counter_legs(_delta(movements), GRNI_ACCOUNT),
        actor_account_id=actor_account_id,
    )


def issue_expense_account(db: Session, item_id: uuid.UUID, cache: dict[uuid.UUID, str]) -> str:
    """D18: the expense account of the item's category, else of the nearest
    ancestor category that has one, else inventory_consumption."""
    if item_id in cache:
        return cache[item_id]
    item = db.get(InventoryItem, item_id)
    account = CONSUMPTION_ACCOUNT
    category_id = item.category_id if item is not None else None
    seen: set[uuid.UUID] = set()
    while category_id is not None and category_id not in seen:
        seen.add(category_id)
        category = db.get(InventoryCategory, category_id)
        if category is None:
            break
        if category.expense_account_code:
            account = category.expense_account_code
            break
        category_id = category.parent_id
    cache[item_id] = account
    return account


def post_issue_journal(
    db: Session,
    *,
    org_id: uuid.UUID,
    issue_id: uuid.UUID,
    issue_number: str,
    purpose: str,
    entry_date: date,
    movements: Sequence[InventoryStockMovement],
    actor_account_id: uuid.UUID | None,
) -> JournalEntry | None:
    """Dr each line's expense account (D18) / Cr inventory, at the value the
    stock left at (the moving average)."""
    if not gl_posting_on(db, org_id=org_id):
        return None
    cache: dict[uuid.UUID, str] = {}
    legs: list[Leg] = []
    for movement in movements:
        legs.append(Leg(INVENTORY_ACCOUNT, movement.value_minor))
        legs.append(Leg(issue_expense_account(db, movement.item_id, cache), -movement.value_minor))
    return _post(
        db,
        org_id=org_id,
        entry_date=entry_date,
        source_type=JournalSourceType.STOCK_ISSUE,
        source_id=issue_id,
        source_event=POSTED,
        description=f"{issue_number}: stock issued — {purpose}",
        reference=issue_number,
        legs=legs,
        actor_account_id=actor_account_id,
    )


def adjustment_counter_account(reason: InventoryAdjustmentReason) -> str:
    """Opening balances bring existing stock onto the books against equity;
    every other gain or loss is an adjustment."""
    if reason == InventoryAdjustmentReason.OPENING_BALANCE:
        return OPENING_BALANCE_ACCOUNT
    return ADJUSTMENT_ACCOUNT


def post_adjustment_journal(
    db: Session,
    *,
    adjustment: InventoryAdjustment,
    movements: Sequence[InventoryStockMovement],
    actor_account_id: uuid.UUID | None,
) -> JournalEntry | None:
    if not gl_posting_on(db, org_id=adjustment.org_id):
        return None
    return _post(
        db,
        org_id=adjustment.org_id,
        entry_date=adjustment.adjustment_date,
        source_type=JournalSourceType.STOCK_ADJUSTMENT,
        source_id=adjustment.id,
        source_event=POSTED,
        description=(
            f"{adjustment.adjustment_number}: stock adjustment "
            f"({adjustment.reason.value.replace('_', ' ')})"
        ),
        reference=adjustment.adjustment_number,
        legs=counter_legs(_delta(movements), adjustment_counter_account(adjustment.reason)),
        actor_account_id=actor_account_id,
    )


def post_stocktake_journal(
    db: Session,
    *,
    stocktake: InventoryStocktake,
    movements: Sequence[InventoryStockMovement],
    actor_account_id: uuid.UUID | None,
) -> JournalEntry | None:
    """A count's net variance against inventory_adjustment: stock found
    Dr inventory / Cr inventory_adjustment, stock missing the reverse."""
    if not gl_posting_on(db, org_id=stocktake.org_id):
        return None
    return _post(
        db,
        org_id=stocktake.org_id,
        entry_date=stocktake.count_date,
        source_type=JournalSourceType.STOCKTAKE,
        source_id=stocktake.id,
        source_event=POSTED,
        description=f"{stocktake.stocktake_number}: stocktake variance",
        reference=stocktake.stocktake_number,
        legs=counter_legs(_delta(movements), ADJUSTMENT_ACCOUNT),
        actor_account_id=actor_account_id,
    )


def post_transfer_journal(
    db: Session,
    *,
    org_id: uuid.UUID,
    transfer_id: uuid.UUID,
    transfer_number: str,
    source_event: str,
    entry_date: date,
    movements: Sequence[InventoryStockMovement],
    actor_account_id: uuid.UUID | None,
) -> JournalEntry | None:
    """A transfer's out/in pairs are value-neutral, so only a transit loss
    (stock written off from transit at receipt) reaches the GL:
    Dr inventory_adjustment / Cr inventory."""
    if not gl_posting_on(db, org_id=org_id):
        return None
    return _post(
        db,
        org_id=org_id,
        entry_date=entry_date,
        source_type=JournalSourceType.STOCK_TRANSFER,
        source_id=transfer_id,
        source_event=source_event,
        description=f"{transfer_number}: stock lost in transit",
        reference=transfer_number,
        legs=counter_legs(_delta(movements), ADJUSTMENT_ACCOUNT),
        actor_account_id=actor_account_id,
    )


def _posting_journal(
    db: Session, *, org_id: uuid.UUID, source_type: JournalSourceType, source_id: uuid.UUID
) -> JournalEntry | None:
    return db.scalar(
        select(JournalEntry).where(
            JournalEntry.org_id == org_id,
            JournalEntry.source_type == source_type,
            JournalEntry.source_id == source_id,
            JournalEntry.source_event == POSTED,
        )
    )


def _account_net(db: Session, *, journal_id: uuid.UUID, account: str) -> int:
    """Debits less credits on one account within one journal."""
    return int(
        db.scalar(
            select(
                func.coalesce(func.sum(LedgerEntry.debit_minor - LedgerEntry.credit_minor), 0)
            ).where(LedgerEntry.journal_entry_id == journal_id, LedgerEntry.account == account)
        )
        or 0
    )


def post_reversal_journal(
    db: Session,
    *,
    org_id: uuid.UUID,
    stock_source: StockSourceType,
    source_id: uuid.UUID,
    document_number: str,
    posted_at: datetime | None,
    reason: str,
    movements: Sequence[InventoryStockMovement],
    actor_account_id: uuid.UUID | None,
) -> None:
    """The GL side of a document reversal, dated today like its movements.

    When the document posted a journal, that journal is mirrored through
    reverse_journal (linked by reversal_of_id), and any cost variance gets
    its own journal. A document posted before inventory accounting started
    has no journal: its stock was brought onto the books by the opening
    journal, so its reversal is taken back through the opening balance."""
    settings = get_inventory_settings(db, org_id=org_id)
    if not settings.post_to_gl:
        return
    source_type = JOURNAL_SOURCE[stock_source]
    actual = _delta(movements)
    today = today_lagos()
    original = _posting_journal(db, org_id=org_id, source_type=source_type, source_id=source_id)
    if original is not None:
        mirrored = -_account_net(db, journal_id=original.id, account=INVENTORY_ACCOUNT)
        reverse_journal(
            db,
            org_id=org_id,
            journal_id=original.id,
            reversal_date=today,
            reason=reason,
            actor_account_id=actor_account_id,
        )
        _post(
            db,
            org_id=org_id,
            entry_date=today,
            source_type=source_type,
            source_id=source_id,
            source_event=REVERSAL_VARIANCE,
            description=f"{document_number}: cost variance on reversal",
            reference=document_number,
            legs=reversal_variance_legs(actual, mirrored),
            actor_account_id=actor_account_id,
        )
        return
    started = settings.gl_started_at
    before_gl = posted_at is None or started is None or posted_at < started
    _post(
        db,
        org_id=org_id,
        entry_date=today,
        source_type=source_type,
        source_id=source_id,
        source_event=REVERSED,
        description=f"{document_number}: reversed ({reason})",
        reference=document_number,
        legs=counter_legs(actual, OPENING_BALANCE_ACCOUNT if before_gl else ADJUSTMENT_ACCOUNT),
        actor_account_id=actor_account_id,
    )


# --- switching accounting on -------------------------------------------------


def stock_value_minor(db: Session, *, org_id: uuid.UUID) -> int:
    """Total value of the stock held, in transit included: the sum of the
    items' cost pools."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(InventoryItemCost.value_minor), 0)).where(
                InventoryItemCost.org_id == org_id
            )
        )
        or 0
    )


def start_gl_posting(
    db: Session, *, settings: InventorySettings, actor_account_id: uuid.UUID | None
) -> JournalEntry | None:
    """Switches inventory accounting on for an organisation that has been
    moving stock without journals. Seeds the inventory accounts and posts
    the stock already held as an opening balance (Dr inventory /
    Cr inventory_opening_balance), dated today. One-way: the books can't be
    made to forget journals already posted. Call with the settings row
    locked (inventory_common.lock_settings)."""
    if settings.post_to_gl:
        raise ValueError("inventory accounting is already on")
    seed_inventory_accounts(db, org_id=settings.org_id)
    settings.post_to_gl = True
    settings.gl_started_at = datetime.now(UTC)
    settings.updated_by = actor_account_id
    db.flush()
    return _post(
        db,
        org_id=settings.org_id,
        entry_date=today_lagos(),
        source_type=JournalSourceType.OPENING_BALANCE,
        source_id=settings.org_id,
        source_event=OPENING_EVENT,
        description="Inventory opening balance: stock held when inventory accounting started",
        reference=None,
        legs=counter_legs(stock_value_minor(db, org_id=settings.org_id), OPENING_BALANCE_ACCOUNT),
        actor_account_id=actor_account_id,
    )


# --- goods receipts and bills (D2) ---------------------------------------------


def receipt_accrual_minor(db: Session, *, org_id: uuid.UUID, receipt_id: uuid.UUID) -> int | None:
    """What a goods receipt accrued to goods-received-not-invoiced, or None
    when it posted no journal (posted before inventory accounting started,
    or held no stock value)."""
    journal = _posting_journal(
        db, org_id=org_id, source_type=JournalSourceType.GOODS_RECEIPT, source_id=receipt_id
    )
    if journal is None:
        return None
    return -_account_net(db, journal_id=journal.id, account=GRNI_ACCOUNT)


def billable_receipt(
    db: Session,
    *,
    org_id: uuid.UUID,
    receipt_id: uuid.UUID,
    vendor_id: uuid.UUID,
    bill_id: uuid.UUID | None = None,
) -> tuple[InventoryGoodsReceipt, int]:
    """The receipt a bill may be linked to, with its accrual. Raises
    ValueError when it isn't posted, accrued nothing, belongs to another
    vendor, or is billed by a bill other than `bill_id`."""
    receipt = db.get(InventoryGoodsReceipt, receipt_id)
    if receipt is None or receipt.org_id != org_id:
        raise ValueError("goods receipt not found")
    if receipt.status != GoodsReceiptStatus.POSTED:
        raise ValueError(f"{receipt.grn_number} is {receipt.status.value}, not posted")
    order = db.get(InventoryPurchaseOrder, receipt.purchase_order_id)
    if order is None or order.vendor_id != vendor_id:
        raise ValueError(f"{receipt.grn_number} is from a different vendor")
    other = receipt_bill(db, receipt_id=receipt.id)
    if other is not None and other.id != bill_id:
        raise ValueError(f"{receipt.grn_number} is already billed by bill {other.bill_number}")
    accrual = receipt_accrual_minor(db, org_id=org_id, receipt_id=receipt.id)
    if not accrual:
        raise ValueError(
            f"{receipt.grn_number} accrued nothing to goods received not invoiced "
            "(it holds no stock value, or was posted before inventory accounting started); "
            "bill it without linking it"
        )
    return receipt, accrual


def receipt_bill(db: Session, *, receipt_id: uuid.UUID) -> Bill | None:
    """The bill (not void) that invoices a goods receipt, if any."""
    return db.scalar(
        select(Bill).where(Bill.goods_receipt_id == receipt_id, Bill.status != BillStatus.VOID)
    )


# --- reconciliation ------------------------------------------------------------


def _gl_net(db: Session, *, org_id: uuid.UUID, account: str) -> int:
    return int(
        db.scalar(
            select(
                func.coalesce(func.sum(LedgerEntry.debit_minor - LedgerEntry.credit_minor), 0)
            ).where(LedgerEntry.org_id == org_id, LedgerEntry.account == account)
        )
        or 0
    )


def unbilled_accruals_minor(db: Session, *, org_id: uuid.UUID) -> tuple[int, int]:
    """(count, total) of posted goods receipts whose accrual no approved or
    paid bill has cleared: what goods-received-not-invoiced should hold."""
    receipts = db.scalars(
        select(InventoryGoodsReceipt.id).where(
            InventoryGoodsReceipt.org_id == org_id,
            InventoryGoodsReceipt.status == GoodsReceiptStatus.POSTED,
        )
    ).all()
    count = 0
    total = 0
    for receipt_id in receipts:
        bill = receipt_bill(db, receipt_id=receipt_id)
        if bill is not None and bill.status in (BillStatus.APPROVED, BillStatus.PAID):
            continue
        accrual = receipt_accrual_minor(db, org_id=org_id, receipt_id=receipt_id)
        if accrual:
            count += 1
            total += accrual
    return count, total


def reconciliation(db: Session, *, org_id: uuid.UUID) -> dict[str, Any]:
    """Inventory against the GL: stock value (the cost pools) against the
    inventory account, and unbilled receipt accruals against the
    goods-received-not-invoiced account. Both differences are zero while
    every stock change has posted its journal."""
    settings = get_inventory_settings(db, org_id=org_id)
    stock_value = stock_value_minor(db, org_id=org_id)
    gl_inventory = _gl_net(db, org_id=org_id, account=INVENTORY_ACCOUNT)
    unbilled_count, unbilled_total = unbilled_accruals_minor(db, org_id=org_id)
    gl_grni = -_gl_net(db, org_id=org_id, account=GRNI_ACCOUNT)
    return {
        "post_to_gl": settings.post_to_gl,
        "gl_started_at": settings.gl_started_at,
        "lock_date": lock_date(db, org_id=org_id),
        "stock_value_minor": stock_value,
        "gl_inventory_minor": gl_inventory,
        "inventory_difference_minor": gl_inventory - stock_value,
        "unbilled_receipts": unbilled_count,
        "unbilled_receipts_minor": unbilled_total,
        "gl_grni_minor": gl_grni,
        "grni_difference_minor": gl_grni - unbilled_total,
    }


def document_journal_ids(
    db: Session, *, org_id: uuid.UUID, source_type: JournalSourceType, source_id: uuid.UUID
) -> list[uuid.UUID]:
    """Every journal a document produced, oldest first: its own (posting,
    variance, transit loss) and the reversals of them."""
    own = select(JournalEntry.id).where(
        JournalEntry.org_id == org_id,
        JournalEntry.source_type == source_type,
        JournalEntry.source_id == source_id,
    )
    return list(
        db.scalars(
            select(JournalEntry.id)
            .where(
                JournalEntry.org_id == org_id,
                (JournalEntry.id.in_(own)) | (JournalEntry.reversal_of_id.in_(own)),
            )
            .order_by(JournalEntry.created_at, JournalEntry.reversal_of_id.is_not(None))
        )
    )
