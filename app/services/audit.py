import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def record_audit_event(
    db: Session,
    *,
    org_id: uuid.UUID,
    account_id: uuid.UUID | None,
    role: str | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Record one audit event. Called from the API layer right after a
    mutating action succeeds — routers hold the JWT claims (account_id,
    role) that service functions don't otherwise need, so this is the
    natural integration point rather than threading actor identity through
    every service call.
    """
    entry = AuditLog(
        org_id=org_id,
        account_id=account_id,
        role=role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        event_metadata=metadata or {},
    )
    db.add(entry)
    db.flush()
    return entry
