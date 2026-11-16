import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.employee_document import DocumentCategory, EmployeeDocument
from app.models.membership import Role
from app.schemas.employee_documents import (
    EmployeeDocumentCreate,
    EmployeeDocumentOut,
    EmployeeDocumentUpdate,
)
from app.services.audit import record_audit_event
from app.services.employee_documents import (
    MAX_DOCUMENT_BYTES,
    InvalidDocumentError,
    document_url,
    upload_employee_document,
)

router = APIRouter(prefix="/employees", tags=["employee-documents"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT, Role.HR_MANAGER)


def _get_employee_or_404(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    return employee


def _get_document_or_404(db: Session, document_id: uuid.UUID) -> EmployeeDocument:
    document = db.get(EmployeeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return document


def _out(document: EmployeeDocument, request: Request) -> EmployeeDocumentOut:
    """The document with a link to open it, signed afresh for an uploaded
    file (never stored, never public)."""
    out = EmployeeDocumentOut.model_validate(document)
    out.storage_url = document_url(document, base_url=str(request.base_url).rstrip("/"))
    return out


@router.post(
    "/{employee_id}/documents",
    response_model=EmployeeDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    employee_id: uuid.UUID,
    body: EmployeeDocumentCreate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EmployeeDocumentOut:
    """Records a document by a link to wherever the file already lives."""
    _get_employee_or_404(db, employee_id)
    document = EmployeeDocument(
        org_id=claims.org_id,
        employee_id=employee_id,
        uploaded_by=claims.account_id,
        **body.model_dump(),
    )
    db.add(document)
    db.flush()
    return _out(document, request)


@router.post(
    "/{employee_id}/documents/upload",
    response_model=EmployeeDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    employee_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
    file: UploadFile = File(...),
    category: DocumentCategory = Form(...),
    title: str = Form(...),
    expiry_date: date | None = Form(None),
) -> EmployeeDocumentOut:
    """Uploads a file from the person's computer or phone (a PDF, a photo
    or scan, or a Word document) to the employee's record."""
    employee = _get_employee_or_404(db, employee_id)
    # One byte past the limit is enough to know the file is too big.
    data = file.file.read(MAX_DOCUMENT_BYTES + 1)
    try:
        document = upload_employee_document(
            db,
            employee=employee,
            uploaded_by=claims.account_id,
            category=category,
            title=title,
            expiry_date=expiry_date,
            file_name=file.filename,
            content_type=file.content_type,
            data=data,
        )
    except InvalidDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="employee.document.upload",
        entity_type="employee_document",
        entity_id=document.id,
        metadata={
            "employee_id": str(employee.id),
            "category": document.category.value,
            "file_name": document.file_name,
            "size_bytes": document.size_bytes,
        },
    )
    return _out(document, request)


@router.get("/{employee_id}/documents", response_model=list[EmployeeDocumentOut])
def list_documents(
    employee_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[EmployeeDocumentOut]:
    _get_employee_or_404(db, employee_id)
    return [
        _out(document, request)
        for document in db.scalars(
            select(EmployeeDocument)
            .where(EmployeeDocument.employee_id == employee_id)
            .order_by(EmployeeDocument.created_at)
        )
    ]


@router.get("/documents/me", response_model=list[EmployeeDocumentOut])
def list_my_documents(
    request: Request,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> list[EmployeeDocumentOut]:
    return [
        _out(document, request)
        for document in db.scalars(
            select(EmployeeDocument)
            .where(EmployeeDocument.employee_id == employee.id)
            .order_by(EmployeeDocument.created_at)
        )
    ]


@router.patch("/documents/{document_id}", response_model=EmployeeDocumentOut)
def update_document(
    document_id: uuid.UUID,
    body: EmployeeDocumentUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> EmployeeDocumentOut:
    document = _get_document_or_404(db, document_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(document, field, value)
    db.add(document)
    db.flush()
    return _out(document, request)
