from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.accounting_settings import AccountingSettings
from app.models.membership import Role
from app.schemas.accounting_settings import AccountingSettingsOut, AccountingSettingsUpdate
from app.services.accounting_settings import get_accounting_settings, update_accounting_settings
from app.services.audit import record_audit_event

router = APIRouter(prefix="/accounting-settings", tags=["accounting"])

# Changing what the ledger posts automatically is a financial-control
# decision, so it is narrower than the general accounting roles: a payroll
# manager can read it but not change it.
_CHANGE = require_roles(Role.ADMIN, Role.ACCOUNTANT)
_VIEW = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT, Role.AUDITOR)


@router.get("", response_model=AccountingSettingsOut)
def read_accounting_settings(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW)
) -> AccountingSettings:
    return get_accounting_settings(db, org_id=claims.org_id)


@router.patch("", response_model=AccountingSettingsOut)
def change_accounting_settings(
    body: AccountingSettingsUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_CHANGE),
) -> AccountingSettings:
    settings = update_accounting_settings(
        db,
        org_id=claims.org_id,
        actor_account_id=claims.account_id,
        post_statutory_remittances=body.post_statutory_remittances,
    )
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="accounting_settings.update",
        entity_type="accounting_settings",
        entity_id=claims.org_id,
        metadata=body.model_dump(exclude_unset=True),
    )
    return settings
