"""Journal headers, reversals and statutory-remittance posting, end to end
through the API (and the posting engine directly for the cases the API can't
reach, such as a legacy journal that predates headers)."""

import uuid
from collections import defaultdict
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.domain.accounting.posting_rules import PostingLine
from app.models import AccountingSettings, ChartAccount, JournalEntry, LedgerEntry, Role
from app.models.journal_entry import JournalSourceType
from app.services.organisation import signup_organisation
from app.services.posting import post_journal, reverse_journal, today_lagos
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
)


def _admin(org_id: uuid.UUID) -> dict[str, str]:
    email = f"admin-{uuid.uuid4()}@example.com"
    create_account_with_membership(org_id, Role.ADMIN, email=email)
    return auth_headers(login(email)["access_token"])


def _lock_run(headers: dict[str, str], employee_id: uuid.UUID) -> str:
    body = {
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "frequency": "monthly",
        "employee_ids": [str(employee_id)],
    }
    created = client.post("/api/v1/pay-runs", headers=headers, json=body)
    assert created.status_code == 201, created.text
    run_id: str = created.json()["id"]
    validated = client.post(f"/api/v1/pay-runs/{run_id}/validate", headers=headers, json={})
    assert validated.status_code == 200, validated.text
    locked = client.post(f"/api/v1/pay-runs/{run_id}/lock", headers=headers)
    assert locked.status_code == 200, locked.text
    return run_id


def _entries(headers: dict[str, str], **params: str) -> list[dict[str, Any]]:
    response = client.get("/api/v1/general-ledger/entries", headers=headers, params=params)
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()
    return rows


def _liability(headers: dict[str, str], scheme: str) -> dict[str, Any]:
    rows = client.get("/api/v1/statutory-liabilities", headers=headers).json()
    return next(row for row in rows if row["scheme"] == scheme)


def _enable_remittance_posting(headers: dict[str, str]) -> None:
    response = client.patch(
        "/api/v1/accounting-settings", headers=headers, json={"post_statutory_remittances": True}
    )
    assert response.status_code == 200, response.text


def _setup(emp_no: str) -> tuple[uuid.UUID, dict[str, str], str]:
    org_id = create_org()
    headers = _admin(org_id)
    employee_id = create_employee(
        org_id,
        employee_number=emp_no,
        basic_minor=900_000_00,
        housing_minor=450_000_00,
        transport_minor=150_000_00,
    )
    return org_id, headers, _lock_run(headers, employee_id)


def test_locking_a_run_posts_balanced_journals_with_headers() -> None:
    _org, headers, run_id = _setup("JE-1")

    rows = _entries(headers, pay_run_id=run_id)
    assert rows
    by_journal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_journal[row["journal_entry_id"]].append(row)

    for journal_id, lines in by_journal.items():
        journal = client.get(
            f"/api/v1/general-ledger/journals/{journal_id}", headers=headers
        ).json()
        # Payslip journals plus the run-level NSITF accrual, both tagged
        # with the run.
        assert (journal["source_type"], journal["source_event"]) in {
            ("payroll", "payslip.locked"),
            ("statutory_accrual", "nsitf.accrued"),
        }
        assert journal["entry_date"] == "2026-01-31"  # period end (audit A11)
        assert journal["source_id"] is not None
        assert sum(line["debit_minor"] for line in lines) == sum(
            line["credit_minor"] for line in lines
        )
        assert len(journal["lines"]) == len(lines)


def test_reversing_a_run_creates_one_reversal_header_per_journal() -> None:
    _org, headers, run_id = _setup("JE-2")
    originals = {row["journal_entry_id"] for row in _entries(headers, pay_run_id=run_id)}

    assert client.post(f"/api/v1/pay-runs/{run_id}/reverse", headers=headers).status_code == 200

    after = _entries(headers, pay_run_id=run_id)
    new_ids = {row["journal_entry_id"] for row in after} - originals
    assert len(new_ids) == len(originals)
    reversed_of = set()
    for journal_id in new_ids:
        journal = client.get(
            f"/api/v1/general-ledger/journals/{journal_id}", headers=headers
        ).json()
        assert journal["source_type"] == "reversal"
        assert journal["reversal_reason"]
        reversed_of.add(journal["reversal_of_id"])
    assert reversed_of == originals

    # Every account nets to zero once the run is reversed.
    net: dict[str, int] = defaultdict(int)
    for row in after:
        net[row["account"]] += row["debit_minor"] - row["credit_minor"]
    assert all(value == 0 for value in net.values())


