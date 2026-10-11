"""The posting engine: the one place a journal header and its ledger lines
are written together. Evolved from post_manual_journal_entry
(app/services/general_ledger.py) per ACCOUNTING_IMPLEMENTATION_AUDIT.md §20.

Writers that have been moved onto it so far: pay-run lock (one journal per
payslip), NSITF accrual, pay-run reversal, and statutory remittance. Bills,
invoices, credit notes, fixed assets, contractor WHT and manual journals
still write ledger_entries directly and so have no header yet.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.accounting.posting_rules import PostingLine, assert_balanced, mirror_postings
from app.models.chart_account import ChartAccount
from app.models.journal_entry import JournalEntry, JournalSourceType
from app.models.ledger import LedgerEntry

# Nigeria has no daylight saving, so a fixed offset is exact — and avoids
# depending on tzdata being present, which the Windows desktop build (a
# PyInstaller bundle) does not guarantee.
_LAGOS = timezone(timedelta(hours=1))

_DESCRIPTION_MAX = 500


def lagos_date(moment: datetime) -> date:
    """The calendar date `moment` falls on in Nigeria."""
    return moment.astimezone(_LAGOS).date()


def today_lagos() -> date:
    return lagos_date(datetime.now(UTC))


def _truncate(text: str) -> str:
    return text if len(text) <= _DESCRIPTION_MAX else text[: _DESCRIPTION_MAX - 1] + "…"


def _require_active_accounts(db: Session, *, org_id: uuid.UUID, codes: Iterable[str]) -> None:
    wanted = set(codes)
    rows = db.execute(
        select(ChartAccount.code, ChartAccount.is_active).where(
            ChartAccount.org_id == org_id, ChartAccount.code.in_(wanted)
        )
    ).all()
    active_by_code = {code: is_active for code, is_active in rows}
    for code in sorted(wanted):
        if code not in active_by_code:
            raise ValueError(f"unknown account code: {code}")
        if not active_by_code[code]:
            raise ValueError(f"account {code} is inactive and cannot be posted to")


def _write_lines(
    db: Session, *, org_id: uuid.UUID, header: JournalEntry, lines: Iterable[PostingLine]
) -> None:
    for line in lines:
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=header.id,
                pay_run_id=line.pay_run_id,
                employee_id=line.employee_id,
                department_id=line.department_id,
                account=line.account,
                debit_minor=line.debit_minor,
                credit_minor=line.credit_minor,
                description=line.description or header.description,
            )
        )
    db.flush()


def post_journal(
    db: Session,
    *,
    org_id: uuid.UUID,
    entry_date: date,
    source_type: JournalSourceType,
    source_event: str,
    description: str,
    lines: Iterable[PostingLine],
    source_id: uuid.UUID | None = None,
    reference: str | None = None,
    actor_account_id: uuid.UUID | None = None,
    validate_chart: bool = True,
) -> JournalEntry:
    """Writes one journal header and its lines in the caller's transaction;
    nothing is committed here. Raises ValueError (routers map it to 400)
    before writing anything if the lines don't balance, if a line's account
    is missing or inactive, or if this (source_type, source_id,
    source_event) has already been posted.

    `validate_chart=False` skips the chart-of-accounts check. It exists for
    the payroll writers only, which have always posted to account codes
    without consulting the chart: an organisation that never seeded its
    chart (audit P3) must still be able to lock a pay run, and the chart
    still lacks two accounts payroll posts to (audit P1). Each such call
    site says so; delete the flag once the chart is guaranteed complete.
    Everything new validates.
    """
    materialised = tuple(lines)
    assert_balanced(materialised)
    if validate_chart:
        _require_active_accounts(db, org_id=org_id, codes=(line.account for line in materialised))

    if source_id is not None:
        already_posted = db.scalar(
            select(JournalEntry.id).where(
                JournalEntry.org_id == org_id,
                JournalEntry.source_type == source_type,
                JournalEntry.source_id == source_id,
                JournalEntry.source_event == source_event,
            )
        )
        if already_posted is not None:
            raise ValueError(f"{source_event} has already been posted for this {source_type.value}")

    header = JournalEntry(
        org_id=org_id,
        entry_date=entry_date,
        source_type=source_type,
        source_id=source_id,
        source_event=source_event,
        reference=reference,
        description=_truncate(description),
        created_by=actor_account_id,
    )
    db.add(header)
    db.flush()
    _write_lines(db, org_id=org_id, header=header, lines=materialised)
    return header


def ensure_journal_header(
    db: Session, *, org_id: uuid.UUID, journal_entry_id: uuid.UUID
) -> JournalEntry:
    """Returns the header for a journal, creating a LEGACY one first if the
    journal pre-dates the journal_entries table. Existing ledger rows are
    never touched: the header borrows the earliest line's description and
    takes its accounting date from the earliest line's created_at (Nigeria
    time), which is what every report already treats as the date.
    """
    header = db.get(JournalEntry, journal_entry_id)
    if header is not None:
        if header.org_id != org_id:
            raise ValueError("journal not found")
        return header

    first_line = db.execute(
        select(LedgerEntry.created_at, LedgerEntry.description)
        .where(LedgerEntry.org_id == org_id, LedgerEntry.journal_entry_id == journal_entry_id)
        .order_by(LedgerEntry.created_at, LedgerEntry.id)
        .limit(1)
    ).first()
    if first_line is None:
        raise ValueError("journal not found")
    created_at, description = first_line

    header = JournalEntry(
        id=journal_entry_id,
        org_id=org_id,
        entry_date=lagos_date(created_at),
        source_type=JournalSourceType.LEGACY,
        source_id=None,
        source_event="adopted",
        description=_truncate(description or "Journal entry recorded before journal headers"),
    )
    db.add(header)
    db.flush()
    return header


def reverse_journal(
    db: Session,
    *,
    org_id: uuid.UUID,
    journal_id: uuid.UUID,
    reversal_date: date,
    reason: str,
    actor_account_id: uuid.UUID | None = None,
    line_description: str | None = None,
) -> JournalEntry:
    """Posts the correcting entry for one journal: every line mirrored with
    debit and credit swapped, linked back through reversal_of_id. The
    original is never edited — the ledger is append-only.

    A journal can be reversed once (the unique index on reversal_of_id is
    the backstop for the check here), and a reversal cannot itself be
    reversed — post a fresh entry instead.

    The mirrored lines are not checked against the chart: reversing a
    posting that was accepted must stay possible even if one of its
    accounts has since been deactivated.
    """
    if not reason or not reason.strip():
        raise ValueError("a reason is required to reverse a journal")

    original = ensure_journal_header(db, org_id=org_id, journal_entry_id=journal_id)
    if original.reversal_of_id is not None:
        raise ValueError("a reversal cannot itself be reversed")
    if (
        db.scalar(select(JournalEntry.id).where(JournalEntry.reversal_of_id == original.id))
        is not None
    ):
        raise ValueError("this journal has already been reversed")

    original_lines = db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.org_id == org_id, LedgerEntry.journal_entry_id == original.id)
        .order_by(LedgerEntry.created_at, LedgerEntry.id)
    )
    mirrored = mirror_postings(
        (
            PostingLine(
                account=entry.account,
                debit_minor=entry.debit_minor,
                credit_minor=entry.credit_minor,
                description=entry.description,
                employee_id=entry.employee_id,
                department_id=entry.department_id,
                pay_run_id=entry.pay_run_id,
            )
            for entry in original_lines
        ),
        description=line_description or f"reversal: {reason.strip()}",
    )
    assert_balanced(mirrored)

    header = JournalEntry(
        org_id=org_id,
        entry_date=reversal_date,
        source_type=JournalSourceType.REVERSAL,
        source_id=None,
        source_event="journal.reversed",
        description=_truncate(f"Reversal of: {original.description}"),
        reversal_of_id=original.id,
        reversal_reason=_truncate(reason.strip()),
        created_by=actor_account_id,
    )
    db.add(header)
    db.flush()
    _write_lines(db, org_id=org_id, header=header, lines=mirrored)
    return header
