import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.permissions import Permission
from app.models.base import Base


class MembershipPermissionOverride(Base):
    """One permission, explicitly granted or revoked for one Membership,
    beyond what its Role would give it by default (see
    app.domain.permissions.resolve_permissions) — the fine-grained half of
    RBAC in this codebase. At most one row per (membership, permission);
    updating an override overwrites this row rather than adding another.
    """

    __tablename__ = "membership_permission_overrides"
    __table_args__ = (
        UniqueConstraint("membership_id", "permission", name="uq_membership_permission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="CASCADE"), nullable=False
    )
    permission: Mapped[Permission] = mapped_column(
        Enum(
            Permission,
            name="membership_permission_override_permission",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
