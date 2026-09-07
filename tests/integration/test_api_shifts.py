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


def _admin_headers(org_id, email: str = "shift-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_shifts() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Morning", "start_time": "08:00:00", "end_time": "16:00:00"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Morning"
    assert body["start_time"] == "08:00:00"
    assert body["end_time"] == "16:00:00"

    listed = client.get("/api/v1/shifts", headers=headers)
    assert listed.status_code == 200
    assert [s["name"] for s in listed.json()] == ["Morning"]


def test_overnight_shift_is_valid() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="shift-admin-overnight@example.com")

    created = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Night", "start_time": "22:00:00", "end_time": "06:00:00"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["start_time"] == "22:00:00"
    assert created.json()["end_time"] == "06:00:00"


def test_duplicate_shift_name_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="shift-admin2@example.com")

    first = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Morning", "start_time": "08:00:00", "end_time": "16:00:00"},
    )
    assert first.status_code == 201

    dupe = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Morning", "start_time": "09:00:00", "end_time": "17:00:00"},
    )
    assert dupe.status_code in (400, 409, 500)


def test_update_shift() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="shift-admin3@example.com")

    created = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Afternoon", "start_time": "12:00:00", "end_time": "20:00:00"},
    )
    assert created.status_code == 201, created.text

    shift_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/shifts/{shift_id}", headers=headers, json={"end_time": "21:00:00"}
    )
    assert updated.status_code == 200
    assert updated.json()["end_time"] == "21:00:00"
    assert updated.json()["start_time"] == "12:00:00"


def test_employee_can_be_assigned_to_a_shift() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="shift-admin4@example.com")

    shift = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Morning", "start_time": "08:00:00", "end_time": "16:00:00"},
    )
    shift_id = shift.json()["id"]

    employee_id = create_employee(org_id, employee_number="EMP-200")
    updated = client.patch(
        f"/api/v1/employees/{employee_id}",
        headers=headers,
        json={"shift_id": shift_id},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["shift_id"] == shift_id


def test_manager_can_view_but_not_manage_shifts() -> None:
    org_id = create_org()
    email = "shift-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-300")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/shifts", headers=headers)
    assert listed.status_code == 200

    denied = client.post(
        "/api/v1/shifts",
        headers=headers,
        json={"name": "Should Not Work", "start_time": "08:00:00", "end_time": "16:00:00"},
    )
    assert denied.status_code == 403


def test_employee_role_cannot_view_shifts() -> None:
    org_id = create_org()
    email = "shift-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-400")
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/shifts", headers=headers)
    assert response.status_code == 403
