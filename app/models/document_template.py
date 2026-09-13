import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentType(str, enum.Enum):
    OFFER_LETTER = "offer_letter"
    CONFIRMATION_LETTER = "confirmation_letter"
    EMPLOYMENT_CONTRACT = "employment_contract"
    SALARY_CERTIFICATE = "salary_certificate"
    OTHER = "other"


class DocumentTemplate(Base):
    """An org-authored template for one kind of HR document.
    body_template holds {{placeholder}} tokens (see
    app.domain.document_templates.render_template) filled from the
    employee's own record plus whatever extra_context the caller supplies
    when generating (a proposed start date for an offer letter, say) —
    there's no rigid per-document-type schema, since the reference gives
    none to encode.
    """

    __tablename__ = "document_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(
            DocumentType,
            name="document_template_type",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
