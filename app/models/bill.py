import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BillStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PAID = "paid"
    VOID = "void"


class Bill(Base):
    """An accounts-payable bill from a Vendor. `expense_account_code`
    names which chart-of-accounts expense line this bill's cost belongs
    to (office supplies, professional fees, ...) — chosen at creation
    since only the person entering the bill knows what it's actually for.
    Lifecycle is deliberately narrow for this first pass: draft -> approve
    (posts the expense/payable) -> pay (clears the payable to cash); void
    is only reachable from draft, before anything has posted to the
    ledger — voiding an already-approved bill would need a reversing
    entry, left for a later pass.
    """

    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint("org_id", "bill_number", name="uq_bill_org_number"),
        Index(
            "uq_bill_goods_receipt",
            "goods_receipt_id",
            unique=True,
            postgresql_where=text("goods_receipt_id IS NOT NULL AND status <> 'void'"),
        ),
        CheckConstraint(
            "vat_treatment IS NULL OR vat_treatment IN ('standard', 'exempt', 'zero_rated', 'other')",
            name="ck_bills_vat_treatment",
        ),
        CheckConstraint(
            "vat_rate_ppm BETWEEN 0 AND 1000000 AND vat_minor >= 0",
            name="ck_bills_vat_figures",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )

    bill_number: Mapped[str] = mapped_column(String(64), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    expense_account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # How VAT applies to the bill, as on a customer invoice
    # (app.domain.accounting.vat.VatTreatment): the rate's name as printed
    # and the rate, stored so a later change in the law never alters a bill
    # already entered. vat_minor is then worked out from amount_minor and the
    # rate. A bill with no treatment carries the VAT amount entered by hand,
    # as bills did before the treatment was recorded. Either way the VAT is
    # recoverable input VAT (vat_receivable), not part of the expense.
    vat_treatment: Mapped[str | None] = mapped_column(String(16))
    vat_rate_name: Mapped[str | None] = mapped_column(String(64))
    vat_rate_ppm: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    vat_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Set at creation to opt this bill into withholding tax at approval —
    # None means WHT doesn't apply (e.g. a utility bill below threshold).
    # Uses the same category-rated WhtRule contractor payments already do
    # (nigeria-statutory-compliance.md §8) — never a flat rate.
    wht_category: Mapped[str | None] = mapped_column(String(64))
    wht_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # D2: the goods receipt this bill invoices. Approving the bill clears
    # the receipt's goods-received-not-invoiced accrual instead of
    # expensing that part of the amount (app/services/bills.py).
    goods_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "inventory_goods_receipts.id", ondelete="RESTRICT", name="fk_bills_goods_receipt_id"
        ),
    )
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus, name="bill_status", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
        default=BillStatus.DRAFT,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def total_minor(self) -> int:
        """The bill's total as the vendor invoiced it: amount plus VAT."""
        return self.amount_minor + self.vat_minor

    @property
    def net_payable_minor(self) -> int:
        """What's actually owed to the vendor: the bill amount plus VAT
        charged, less any tax withheld at source (paid to the NRS
        instead, see approve_bill)."""
        return self.amount_minor + self.vat_minor - self.wht_amount_minor
