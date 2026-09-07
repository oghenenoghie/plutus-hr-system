import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
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
    __table_args__ = (UniqueConstraint("org_id", "bill_number", name="uq_bill_org_number"),)

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
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus, name="bill_status", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
        default=BillStatus.DRAFT,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
