import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AccountingSettings(Base):
    """One row per organisation, absent until someone sets a flag. Holds the
    switches that gate *new* ledger behaviour, per
    ACCOUNTING_IMPLEMENTATION_AUDIT.md §26.4: off for an organisation that
    existed before the behaviour shipped (it may already have journaled the
    same event by hand, and an automatic posting would double-count it),
    on for an organisation created afterwards.

    A missing row means every flag is off.
    """

    __tablename__ = "accounting_settings"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Marking a statutory liability remitted posts Dr <scheme>_payable /
    # Cr cash. Going forward only — remittances recorded before this was
    # switched on are never back-posted (audit A8).
    post_statutory_remittances: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # D13 (interim period control): no journal may be dated on or before
    # this day. Enforced by every journal writer that goes through
    # app/services/posting.py or post_manual_journal_entry, and by the
    # inventory stock-posting engine. NULL means nothing is locked.
    lock_date: Mapped[date | None] = mapped_column(Date)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
