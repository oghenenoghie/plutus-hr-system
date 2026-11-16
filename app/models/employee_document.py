import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentCategory(str, enum.Enum):
    IDENTIFICATION = "identification"
    CONTRACT = "contract"
    CERTIFICATE = "certificate"
    OFFER_LETTER = "offer_letter"
    OTHER = "other"


class EmployeeDocument(Base):
    """One document held on an employee's file (a scanned ID, signed
    contract, certificate, ...). Either a file uploaded to the app's own
    object storage (storage_key, with its name, type and size; the link to
    it is signed afresh each time it's listed, never stored), or a link to
    wherever the file already lives (storage_url). expiry_date is optional
    and only meaningful for documents that expire (a work permit, a
    certification) — most don't.
    """

    __tablename__ = "employee_documents"
    __table_args__ = (
        CheckConstraint(
            "storage_url IS NOT NULL OR storage_key IS NOT NULL",
            name="ck_employee_documents_has_file",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[DocumentCategory] = mapped_column(
        Enum(
            DocumentCategory,
            name="document_category",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_url: Mapped[str | None] = mapped_column(String(2000))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
