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


def _admin_headers(org_id, email: str = "overtime-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def _gross_by_employee_id(headers: dict[str, str], pay_run_id: str) -> dict[str, int]:
    payslips = client.get(f"/api/v1/pay-runs/{pay_run_id}/payslips", headers=headers).json()
    return {p["employee_id"]: p["gross_minor"] for p in payslips}


def test_submit_approve_and_get_paid_by_next_pay_run() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_email = "overtime-worker@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-OT-1"
    )
    # An identical-pay control employee with no overtime, in the same run,
    # so the overtime employee's extra gross can be measured directly
    # rather than against a separate (and therefore not-quite-comparable)
    # baseline pay run.
    control_id = create_employee(org_id, employee_number="EMP-OT-1-CTRL")
    employee_headers = auth_headers(login(employee_email)["access_token"])

    submitted = client.post(
        "/api/v1/overtime/me",
        headers=employee_headers,
        json={
            "work_date": "2026-01-15",
            "hours": "5.0",
            "rate_multiplier": "1.5",
            "amount_minor": 30_000_00,
        },
    )
    assert submitted.status_code == 201, submitted.text
    overtime_id = submitted.json()["id"]
    assert submitted.json()["status"] == "pending"

    approved = client.post(f"/api/v1/overtime/{overtime_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    run = create_and_lock_pay_run(headers, employee_ids=[employee_id, control_id])
    gross_by_employee = _gross_by_employee_id(headers, run["id"])
    # Overtime is taxable extra earnings on top of regular gross.
    assert gross_by_employee[str(employee_id)] == gross_by_employee[str(control_id)] + 30_000_00

    my_overtime = client.get("/api/v1/overtime/me", headers=employee_headers).json()
    assert my_overtime[0]["status"] == "paid"
    assert my_overtime[0]["pay_run_id"] == run["id"]

    # Already-paid overtime doesn't get picked up again by a later run.
    run2 = create_and_lock_pay_run(
        headers,
        period_start="2026-02-01",
        period_end="2026-02-28",
        employee_ids=[employee_id, control_id],
    )
    gross_by_employee2 = _gross_by_employee_id(headers, run2["id"])
    assert gross_by_employee2[str(employee_id)] == gross_by_employee2[str(control_id)]


def test_reversing_pay_run_restores_overtime_to_approved_and_unpaid() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="overtime-admin2@example.com")
    employee_email = "overtime-worker2@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-OT-2"
    )
    employee_headers = auth_headers(login(employee_email)["access_token"])

    submitted = client.post(
        "/api/v1/overtime/me",
        headers=employee_headers,
        json={
            "work_date": "2026-01-15",
            "hours": "3.0",
            "rate_multiplier": "1.5",
            "amount_minor": 15_000_00,
        },
    )
    overtime_id = submitted.json()["id"]
    client.post(f"/api/v1/overtime/{overtime_id}/approve", headers=headers)

    run = create_and_lock_pay_run(headers, employee_ids=[employee_id])
    paid = client.get("/api/v1/overtime/me", headers=employee_headers).json()[0]
    assert paid["status"] == "paid"

    reverse = client.post(f"/api/v1/pay-runs/{run['id']}/reverse", headers=headers)
    assert reverse.status_code == 200, reverse.text

    restored = client.get("/api/v1/overtime/me", headers=employee_headers).json()[0]
    assert restored["status"] == "approved"
    assert restored["pay_run_id"] is None


def test_rejected_overtime_is_never_paid() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="overtime-admin3@example.com")
    employee_email = "overtime-worker3@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-OT-3"
    )
    control_id = create_employee(org_id, employee_number="EMP-OT-3-CTRL")
    employee_headers = auth_headers(login(employee_email)["access_token"])

    submitted = client.post(
        "/api/v1/overtime/me",
        headers=employee_headers,
        json={
            "work_date": "2026-01-15",
            "hours": "2.0",
            "rate_multiplier": "1.5",
            "amount_minor": 10_000_00,
        },
    )
    assert submitted.status_code == 201, submitted.text
    overtime_id = submitted.json()["id"]

    rejected = client.post(f"/api/v1/overtime/{overtime_id}/reject", headers=headers)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    run = create_and_lock_pay_run(headers, employee_ids=[employee_id, control_id])
    gross_by_employee = _gross_by_employee_id(headers, run["id"])
    # A rejected entry never contributes to gross.
    assert gross_by_employee[str(employee_id)] == gross_by_employee[str(control_id)]

    still_rejected = client.get("/api/v1/overtime", headers=headers).json()
    assert next(o for o in still_rejected if o["id"] == overtime_id)["status"] == "rejected"
