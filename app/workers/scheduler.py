"""The app's in-process job scheduler.

There is no separate worker/cron service (railway.json defines only the
plutus-api web service), so this runs inside the same uvicorn process as
the API instead — a BackgroundScheduler on its own thread, started from
app.main's lifespan. It replaces what used to be purely pull-based,
externally-triggered endpoints (POST /reminders/run,
POST /recurring-bills/generate-due, POST /recurring-invoices/generate-due)
with an actual daily schedule, while leaving those endpoints in place for
an on-demand run.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.db import get_session_factory, system_session
from app.models.membership import Membership
from app.services.recurring_bills import generate_due_bills
from app.services.recurring_invoices import generate_due_invoices
from app.services.reminders import run_reminder_job

logger = logging.getLogger(__name__)


def _all_org_ids() -> list[uuid.UUID]:
    """organisations carries RLS forcing app.current_org to be set to one
    specific org already — no use for "give me every org" — so this reads
    memberships instead, an identity/directory table with no RLS (see
    tests/integration/api_helpers.py, which already queries it the same
    way). Every real org gets at least one membership at creation time
    (its first admin), so this is a complete list of orgs in practice."""
    session = get_session_factory()()
    try:
        return list(session.scalars(select(Membership.org_id).distinct()))
    finally:
        session.close()


def _for_every_org(job_name: str, run_one: Callable[[uuid.UUID], None]) -> None:
    """Runs `run_one` once per org, each in its own transaction — a
    failure for one org (bad data, a transient DB error) is logged and
    skipped rather than aborting every other org's run."""
    for org_id in _all_org_ids():
        try:
            run_one(org_id)
        except Exception:
            logger.exception("scheduled job %s failed for org %s", job_name, org_id)


def run_reminders_for_all_orgs() -> None:
    today = datetime.now(UTC).date()

    def _run_one(org_id: uuid.UUID) -> None:
        with system_session(org_id) as db:
            run_reminder_job(db, org_id, as_of=today)

    _for_every_org("reminders", _run_one)


def generate_due_bills_for_all_orgs() -> None:
    today = datetime.now(UTC).date()

    def _run_one(org_id: uuid.UUID) -> None:
        with system_session(org_id) as db:
            generate_due_bills(db, org_id, as_of=today)

    _for_every_org("recurring-bills", _run_one)


def generate_due_invoices_for_all_orgs() -> None:
    today = datetime.now(UTC).date()

    def _run_one(org_id: uuid.UUID) -> None:
        with system_session(org_id) as db:
            generate_due_invoices(db, org_id, as_of=today)

    _for_every_org("recurring-invoices", _run_one)


def build_scheduler() -> BackgroundScheduler:
    """One in-process scheduler for the whole app. The three jobs are
    staggered five minutes apart, all in an early-morning UTC window, so
    they don't all hammer the database at the same instant."""
    scheduler = BackgroundScheduler(timezone=UTC)
    scheduler.add_job(
        run_reminders_for_all_orgs,
        CronTrigger(hour=2, minute=0),
        id="reminders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        generate_due_bills_for_all_orgs,
        CronTrigger(hour=2, minute=5),
        id="recurring-bills",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        generate_due_invoices_for_all_orgs,
        CronTrigger(hour=2, minute=10),
        id="recurring-invoices",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler
