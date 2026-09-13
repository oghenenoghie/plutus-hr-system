import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.document_template import DocumentType


class GeneratedDocumentStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT_FOR_SIGNATURE = "sent_for_signature"
    SIGNED = "signed"


class GeneratedDocument(Base):
    """One rendered document for one employee. document_type and
    rendered_content are captured at generation time and never re-derived
    from the template afterwards — a later edit to the template must not
    change what an already-issued offer letter said. Signing is a
    lightweight click-to-sign: the employee types their full name to
    confirm (signed_by_name), recorded with a timestamp — not a
    cryptographic signature, since nothing in this codebase implements
    one.
    """

    __tablename__ = "generated_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(
            DocumentType,
            name="generated_document_type",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    rendered_content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GeneratedDocumentStatus] = mapped_column(
        Enum(
            GeneratedDocumentStatus,
            name="generated_document_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=GeneratedDocumentStatus.DRAFT,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_name: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
