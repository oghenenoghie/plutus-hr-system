"""app/workers/scheduler.py — the in-process daily jobs that replace what
used to be purely pull-based, externally-triggered endpoints. These tests
call the "for every org" job functions directly (never through FastAPI's
lifespan, which the test suite's TestClient never triggers), against real
orgs created the normal way — verifying they process every org, keep each
org's data isolated, and don't let one org's failure stop the rest.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app.models import Role
from app.services.reminders import run_reminder_job as real_run_reminder_job
from app.workers.scheduler import (
    generate_due_bills_for_all_orgs,
    generate_due_invoices_for_all_orgs,
    run_reminders_for_all_orgs,
)
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id: uuid.UUID, email: str) -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_run_reminders_for_all_orgs_notifies_each_org_separately() -> None:
    org_a = create_org()
    headers_a = _admin_headers(org_a, "sched-reminders-a@example.com")
    employee_a = create_employee(org_a, employee_number="EMP-SCHED-A")
    client.patch(
        f"/api/v1/employees/{employee_a}",
        headers=headers_a,
        json={"contract_end_date": datetime.now(UTC).date().isoformat()},
    )

    org_b = create_org()
    headers_b = _admin_headers(org_b, "sched-reminders-b@example.com")
    create_employee(org_b, employee_number="EMP-SCHED-B")

    run_reminders_for_all_orgs()

    notifications_a = client.get("/api/v1/notifications/me", headers=headers_a).json()
    assert len(notifications_a) == 1
    assert "contract" in notifications_a[0]["body"].lower()

    # Org B has no expiring contracts, stale approvals, or deadlines — the
    # scheduled run must not manufacture a notification for it.
    notifications_b = client.get("/api/v1/notifications/me", headers=headers_b).json()
    assert notifications_b == []


def test_run_reminders_for_all_orgs_skips_a_failing_org_and_continues() -> None:
    org_a = create_org()
    _admin_headers(org_a, "sched-reminders-fail-a@example.com")
    create_employee(org_a, employee_number="EMP-SCHED-FAIL-A")

    org_b = create_org()
    headers_b = _admin_headers(org_b, "sched-reminders-fail-b@example.com")
    employee_id = create_employee(org_b, employee_number="EMP-SCHED-FAIL-B")
    client.patch(
        f"/api/v1/employees/{employee_id}",
        headers=headers_b,
        json={"contract_end_date": datetime.now(UTC).date().isoformat()},
    )

    def _raise_for_org_a(db, org_id, **kwargs):  # type: ignore[no-untyped-def]
        if org_id == org_a:
            raise RuntimeError("boom")
        return real_run_reminder_job(db, org_id, **kwargs)

    with patch("app.workers.scheduler.run_reminder_job", side_effect=_raise_for_org_a):
        run_reminders_for_all_orgs()

    # Org B still got processed even though org A's run blew up.
    notifications_b = client.get("/api/v1/notifications/me", headers=headers_b).json()
    assert len(notifications_b) == 1


def test_generate_due_bills_for_all_orgs_processes_every_org() -> None:
    org_a = create_org()
    headers_a = _admin_headers(org_a, "sched-bills-a@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers_a)
    vendor_a = client.post("/api/v1/vendors", headers=headers_a, json={"name": "Vendor A"}).json()[
        "id"
    ]
    client.post(
        "/api/v1/recurring-bills",
        headers=headers_a,
        json={
            "vendor_id": vendor_a,
            "bill_number_prefix": "RENT-A",
            "expense_account_code": "contractor_expense",
            "amount_minor": 10_000_00,
            "frequency": "monthly",
            "next_run_date": datetime.now(UTC).date().isoformat(),
        },
    )

    org_b = create_org()
    headers_b = _admin_headers(org_b, "sched-bills-b@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers_b)
    vendor_b = client.post("/api/v1/vendors", headers=headers_b, json={"name": "Vendor B"}).json()[
        "id"
    ]
    client.post(
        "/api/v1/recurring-bills",
        headers=headers_b,
        json={
            "vendor_id": vendor_b,
            "bill_number_prefix": "RENT-B",
            "expense_account_code": "contractor_expense",
            "amount_minor": 20_000_00,
            "frequency": "monthly",
            "next_run_date": datetime.now(UTC).date().isoformat(),
        },
    )

    generate_due_bills_for_all_orgs()

    bills_a = client.get("/api/v1/bills", headers=headers_a).json()
    assert len(bills_a) == 1
    assert bills_a[0]["bill_number"].startswith("RENT-A-")

    bills_b = client.get("/api/v1/bills", headers=headers_b).json()
    assert len(bills_b) == 1
    assert bills_b[0]["bill_number"].startswith("RENT-B-")


def test_generate_due_invoices_for_all_orgs_processes_every_org() -> None:
    org_a = create_org()
    headers_a = _admin_headers(org_a, "sched-invoices-a@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers_a)
    customer_a = client.post(
        "/api/v1/customers", headers=headers_a, json={"name": "Customer A"}
    ).json()["id"]
    client.post(
        "/api/v1/recurring-invoices",
        headers=headers_a,
        json={
            "customer_id": customer_a,
            "invoice_number_prefix": "INV-A",
            "revenue_account_code": "revenue",
            "amount_minor": 15_000_00,
            "frequency": "monthly",
            "next_run_date": datetime.now(UTC).date().isoformat(),
        },
    )

    generate_due_invoices_for_all_orgs()

    invoices_a = client.get("/api/v1/invoices", headers=headers_a).json()
    assert len(invoices_a) == 1
    assert invoices_a[0]["invoice_number"].startswith("INV-A-")
