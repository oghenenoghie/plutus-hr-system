import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.bill import Bill
from app.models.membership import Role
from app.models.recurring_bill import RecurringBill
from app.schemas.bills import BillOut
from app.schemas.recurring_bills import RecurringBillCreate, RecurringBillOut, RecurringBillUpdate
from app.services.recurring_bills import generate_due_bills, register_recurring_bill

router = APIRouter(prefix="/recurring-bills", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_or_404(db: Session, template_id: uuid.UUID) -> RecurringBill:
    template = db.get(RecurringBill, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="recurring bill not found"
        )
    return template


@router.post("", response_model=RecurringBillOut, status_code=status.HTTP_201_CREATED)
def create_recurring_bill(
    body: RecurringBillCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> RecurringBill:
    try:
        return register_recurring_bill(db, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[RecurringBillOut])
def list_recurring_bills(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[RecurringBill]:
    return list(db.scalars(select(RecurringBill)))


@router.patch("/{template_id}", response_model=RecurringBillOut)
def update_recurring_bill(
    template_id: uuid.UUID,
    body: RecurringBillUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> RecurringBill:
    template = _get_or_404(db, template_id)
    template.is_active = body.is_active
    db.add(template)
    db.flush()
    return template


@router.post("/generate-due", response_model=list[BillOut])
def generate_due(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[Bill]:
    return generate_due_bills(db, claims.org_id, as_of=as_of or datetime.now(UTC).date())
