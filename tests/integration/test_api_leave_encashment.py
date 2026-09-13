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


def _admin_headers(org_id, email: str = "encashment-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def _gross_by_employee_id(headers: dict[str, str], pay_run_id: str) -> dict[str, int]:
    payslips = client.get(f"/api/v1/pay-runs/{pay_run_id}/payslips", headers=headers).json()
    return {p["employee_id"]: p["gross_minor"] for p in payslips}


def test_encashment_blocked_beyond_leave_balance() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_email = "encashment-worker@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-ENC-1")
    employee_headers = auth_headers(login(employee_email)["access_token"])

    # Default entitlement is 20 days (api_helpers.create_employee doesn't
    # override it); asking to encash more than that must be rejected at
    # approval time even though submitting it is allowed.
    submitted = client.post(
        "/api/v1/leave-encashment/me",
        headers=employee_headers,
        json={"requested_date": "2026-01-10", "days": 25, "amount_minor": 200_000_00},
    )
    assert submitted.status_code == 201, submitted.text
    request_id = submitted.json()["id"]

    blocked = client.post(f"/api/v1/leave-encashment/{request_id}/approve", headers=headers)
    assert blocked.status_code == 400, blocked.text


def test_approved_encashment_is_paid_by_next_pay_run_and_reduces_balance() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="encashment-admin2@example.com")
    employee_email = "encashment-worker2@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-ENC-2"
    )
    control_id = create_employee(org_id, employee_number="EMP-ENC-2-CTRL")
    employee_headers = auth_headers(login(employee_email)["access_token"])

    submitted = client.post(
        "/api/v1/leave-encashment/me",
        headers=employee_headers,
        json={"requested_date": "2026-01-10", "days": 5, "amount_minor": 50_000_00},
    )
    assert submitted.status_code == 201, submitted.text
    request_id = submitted.json()["id"]

    approved = client.post(f"/api/v1/leave-encashment/{request_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    balance = client.get("/api/v1/leave-requests/me/balance", headers=employee_headers).json()
    assert balance["remaining_days"] == 15  # 20 entitlement - 5 encashed

    run = create_and_lock_pay_run(headers, employee_ids=[employee_id, control_id])
    gross_by_employee = _gross_by_employee_id(headers, run["id"])
    assert gross_by_employee[str(employee_id)] == gross_by_employee[str(control_id)] + 50_000_00

    paid = client.get("/api/v1/leave-encashment/me", headers=employee_headers).json()[0]
    assert paid["status"] == "paid"
    assert paid["pay_run_id"] == run["id"]


def test_reversing_pay_run_restores_encashment_to_approved_and_unpaid() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="encashment-admin3@example.com")
    employee_email = "encashment-worker3@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-ENC-3"
    )
    employee_headers = auth_headers(login(employee_email)["access_token"])

    submitted = client.post(
        "/api/v1/leave-encashment/me",
        headers=employee_headers,
        json={"requested_date": "2026-01-10", "days": 3, "amount_minor": 30_000_00},
    )
    request_id = submitted.json()["id"]
    client.post(f"/api/v1/leave-encashment/{request_id}/approve", headers=headers)

    run = create_and_lock_pay_run(headers, employee_ids=[employee_id])
    paid = client.get("/api/v1/leave-encashment/me", headers=employee_headers).json()[0]
    assert paid["status"] == "paid"

    reverse = client.post(f"/api/v1/pay-runs/{run['id']}/reverse", headers=headers)
    assert reverse.status_code == 200, reverse.text

    restored = client.get("/api/v1/leave-encashment/me", headers=employee_headers).json()[0]
    assert restored["status"] == "approved"
    assert restored["pay_run_id"] is None

    # Reversal only undoes the payment, not the approval decision itself —
    # the days stay debited (same as before the run existed) until whoever
    # actually pays this out next does so.
    balance = client.get("/api/v1/leave-requests/me/balance", headers=employee_headers).json()
    assert balance["remaining_days"] == 17