def test_remit_posts_payable_against_cash_when_enabled() -> None:
    _org, headers, _run = _setup("JE-3")
    _enable_remittance_posting(headers)
    paye = _liability(headers, "paye")
    assert paye["amount_minor"] > 0

    remitted = client.post(
        f"/api/v1/statutory-liabilities/{paye['id']}/remit",
        headers=headers,
        json={"reference": "FIRS-001"},
    )
    assert remitted.status_code == 200, remitted.text
    journal_id = remitted.json()["remittance_journal_id"]
    assert journal_id is not None

    journal = client.get(f"/api/v1/general-ledger/journals/{journal_id}", headers=headers).json()
    assert journal["source_type"] == "statutory_remittance"
    assert journal["source_id"] == paye["id"]
    assert journal["reference"] == "FIRS-001"
    by_account = {line["account"]: line for line in journal["lines"]}
    assert by_account["paye_payable"]["debit_minor"] == paye["amount_minor"]
    assert by_account["cash"]["credit_minor"] == paye["amount_minor"]
    assert all(line["pay_run_id"] is None for line in journal["lines"])

    again = client.post(
        f"/api/v1/statutory-liabilities/{paye['id']}/remit", headers=headers, json={}
    )
    assert again.status_code == 400


def test_remit_posts_nothing_when_disabled() -> None:
    _org, headers, _run = _setup("JE-4")
    paye = _liability(headers, "paye")
    before = len(_entries(headers))

    remitted = client.post(
        f"/api/v1/statutory-liabilities/{paye['id']}/remit", headers=headers, json={}
    )
    assert remitted.status_code == 200, remitted.text
    assert remitted.json()["remittance_journal_id"] is None
    assert len(_entries(headers)) == before


def test_reversing_a_run_does_not_unremit_money_paid_to_the_authority() -> None:
    _org, headers, run_id = _setup("JE-5")
    _enable_remittance_posting(headers)
    paye = _liability(headers, "paye")
    remitted = client.post(
        f"/api/v1/statutory-liabilities/{paye['id']}/remit", headers=headers, json={}
    ).json()
    remit_id = remitted["remittance_journal_id"]

    reversed_run = client.post(
        f"/api/v1/pay-runs/{run_id}/reverse",
        headers=headers,
        json={"acknowledge_filed_or_remitted": True},
    )
    assert reversed_run.status_code == 200, reversed_run.text

    journal = client.get(f"/api/v1/general-ledger/journals/{remit_id}", headers=headers).json()
    assert journal["reversal_of_id"] is None
    assert len(journal["lines"]) == 2
    reversals = [
        row
        for row in _entries(headers, account="paye_payable")
        if row["journal_entry_id"] == remit_id
    ]
    assert len(reversals) == 1
    # Money really left the bank, so the payable ends in debit.
    total = sum(
        r["debit_minor"] - r["credit_minor"] for r in _entries(headers, account="paye_payable")
    )
    assert total == paye["amount_minor"]


def test_enabling_the_flag_seeds_the_chart_and_inactive_account_blocks_remit() -> None:
    org_id, headers, _run = _setup("JE-6")
    _enable_remittance_posting(headers)
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        cash = db.scalar(select(ChartAccount).where(ChartAccount.code == "cash"))
        assert cash is not None  # seeded by enabling the flag
        cash.is_active = False

    paye = _liability(headers, "paye")
    blocked = client.post(
        f"/api/v1/statutory-liabilities/{paye['id']}/remit", headers=headers, json={}
    )
    assert blocked.status_code == 400
    assert "inactive" in blocked.json()["detail"]
    assert _liability(headers, "paye")["status"] != "remitted"


