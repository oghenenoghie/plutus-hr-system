import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.document_template import DocumentTemplate
from app.models.employee import Employee
from app.models.generated_document import GeneratedDocument
from app.models.membership import Role
from app.models.organisation import Organisation
from app.schemas.document_generation import (
    DocumentTemplateCreate,
    DocumentTemplateOut,
    GeneratedDocumentOut,
    GenerateDocumentRequest,
    SignDocumentRequest,
)
from app.services.document_generation import generate_document, send_for_signature, sign_document
from app.services.generated_document_pdf import render_generated_document_pdf

router = APIRouter(tags=["document-generation"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)


def _get_template_or_404(db: Session, template_id: uuid.UUID) -> DocumentTemplate:
    template = db.get(DocumentTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
    return template


def _get_employee_or_404(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    return employee


def _get_document_or_404(db: Session, document_id: uuid.UUID) -> GeneratedDocument:
    document = db.get(GeneratedDocument, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return document


@router.post(
    "/document-templates", response_model=DocumentTemplateOut, status_code=status.HTTP_201_CREATED
)
def create_template(
    body: DocumentTemplateCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> DocumentTemplate:
    template = DocumentTemplate(org_id=claims.org_id, **body.model_dump())
    db.add(template)
    db.flush()
    return template


@router.get("/document-templates", response_model=list[DocumentTemplateOut])
def list_templates(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[DocumentTemplate]:
    return list(db.scalars(select(DocumentTemplate)))


@router.post(
    "/employees/{employee_id}/generated-documents",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_generated_document(
    employee_id: uuid.UUID,
    body: GenerateDocumentRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> GeneratedDocument:
    employee = _get_employee_or_404(db, employee_id)
    template = _get_template_or_404(db, body.template_id)
    organisation = db.get(Organisation, claims.org_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organisation not found")
    return generate_document(
        db,
        org_id=claims.org_id,
        template=template,
        employee=employee,
        organisation=organisation,
        extra_context=body.extra_context,
    )


@router.get(
    "/employees/{employee_id}/generated-documents", response_model=list[GeneratedDocumentOut]
)
def list_generated_documents(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[GeneratedDocument]:
    _get_employee_or_404(db, employee_id)
    return list(
        db.scalars(
            select(GeneratedDocument)
            .where(GeneratedDocument.employee_id == employee_id)
            .order_by(GeneratedDocument.created_at)
        )
    )


@router.get("/generated-documents/me", response_model=list[GeneratedDocumentOut])
def list_my_generated_documents(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[GeneratedDocument]:
    return list(
        db.scalars(
            select(GeneratedDocument)
            .where(GeneratedDocument.employee_id == employee.id)
            .order_by(GeneratedDocument.created_at)
        )
    )


@router.post("/generated-documents/{document_id}/send", response_model=GeneratedDocumentOut)
def send_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> GeneratedDocument:
    document = _get_document_or_404(db, document_id)
    try:
        return send_for_signature(db, document)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/generated-documents/{document_id}/sign", response_model=GeneratedDocumentOut)
def sign(
    document_id: uuid.UUID,
    body: SignDocumentRequest,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> GeneratedDocument:
    document = _get_document_or_404(db, document_id)
    if document.employee_id != employee.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not authorised to sign this document"
        )
    try:
        return sign_document(db, document, signed_by_name=body.signed_by_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/generated-documents/{document_id}/pdf")
def download_generated_document_pdf(
    document_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Response:
    document = _get_document_or_404(db, document_id)
    if claims.role not in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value, Role.ACCOUNTANT.value):
        employee = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        if employee is None or document.employee_id != employee.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not authorised to view this document",
            )
    pdf_bytes = render_generated_document_pdf(document)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{document.document_type.value}.pdf"'
        },
    )
