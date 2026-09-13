from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
)


def test_employee_clocks_in_and_out() -> None:
    org_id = create_org()
    email = "attendance-worker@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-1100")
    headers = auth_headers(login(email)["access_token"])

    clock_in = client.post("/api/v1/attendance/clock-in", headers=headers)
    assert clock_in.status_code == 201, clock_in.text
    assert clock_in.json()["clock_in_at"] is not None
    assert clock_in.json()["clock_out_at"] is None

    clock_out = client.post("/api/v1/attendance/clock-out", headers=headers)
    assert clock_out.status_code == 200, clock_out.text
    assert clock_out.json()["clock_out_at"] is not None

    mine = client.get("/api/v1/attendance/me", headers=headers)
    assert mine.status_code == 200
    assert len(mine.json()) == 1


def test_cannot_clock_in_twice_or_clock_out_without_clocking_in() -> None:
    org_id = create_org()
    email = "attendance-worker2@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-1101")
    headers = auth_headers(login(email)["access_token"])

    without_clock_in = client.post("/api/v1/attendance/clock-out", headers=headers)
    assert without_clock_in.status_code == 400

    first = client.post("/api/v1/attendance/clock-in", headers=headers)
    assert first.status_code == 201

    second = client.post("/api/v1/attendance/clock-in", headers=headers)
    assert second.status_code == 400

    client.post("/api/v1/attendance/clock-out", headers=headers)
    double_clock_out = client.post("/api/v1/attendance/clock-out", headers=headers)
    assert double_clock_out.status_code == 400


def test_manager_can_view_report_attendance_but_not_a_non_report() -> None:
    org_id = create_org()

    manager_email = "attendance-manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-200")

    report_email = "attendance-report@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    report_id = create_employee(
        org_id, account_id=report_account_id, employee_number="EMP-1102", manager_id=manager_id
    )
    non_report_id = create_employee(org_id, employee_number="EMP-1103")

    report_headers = auth_headers(login(report_email)["access_token"])
    client.post("/api/v1/attendance/clock-in", headers=report_headers)

    manager_headers = auth_headers(login(manager_email)["access_token"])
    allowed = client.get(f"/api/v1/attendance/employees/{report_id}", headers=manager_headers)
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1

    denied = client.get(f"/api/v1/attendance/employees/{non_report_id}", headers=manager_headers)
    assert denied.status_code == 403
