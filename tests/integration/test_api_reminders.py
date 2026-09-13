from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "reminder-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_reminder_job_notifies_admins_of_upcoming_deadlines() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_id = create_employee(org_id, employee_number="EMP-4000")
    create_and_lock_pay_run(headers, employee_ids=[employee_id])

    result = client.post("/api/v1/reminders/run", headers=headers, params={"as_of": "2026-01-31"})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["deadline_count"] > 0
    assert body["notifications_created"] == 1

    my_notifications = client.get("/api/v1/notifications/me", headers=headers)
    assert my_notifications.status_code == 200
    assert len(my_notifications.json()) == 1
    assert "deadline" in my_notifications.json()[0]["body"].lower()


def test_reminder_job_flags_stale_pending_approval_requests() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="reminder-admin2@example.com")

    client.post(
        "/api/v1/approval-workflows/templates",
        headers=headers,
        json={"entity_type": "expense", "name": "Expense sign-off", "approver_roles": ["admin"]},
    )
    client.post(
        "/api/v1/approval-workflows/requests",
        headers=headers,
        json={"entity_type": "expense", "entity_id": "00000000-0000-0000-0000-000000000001"},
    )

    # ApprovalRequest.created_at is a real wall-clock timestamp (unlike the
    # fictional business dates used elsewhere in this suite), so as_of must
    # be safely in the future relative to actual "now" for a zero-day
    # staleness cutoff to catch a request created moments ago.
    result = client.post(
        "/api/v1/reminders/run",
        headers=headers,
        params={"as_of": "2030-01-01", "stale_after_days": 0},
    )
    assert result.status_code == 200, result.text
    assert result.json()["stale_approval_count"] == 1


def test_reminder_job_is_a_no_op_when_nothing_needs_attention() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="reminder-admin3@example.com")

    result = client.post("/api/v1/reminders/run", headers=headers, params={"as_of": "2026-01-01"})
    assert result.status_code == 200, result.text
    assert result.json() == {
        "deadline_count": 0,
        "stale_approval_count": 0,
        "notifications_created": 0,
    }


def test_non_admin_cannot_run_reminders() -> None:
    org_id = create_org()
    email = "reminder-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    headers = auth_headers(login(email)["access_token"])
    denied = client.post("/api/v1/reminders/run", headers=headers)
    assert denied.status_code == 403
