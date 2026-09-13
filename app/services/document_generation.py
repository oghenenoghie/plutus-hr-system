import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.domain.document_templates import render_template
from app.models.document_template import DocumentTemplate
from app.models.employee import Employee
from app.models.generated_document import GeneratedDocument, GeneratedDocumentStatus
from app.models.organisation import Organisation


def _employee_context(employee: Employee, organisation: Organisation) -> dict[str, str]:
    return {
        "full_name": employee.full_name,
        "employee_number": employee.employee_number,
        "job_title": employee.job_title or "",
        "state_of_residence": employee.state_of_residence,
        "date_of_joining": employee.date_of_joining.isoformat(),
        "org_name": organisation.name,
        "today": datetime.now(UTC).date().isoformat(),
    }


def generate_document(
    db: Session,
    *,
    org_id: uuid.UUID,
    template: DocumentTemplate,
    employee: Employee,
    organisation: Organisation,
    extra_context: dict[str, str] | None = None,
) -> GeneratedDocument:
    context = _employee_context(employee, organisation)
    context.update(extra_context or {})
    rendered_content = render_template(template.body_template, context)

    document = GeneratedDocument(
        org_id=org_id,
        template_id=template.id,
        employee_id=employee.id,
        document_type=template.document_type,
        rendered_content=rendered_content,
    )
    db.add(document)
    db.flush()
    return document


def send_for_signature(db: Session, document: GeneratedDocument) -> GeneratedDocument:
    if document.status != GeneratedDocumentStatus.DRAFT:
        raise ValueError(f"document is already {document.status.value}")
    document.status = GeneratedDocumentStatus.SENT_FOR_SIGNATURE
    document.sent_at = datetime.now(UTC)
    db.add(document)
    db.flush()
    return document


def sign_document(
    db: Session, document: GeneratedDocument, *, signed_by_name: str
) -> GeneratedDocument:
    if document.status != GeneratedDocumentStatus.SENT_FOR_SIGNATURE:
        raise ValueError(
            f"document must be sent for signature before it can be signed "
            f"(it is {document.status.value})"
        )
    if not signed_by_name.strip():
        raise ValueError("signed_by_name must not be blank")
    document.status = GeneratedDocumentStatus.SIGNED
    document.signed_at = datetime.now(UTC)
    document.signed_by_name = signed_by_name.strip()
    db.add(document)
    db.flush()
    return document
