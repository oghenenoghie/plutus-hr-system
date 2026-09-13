import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.compliance.resolver import resolve_rule_version
from app.core.deps import get_current_claims, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.approval import ApprovalRequestType
from app.models.bill import Bill
from app.models.membership import Role
from app.models.organisation import Organisation
from app.models.vendor import Vendor
from app.schemas.bills import BillCreate, BillOut, EmailBillRequest
from app.services import approvals
from app.services.bill_pdf import render_bill_pdf
from app.services.bills import approve_bill, pay_bill, register_bill, void_bill
from app.services.document_email import email_bill_pdf

_COUNTRY = "NG"

router = APIRouter(prefix="/bills", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_bill_or_404(db: Session, bill_id: uuid.UUID) -> Bill:
    bill = db.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bill not found")
    return bill


def _get_bill_vendor_org(db: Session, bill_id: uuid.UUID) -> tuple[Bill, Vendor, Organisation]:
    bill = _get_bill_or_404(db, bill_id)
    vendor = db.get(Vendor, bill.vendor_id)
    organisation = db.get(Organisation, bill.org_id)
    if vendor is None or organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bill not found")
    return bill, vendor, organisation


@router.post("", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def create_bill(
    body: BillCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    try:
        bill = register_bill(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a bill with this number already exists for this vendor",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    approvals.get_or_create_instance(
        db,
        org_id=claims.org_id,
        request_type=ApprovalRequestType.BILL,
        request_id=bill.id,
        requester_employee_id=None,
    )
    return bill


@router.get("", response_model=list[BillOut])
def list_bills(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[Bill]:
    return list(db.scalars(select(Bill).order_by(Bill.bill_date.desc())))


@router.get("/{bill_id}", response_model=BillOut)
def get_bill(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    return _get_bill_or_404(db, bill_id)


@router.post("/{bill_id}/approve", response_model=BillOut)
def approve(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Bill:
    bill = _get_bill_or_404(db, bill_id)
    rules = (
        resolve_rule_version(_COUNTRY, bill.bill_date) if bill.wht_category is not None else None
    )
    try:
        _, is_final = approvals.decide(
            db,
            claims=claims,
            request_type=ApprovalRequestType.BILL,
            request_id=bill.id,
            requester_employee_id=None,
            approve=True,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not is_final:
        return bill
    try:
        return approve_bill(db, bill, rules=rules)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{bill_id}/pay", response_model=BillOut)
def pay(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    bill = _get_bill_or_404(db, bill_id)
    try:
        return pay_bill(db, bill)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{bill_id}/void", response_model=BillOut)
def void(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    bill = _get_bill_or_404(db, bill_id)
    try:
        return void_bill(db, bill)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{bill_id}/pdf")
def download_bill_pdf(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    bill, vendor, organisation = _get_bill_vendor_org(db, bill_id)
    pdf_bytes = render_bill_pdf(organisation=organisation, bill=bill, vendor=vendor)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="bill-{bill.bill_number}.pdf"'},
    )


@router.post("/{bill_id}/email", status_code=status.HTTP_204_NO_CONTENT)
def email_bill(
    bill_id: uuid.UUID,
    body: EmailBillRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> None:
    bill, vendor, organisation = _get_bill_vendor_org(db, bill_id)
    try:
        email_bill_pdf(organisation=organisation, bill=bill, vendor=vendor, to=body.to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"email delivery failed: {exc}"
        ) from exc
