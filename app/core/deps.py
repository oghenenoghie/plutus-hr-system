from collections.abc import Callable, Generator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_untenanted_session, tenant_session
from app.core.security import TokenClaims, decode_token
from app.models.employee import Employee
from app.models.membership import Role

_bearer_scheme = HTTPBearer()


def get_untenanted_db() -> Generator[Session, None, None]:
    yield from get_untenanted_session()


def get_current_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> TokenClaims:
    try:
        return decode_token(credentials.credentials, expected_type="access")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token"
        ) from exc


def get_tenant_db(
    claims: TokenClaims = Depends(get_current_claims),
) -> Generator[Session, None, None]:
    with tenant_session(claims.org_id, claims.account_id, claims.role) as session:
        yield session


def require_roles(*roles: Role) -> Callable[[TokenClaims], TokenClaims]:
    """Dependency factory gating an endpoint to a set of roles, e.g.
    Depends(require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)). Checked
    against the role embedded in the JWT at login time — a role change
    takes effect on the account's next login, same as every other claim.
    """
    allowed = frozenset(roles)

    def _check(claims: TokenClaims = Depends(get_current_claims)) -> TokenClaims:
        if claims.role not in {r.value for r in allowed}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of: {', '.join(sorted(r.value for r in allowed))}",
            )
        return claims

    return _check


def get_current_employee(
    claims: TokenClaims = Depends(get_current_claims), db: Session = Depends(get_tenant_db)
) -> Employee:
    """Resolves the caller's own Employee record for self-service endpoints
    (my payslips, my leave, my loans). A membership with no linked
    employee row (e.g. an admin who is only ever an operator, never on
    payroll) gets 403 rather than a confusing empty result."""
    employee = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this account has no linked employee record",
        )
    return employee
