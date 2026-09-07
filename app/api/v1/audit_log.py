import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.audit_log import AuditLog
from app.models.membership import Role
from app.schemas.audit import AuditLogOut

router = APIRouter(prefix="/audit-log", tags=["audit-log"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.get("", response_model=list[AuditLogOut])
def list_audit_log(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    limit: int = Query(default=100, le=500, gt=0),
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if entity_type is not None:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    return list(db.scalars(query))
