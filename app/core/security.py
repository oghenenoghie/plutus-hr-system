import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str, issuer: str = "Plutus") -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.totp.TOTP(secret).verify(code)


@dataclass(frozen=True)
class TokenClaims:
    account_id: uuid.UUID
    org_id: uuid.UUID
    role: str


def _encode_token(
    account_id: uuid.UUID,
    org_id: uuid.UUID,
    role: str,
    token_type: Literal["access", "refresh"],
    ttl: timedelta,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(account_id),
        "org_id": str(org_id),
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(account_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    return _encode_token(
        account_id, org_id, role, "access", timedelta(minutes=settings.jwt_access_ttl_minutes)
    )


def create_refresh_token(account_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    return _encode_token(
        account_id, org_id, role, "refresh", timedelta(days=settings.jwt_refresh_ttl_days)
    )


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> TokenClaims:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return TokenClaims(
        account_id=uuid.UUID(payload["sub"]),
        org_id=uuid.UUID(payload["org_id"]),
        role=payload["role"],
    )
