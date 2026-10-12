"""Shared plumbing for the inventory routers: the module-enabled gate,
permission checks, service-error mapping and audit events."""

import uuid
from collections.abc import Callable
from typing import Any, NoReturn

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_tenant_db
from app.core.security import TokenClaims
from app.domain.inventory.costing import InsufficientStockError
from app.domain.permissions import Permission
from app.services import inventory as svc
from app.services.audit import record_audit_event
from app.services.permissions import account_has_permission


def require_enabled(
    claims: TokenClaims = Depends(get_current_claims), db: Session = Depends(get_tenant_db)
) -> None:
    if not svc.inventory_enabled(db, org_id=claims.org_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="inventory is not enabled for this organisation",
        )


ENABLED = [Depends(require_enabled)]


def sees_values(
    claims: TokenClaims = Depends(get_current_claims), db: Session = Depends(get_tenant_db)
) -> bool:
    return account_has_permission(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        permission=Permission.INVENTORY_VALUATION,
    )


def require_any_permission(
    *permissions: Permission,
) -> Callable[[TokenClaims, Session], TokenClaims]:
    """Like require_permission, but any one of `permissions` is enough."""

    def _check(
        claims: TokenClaims = Depends(get_current_claims), db: Session = Depends(get_tenant_db)
    ) -> TokenClaims:
        if not any(
            account_has_permission(
                db, org_id=claims.org_id, account_id=claims.account_id, permission=permission
            )
            for permission in permissions
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="requires one of: " + ", ".join(p.value for p in permissions),
            )
        return claims

    return _check


def fail(exc: Exception) -> NoReturn:
    """Maps a service exception to its HTTP status (see app.services.inventory)."""
    if isinstance(exc, svc.InventoryNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, (svc.InventoryConflict, InsufficientStockError)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, IntegrityError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this conflicts with an existing record; reload and try again",
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


def not_found(label: str) -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")


def run[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except (LookupError, ValueError, PermissionError, IntegrityError) as exc:
        fail(exc)


def audit(
    db: Session,
    claims: TokenClaims,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
    )


def changes(body: Any) -> dict[str, Any]:
    return dict(body.model_dump(mode="json", exclude_unset=True))
