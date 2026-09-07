import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiKey(Base):
    """An API key an org can hand to an external system for integration
    access. The plaintext key is shown exactly once, at creation — only
    its argon2 hash (key_hash) is stored, same hasher as account
    passwords. key_prefix is the key's first several characters, kept in
    plaintext purely so a key can be recognised in a list without ever
    re-displaying the secret. revoked_at is one-way; there is no
    un-revoke, matching how a leaked credential should be handled (issue
    a new one, don't try to un-leak the old one). Nothing in this
    codebase yet authenticates a request against these keys — this module
    manages their lifecycle as an org-facing settings feature, ahead of
    that verification middleware.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
