import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.api_key import ApiKey

_KEY_PREFIX_LENGTH = 12


def register_api_key(db: Session, *, org_id: uuid.UUID, name: str) -> tuple[ApiKey, str]:
    """Returns (record, plaintext_key) — the caller must surface
    plaintext_key to the response now, since it's never recoverable
    again."""
    plaintext_key = f"plk_{secrets.token_urlsafe(32)}"
    api_key = ApiKey(
        org_id=org_id,
        name=name,
        key_prefix=plaintext_key[:_KEY_PREFIX_LENGTH],
        key_hash=hash_password(plaintext_key),
    )
    db.add(api_key)
    db.flush()
    return api_key, plaintext_key


def revoke_api_key(db: Session, api_key: ApiKey) -> ApiKey:
    if api_key.revoked_at is not None:
        raise ValueError("this API key is already revoked")
    api_key.revoked_at = datetime.now(UTC)
    db.add(api_key)
    return api_key
