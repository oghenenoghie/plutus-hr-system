import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EmployeeLoginCode(Base):
    """Projection of employees.login_code -> account_id, kept outside RLS
    (like Account/Membership) so /auth/login can resolve a code to an
    account before any tenant_session exists — employees is FORCE RLS'd,
    so even a SECURITY DEFINER lookup against it would see nothing under
    an untenanted session. Written at link-account time, mirroring the
    employees row it projects.
    """

    __tablename__ = "employee_login_codes"

    login_code: Mapped[str] = mapped_column(primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
