import secrets
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

# Excludes 0/O and 1/I/L — a login code is read off a screen and typed by a
# human, unlike the token_urlsafe secrets api_keys.py generates for machine
# use, so ambiguous characters are worth avoiding here specifically.
_LOGIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_LOGIN_CODE_LENGTH = 8


def generate_login_code() -> str:
    """A short, globally-unique-by-convention identifier an employee can
    sign in with instead of an email address — mirrors hr-payroll's
    auto-generated Employee ID badge. Uniqueness itself is enforced by the
    caller checking it against employees.login_code (unique-constrained)
    and regenerating on collision; this function only produces a candidate.
    """
    return "".join(secrets.choice(_LOGIN_CODE_ALPHABET) for _ in range(_LOGIN_CODE_LENGTH))


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
