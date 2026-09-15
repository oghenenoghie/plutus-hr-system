import uuid
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.organisation import Organisation
from app.schemas.financial_statements import (
    BalanceSheetOut,
    EmailFinancialStatementRequest,
    IncomeStatementOut,
)
from app.services.document_email import email_balance_sheet_pdf, email_income_statement_pdf
from app.services.financial_statement_pdf import (
    render_balance_sheet_pdf,
    render_income_statement_pdf,
)
from app.services.financial_statements import balance_sheet, income_statement

router = APIRouter(prefix="/financial-statements", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)


def _get_organisation(db: Session, org_id: uuid.UUID) -> Organisation:
    organisation = db.get(Organisation, org_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organisation not found")
    return organisation


@router.get("/balance-sheet", response_model=BalanceSheetOut)
def get_balance_sheet(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> BalanceSheetOut:
    return balance_sheet(db, org_id=claims.org_id, as_of=as_of)


@router.get("/balance-sheet/pdf")
def download_balance_sheet_pdf(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    organisation = _get_organisation(db, claims.org_id)
    statement = balance_sheet(db, org_id=claims.org_id, as_of=as_of)
    pdf_bytes = render_balance_sheet_pdf(organisation=organisation, statement=statement)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="balance-sheet.pdf"'},
    )


@router.post("/balance-sheet/email", status_code=status.HTTP_204_NO_CONTENT)
def email_balance_sheet(
    body: EmailFinancialStatementRequest,
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> None:
    organisation = _get_organisation(db, claims.org_id)
    statement = balance_sheet(db, org_id=claims.org_id, as_of=as_of)
    try:
        email_balance_sheet_pdf(organisation=organisation, statement=statement, to=body.to)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"email delivery failed: {exc}"
        ) from exc


@router.get("/income-statement", response_model=IncomeStatementOut)
def get_income_statement(
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> IncomeStatementOut:
    return income_statement(db, org_id=claims.org_id, from_date=from_date, to_date=to_date)


@router.get("/income-statement/pdf")
def download_income_statement_pdf(
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    organisation = _get_organisation(db, claims.org_id)
    statement = income_statement(db, org_id=claims.org_id, from_date=from_date, to_date=to_date)
    pdf_bytes = render_income_statement_pdf(organisation=organisation, statement=statement)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="income-statement.pdf"'},
    )


@router.post("/income-statement/email", status_code=status.HTTP_204_NO_CONTENT)
def email_income_statement(
    body: EmailFinancialStatementRequest,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> None:
    organisation = _get_organisation(db, claims.org_id)
    statement = income_statement(db, org_id=claims.org_id, from_date=from_date, to_date=to_date)
    try:
        email_income_statement_pdf(organisation=organisation, statement=statement, to=body.to)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"email delivery failed: {exc}"
        ) from exc
