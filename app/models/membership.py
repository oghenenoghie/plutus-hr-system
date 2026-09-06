import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(str, enum.Enum):
    ADMIN = "admin"
    PAYROLL_MANAGER = "payroll_manager"
    MANAGER = "manager"
    EMPLOYEE = "employee"


MFA_REQUIRED_ROLES = frozenset({Role.ADMIN, Role.PAYROLL_MANAGER})


class Membership(Base):
    """Which organisation an account belongs to, and in what role. Not
    tenant business data — no RLS. This is what lets a login flow discover
    which org(s) to open a tenant_session against, before any RLS-scoped
    query can run.
    """

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("account_id", "org_id", name="uq_membership_account_org"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="membership_role", values_callable=lambda roles: [r.value for r in roles]),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
