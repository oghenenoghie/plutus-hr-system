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


def _admin_headers(org_id, email: str = "dues-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_assign_membership_and_employee_can_see_it() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    employee_email = "union-member@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-900")

    created = client.post(
        f"/api/v1/union-memberships/employees/{employee_id}",
        headers=headers,
        json={
            "union_name": "National Union of Finance Workers",
            "membership_number": "NUFW-1001",
            "monthly_dues_minor": 500_00,
            "joined_date": "2026-01-01",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "active"
    membership_id = body["id"]

    listed = client.get(f"/api/v1/union-memberships/employees/{employee_id}", headers=headers)
    assert listed.status_code == 200
    assert [m["id"] for m in listed.json()] == [membership_id]

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/union-memberships/me", headers=employee_headers)
    assert mine.status_code == 200
    assert [m["id"] for m in mine.json()] == [membership_id]


def test_negative_dues_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="dues-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-901")

    response = client.post(
        f"/api/v1/union-memberships/employees/{employee_id}",
        headers=headers,
        json={
            "union_name": "Test Union",
            "monthly_dues_minor": -100,
            "joined_date": "2026-01-01",
        },
    )
    assert response.status_code == 400


def test_suspend_then_terminate_membership() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="dues-admin3@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-902")

    membership_id = client.post(
        f"/api/v1/union-memberships/employees/{employee_id}",
        headers=headers,
        json={
            "union_name": "Test Union",
            "monthly_dues_minor": 200_00,
            "joined_date": "2026-01-01",
        },
    ).json()["id"]

    suspended = client.patch(
        f"/api/v1/union-memberships/{membership_id}", headers=headers, json={"status": "suspended"}
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    terminated = client.post(
        f"/api/v1/union-memberships/{membership_id}/terminate",
        headers=headers,
        json={"terminated_date": "2026-06-01"},
    )
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "terminated"
    assert terminated.json()["terminated_date"] == "2026-06-01"

    already_terminated = client.post(
        f"/api/v1/union-memberships/{membership_id}/terminate",
        headers=headers,
        json={"terminated_date": "2026-07-01"},
    )
    assert already_terminated.status_code == 400


def test_manager_cannot_assign_or_view_union_memberships() -> None:
    org_id = create_org()
    email = "dues-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-903")
    headers = auth_headers(login(email)["access_token"])

    employee_id = create_employee(org_id, employee_number="EMP-904")

    denied_create = client.post(
        f"/api/v1/union-memberships/employees/{employee_id}",
        headers=headers,
        json={
            "union_name": "Test Union",
            "monthly_dues_minor": 100_00,
            "joined_date": "2026-01-01",
        },
    )
    assert denied_create.status_code == 403

    denied_list = client.get(f"/api/v1/union-memberships/employees/{employee_id}", headers=headers)
    assert denied_list.status_code == 403
