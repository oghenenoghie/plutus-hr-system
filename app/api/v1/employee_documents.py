import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.membership import Role
from app.schemas.employee_documents import (
    EmployeeDocumentCreate,
    EmployeeDocumentOut,
    EmployeeDocumentUpdate,
)

router = APIRouter(prefix="/employees", tags=["employee-documents"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


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


@router.post(
    "/{employee_id}/documents",
    response_model=EmployeeDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    employee_id: uuid.UUID,
    body: EmployeeDocumentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EmployeeDocument:
    _get_employee_or_404(db, employee_id)
    document = EmployeeDocument(
        org_id=claims.org_id,
        employee_id=employee_id,
        uploaded_by=claims.account_id,
        **body.model_dump(),
    )
    db.add(document)
    db.flush()
    return document


@router.get("/{employee_id}/documents", response_model=list[EmployeeDocumentOut])
def list_documents(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[EmployeeDocument]:
    _get_employee_or_404(db, employee_id)
    return list(
        db.scalars(
            select(EmployeeDocument)
            .where(EmployeeDocument.employee_id == employee_id)
            .order_by(EmployeeDocument.created_at)
        )
    )


@router.get("/documents/me", response_model=list[EmployeeDocumentOut])
def list_my_documents(
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> list[EmployeeDocument]:
    return list(
        db.scalars(
            select(EmployeeDocument)
            .where(EmployeeDocument.employee_id == employee.id)
            .order_by(EmployeeDocument.created_at)
        )
    )


@router.patch("/documents/{document_id}", response_model=EmployeeDocumentOut)
def update_document(
    document_id: uuid.UUID,
    body: EmployeeDocumentUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> EmployeeDocument:
    document = _get_document_or_404(db, document_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(document, field, value)
    db.add(document)
    db.flush()
    return document
