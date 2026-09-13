import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, func
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
    """Metadata for one document held on an employee's file (a scanned ID,
    signed contract, certificate, ...). This app doesn't host the file
    bytes itself — storage_url points at wherever they actually live (an
    object store the deploying org configures), the same "reference to an
    external thing" shape PayslipDelivery uses for its provider_message_id.
    expiry_date is optional and only meaningful for documents that expire
    (a work permit, a certification) — most don't.
    """

    __tablename__ = "employee_documents"

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
    storage_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
