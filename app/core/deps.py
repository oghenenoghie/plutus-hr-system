from collections.abc import Generator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_untenanted_session, tenant_session
from app.core.security import TokenClaims, decode_token

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