def test_accounting_settings_roles() -> None:
    org_id = create_org()
    email = f"pm-{uuid.uuid4()}@example.com"
    create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    pm = auth_headers(login(email)["access_token"])

    assert client.get("/api/v1/accounting-settings", headers=pm).status_code == 200
    denied = client.patch(
        "/api/v1/accounting-settings", headers=pm, json={"post_statutory_remittances": True}
    )
    assert denied.status_code == 403


def test_signup_seeds_chart_and_enables_remittance_posting() -> None:
    org, _membership = signup_organisation(
        org_name="Fresh Co",
        admin_email=f"fresh-{uuid.uuid4()}@example.com",
        admin_password="s3cret-pass",
    )
    with tenant_session(org.id, uuid.uuid4(), "admin") as db:
        settings = db.get(AccountingSettings, org.id)
        assert settings is not None and settings.post_statutory_remittances
        assert db.scalar(select(ChartAccount).where(ChartAccount.code == "paye_payable"))


def test_journal_entries_are_append_only() -> None:
    org_id = create_org()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        journal = post_journal(
            db,
            org_id=org_id,
            entry_date=today_lagos(),
            source_type=JournalSourceType.MANUAL_JOURNAL,
            source_event="manual.posted",
            description="append-only probe",
            lines=[
                PostingLine(account="cash", debit_minor=100),
                PostingLine(account="equity", credit_minor=100),
            ],
            validate_chart=False,
        )
        journal_id = journal.id

    with pytest.raises(DBAPIError), tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.execute(
            text("UPDATE journal_entries SET description = 'x' WHERE id = :id"), {"id": journal_id}
        )


def test_post_journal_rejects_double_post_and_unbalanced() -> None:
    org_id = create_org()
    source_id = uuid.uuid4()
    lines = [
        PostingLine(account="cash", debit_minor=50),
        PostingLine(account="equity", credit_minor=50),
    ]
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        post_journal(
            db,
            org_id=org_id,
            entry_date=today_lagos(),
            source_type=JournalSourceType.EXPENDITURE,
            source_id=source_id,
            source_event="expenditure.approved",
            description="first",
            lines=lines,
            validate_chart=False,
        )
        with pytest.raises(ValueError, match="already been posted"):
            post_journal(
                db,
                org_id=org_id,
                entry_date=today_lagos(),
                source_type=JournalSourceType.EXPENDITURE,
                source_id=source_id,
                source_event="expenditure.approved",
                description="second",
                lines=lines,
                validate_chart=False,
            )
        with pytest.raises(ValueError, match="does not balance"):
            post_journal(
                db,
                org_id=org_id,
                entry_date=today_lagos(),
                source_type=JournalSourceType.MANUAL_JOURNAL,
                source_event="manual.posted",
                description="bad",
                lines=[
                    PostingLine(account="cash", debit_minor=50),
                    PostingLine(account="equity", credit_minor=40),
                ],
                validate_chart=False,
            )


def test_reversing_a_legacy_journal_adopts_a_legacy_header() -> None:
    org_id = create_org()
    legacy_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        for account, debit, credit in (("cash", 70, 0), ("equity", 0, 70)):
            db.add(
                LedgerEntry(
                    org_id=org_id,
                    journal_entry_id=legacy_id,
                    account=account,
                    debit_minor=debit,
                    credit_minor=credit,
                    description="pre-header entry",
                )
            )
        db.flush()
        assert db.get(JournalEntry, legacy_id) is None

        reversal = reverse_journal(
            db,
            org_id=org_id,
            journal_id=legacy_id,
            reversal_date=today_lagos(),
            reason="correction",
        )
        adopted = db.get(JournalEntry, legacy_id)
        assert adopted is not None
        assert adopted.source_type == JournalSourceType.LEGACY
        assert reversal.reversal_of_id == legacy_id

        with pytest.raises(ValueError, match="already"):
            reverse_journal(
                db,
                org_id=org_id,
                journal_id=legacy_id,
                reversal_date=today_lagos(),
                reason="again",
            )
