import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.organisation import Organisation
from app.schemas.payroll_reports import (
    AnnualTaxReconciliationOut,
    PayeByStateLineOut,
    PayrollRegisterLineOut,
)
from app.services.payroll_reports import annual_tax_reconciliation, paye_by_state, payroll_register
from app.services.tax_certificate_pdf import render_tax_certificate_pdf

router = APIRouter(prefix="/reports", tags=["payroll-reports"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.get("/payroll-register/{pay_run_id}", response_model=list[PayrollRegisterLineOut])
def get_payroll_register(
    pay_run_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[PayrollRegisterLineOut]:
    lines = payroll_register(db, claims.org_id, pay_run_id)
    return [PayrollRegisterLineOut(**vars(line)) for line in lines]


@router.get("/paye-by-state", response_model=list[PayeByStateLineOut])
def get_paye_by_state(
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[PayeByStateLineOut]:
    lines = paye_by_state(db, claims.org_id, from_date=from_date, to_date=to_date)
    return [PayeByStateLineOut(**vars(line)) for line in lines]


@router.get("/annual-tax-reconciliation", response_model=list[AnnualTaxReconciliationOut])
def get_annual_tax_reconciliation(
    tax_year: int,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[AnnualTaxReconciliationOut]:
    lines = annual_tax_reconciliation(db, claims.org_id, tax_year=tax_year)
    return [AnnualTaxReconciliationOut(**vars(line)) for line in lines]


@router.get("/annual-tax-reconciliation/{employee_id}/certificate")
def get_tax_certificate_pdf(
    employee_id: uuid.UUID,
    tax_year: int,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    lines = annual_tax_reconciliation(db, claims.org_id, tax_year=tax_year)
    reconciliation = next((line for line in lines if line.employee_id == employee_id), None)
    if reconciliation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no locked payslips for this employee in that tax year",
        )
    organisation = db.get(Organisation, claims.org_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organisation not found")
    pdf_bytes = render_tax_certificate_pdf(organisation=organisation, reconciliation=reconciliation)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="tax-certificate-{tax_year}.pdf"'},
    )
