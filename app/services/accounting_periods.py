"""Interim period control (D13, docs/architecture/inventory-integration.md).

An organisation may set a lock date in its accounting settings; nothing may
then be posted on or before that day. It is enforced at the bottom of every
journal writer (app/services/posting.py and post_manual_journal_entry) and of
the inventory stock-posting engine, so no caller can forget it. Full
accounting periods (audit Phase 15) will replace it.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accounting_settings import AccountingSettings


class PeriodLockedError(ValueError):
    """A posting dated on or before the organisation's lock date. A
    ValueError, so every router that already maps ValueError to 400 refuses
    it without change."""


def lock_date(db: Session, *, org_id: uuid.UUID) -> date | None:
    return db.scalar(
        select(AccountingSettings.lock_date).where(AccountingSettings.org_id == org_id)
    )


def require_open_period(db: Session, *, org_id: uuid.UUID, entry_date: date) -> None:
    locked_to = lock_date(db, org_id=org_id)
    if locked_to is not None and entry_date <= locked_to:
        raise PeriodLockedError(
            f"{entry_date.isoformat()} is in a locked period: the books are locked up to "
            f"{locked_to.isoformat()}"
        )
