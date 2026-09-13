from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.schemas.reminders import RemindersSummaryOut
from app.services.reminders import run_reminder_job

router = APIRouter(prefix="/reminders", tags=["reminders"])

_RUN = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.post("/run", response_model=RemindersSummaryOut)
def run(
    as_of: date | None = None,
    stale_after_days: int = 3,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RUN),
) -> RemindersSummaryOut:
    """Intended to be called on a schedule by an external trigger (this
    app has no in-process job scheduler of its own, and ApiKey doesn't
    yet authenticate requests — see its own docstring), but works fine
    called on demand by an ADMIN/PAYROLL_MANAGER too."""
    summary = run_reminder_job(
        db,
        claims.org_id,
        as_of=as_of or datetime.now(UTC).date(),
        stale_after_days=stale_after_days,
    )
    return RemindersSummaryOut(
        deadline_count=summary.deadline_count,
        stale_approval_count=summary.stale_approval_count,
        notifications_created=len(summary.notifications_created),
    )
