import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accounting_settings import AccountingSettings
from app.services.chart_accounts import seed_default_chart_of_accounts
from app.services.posting import today_lagos


def get_accounting_settings(db: Session, *, org_id: uuid.UUID) -> AccountingSettings:
    """The org's settings row, or an unsaved all-flags-off default if nobody
    has ever set one. The default is not added to the session."""
    row = db.get(AccountingSettings, org_id)
    if row is None:
        return AccountingSettings(org_id=org_id, post_statutory_remittances=False, lock_date=None)
    return row


def remittance_posting_enabled(db: Session, *, org_id: uuid.UUID) -> bool:
    enabled = db.scalar(
        select(AccountingSettings.post_statutory_remittances).where(
            AccountingSettings.org_id == org_id
        )
    )
    return bool(enabled)


def update_accounting_settings(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_account_id: uuid.UUID | None,
    post_statutory_remittances: bool | None = None,
    lock_date: date | None = None,
    set_lock_date: bool = False,
) -> AccountingSettings:
    """Switching remittance posting on first makes sure the default chart of
    accounts exists (idempotent — it never touches an account the org
    already has), because the posting is validated against the chart and
    would otherwise fail on the first remittance with "unknown account"."""
    row = db.get(AccountingSettings, org_id)
    if row is None:
        row = AccountingSettings(org_id=org_id, post_statutory_remittances=False)
        db.add(row)

    if post_statutory_remittances is not None:
        if post_statutory_remittances:
            seed_default_chart_of_accounts(db, org_id=org_id)
        row.post_statutory_remittances = post_statutory_remittances
    if set_lock_date:
        # D13. Locking ahead of today would refuse today's own postings,
        # which is never what closing a period means.
        if lock_date is not None and lock_date > today_lagos():
            raise ValueError("the lock date can't be in the future")
        row.lock_date = lock_date
    row.updated_by = actor_account_id
    db.flush()
    db.refresh(row)
    return row
