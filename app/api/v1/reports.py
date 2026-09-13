import uuid
from datetime import UTC, date, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.customer import Customer
from app.models.membership import Role
from app.models.organisation import Organisation
from app.models.vendor import Vendor
from app.schemas.reports import (
    AgingLineOut,
    CustomerStatementLineOut,
    EmailStatementRequest,
    PayrollCostLineOut,
    VendorStatementLineOut,
)
from app.services.document_email import email_customer_statement_pdf, email_vendor_statement_pdf
from app.services.reports import (
    ap_aging_report,
    ar_aging_report,
    customer_statement,
    payroll_cost_by_department,
    vendor_statement,
)
from app.services.statement_pdf import render_customer_statement_pdf, render_vendor_statement_pdf

router = APIRouter(prefix="/reports", tags=["reports"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_vendor_or_404(db: Session, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return vendor


def _get_customer_or_404(db: Session, customer_id: uuid.UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="customer not found")
    return customer


def _get_organisation(db: Session, org_id: uuid.UUID) -> Organisation:
    organisation = db.get(Organisation, org_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organisation not found")
    return organisation


@router.get("/payroll-cost", response_model=list[PayrollCostLineOut])
def get_payroll_cost_by_department(
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[PayrollCostLineOut]:
    lines = payroll_cost_by_department(db, claims.org_id, from_date=from_date, to_date=to_date)
    return [PayrollCostLineOut(**vars(line)) for line in lines]


@router.get("/ap-aging", response_model=list[AgingLineOut])
def get_ap_aging(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[AgingLineOut]:
    lines = ap_aging_report(db, claims.org_id, as_of=as_of or datetime.now(UTC).date())
    return [AgingLineOut(**vars(line)) for line in lines]


@router.get("/ar-aging", response_model=list[AgingLineOut])
def get_ar_aging(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[AgingLineOut]:
    lines = ar_aging_report(db, claims.org_id, as_of=as_of or datetime.now(UTC).date())
    return [AgingLineOut(**vars(line)) for line in lines]


@router.get("/vendors/{vendor_id}/statement", response_model=list[VendorStatementLineOut])
def get_vendor_statement(
    vendor_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[VendorStatementLineOut]:
    lines = vendor_statement(db, claims.org_id, vendor_id, from_date=from_date, to_date=to_date)
    return [VendorStatementLineOut(**vars(line)) for line in lines]


@router.get("/vendors/{vendor_id}/statement/pdf")
def download_vendor_statement_pdf(
    vendor_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    vendor = _get_vendor_or_404(db, vendor_id)
    organisation = _get_organisation(db, claims.org_id)
    lines = vendor_statement(db, claims.org_id, vendor_id, from_date=from_date, to_date=to_date)
    pdf_bytes = render_vendor_statement_pdf(
        organisation=organisation, vendor=vendor, lines=lines, from_date=from_date, to_date=to_date
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="statement-{vendor.name}.pdf"'},
    )


@router.post("/vendors/{vendor_id}/statement/email", status_code=status.HTTP_204_NO_CONTENT)
def email_vendor_statement(
    vendor_id: uuid.UUID,
    body: EmailStatementRequest,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> None:
    vendor = _get_vendor_or_404(db, vendor_id)
    organisation = _get_organisation(db, claims.org_id)
    lines = vendor_statement(db, claims.org_id, vendor_id, from_date=from_date, to_date=to_date)
    try:
        email_vendor_statement_pdf(
            organisation=organisation,
            vendor=vendor,
            lines=lines,
            from_date=from_date,
            to_date=to_date,
            to=body.to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"email delivery failed: {exc}"
        ) from exc


@router.get("/customers/{customer_id}/statement", response_model=list[CustomerStatementLineOut])
def get_customer_statement(
    customer_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[CustomerStatementLineOut]:
    lines = customer_statement(db, claims.org_id, customer_id, from_date=from_date, to_date=to_date)
    return [CustomerStatementLineOut(**vars(line)) for line in lines]


@router.get("/customers/{customer_id}/statement/pdf")
def download_customer_statement_pdf(
    customer_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    customer = _get_customer_or_404(db, customer_id)
    organisation = _get_organisation(db, claims.org_id)
    lines = customer_statement(db, claims.org_id, customer_id, from_date=from_date, to_date=to_date)
    pdf_bytes = render_customer_statement_pdf(
        organisation=organisation,
        customer=customer,
        lines=lines,
        from_date=from_date,
        to_date=to_date,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="statement-{customer.name}.pdf"'},
    )


@router.post("/customers/{customer_id}/statement/email", status_code=status.HTTP_204_NO_CONTENT)
def email_customer_statement(
    customer_id: uuid.UUID,
    body: EmailStatementRequest,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> None:
    customer = _get_customer_or_404(db, customer_id)
    organisation = _get_organisation(db, claims.org_id)
    lines = customer_statement(db, claims.org_id, customer_id, from_date=from_date, to_date=to_date)
    try:
        email_customer_statement_pdf(
            organisation=organisation,
            customer=customer,
            lines=lines,
            from_date=from_date,
            to_date=to_date,
            to=body.to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"email delivery failed: {exc}"
        ) from exc
