from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "roster-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _create_shift(headers: dict[str, str]) -> str:
    created = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Morning", "start_time": "08:00:00", "end_time": "16:00:00"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_admin_rosters_employee_for_a_date_range() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    shift_id = _create_shift(headers)
    employee_id = create_employee(org_id, employee_number="EMP-1000")

    created = client.post(
        "/api/v1/shift-roster",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "shift_id": shift_id,
            "start_date": "2026-03-02",
            "end_date": "2026-03-04",
        },
    )
    assert created.status_code == 201, created.text
    entries = created.json()
    assert [e["work_date"] for e in entries] == ["2026-03-02", "2026-03-03", "2026-03-04"]

    listed = client.get(
        "/api/v1/shift-roster", headers=headers, params={"employee_id": str(employee_id)}
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 3


def test_double_booking_a_date_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="roster-admin2@example.com")
    shift_id = _create_shift(headers)
    employee_id = create_employee(org_id, employee_number="EMP-1001")

    first = client.post(
        "/api/v1/shift-roster",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "shift_id": shift_id,
            "start_date": "2026-03-02",
            "end_date": "2026-03-03",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/shift-roster",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "shift_id": shift_id,
            "start_date": "2026-03-03",
            "end_date": "2026-03-05",
        },
    )
    assert second.status_code == 400


def test_employee_sees_own_roster_via_me() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="roster-admin3@example.com")
    shift_id = _create_shift(headers)

    employee_email = "roster-worker@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-1002"
    )

    client.post(
        "/api/v1/shift-roster",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "shift_id": shift_id,
            "start_date": "2026-03-02",
            "end_date": "2026-03-02",
        },
    )

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/shift-roster/me", headers=employee_headers)
    assert mine.status_code == 200
    assert [e["work_date"] for e in mine.json()] == ["2026-03-02"]


def test_manager_cannot_roster_a_non_report() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="roster-admin4@example.com")
    shift_id = _create_shift(headers)

    manager_email = "roster-manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    create_employee(org_id, account_id=manager_account_id, employee_number="MGR-100")
    non_report_id = create_employee(org_id, employee_number="EMP-1003")

    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied = client.post(
        "/api/v1/shift-roster",
        headers=manager_headers,
        json={
            "employee_id": str(non_report_id),
            "shift_id": shift_id,
            "start_date": "2026-03-02",
            "end_date": "2026-03-02",
        },
    )
    assert denied.status_code == 403
