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


def test_admin_can_create_an_employee() -> None:
    org_id = create_org()
    admin_email = "employees-admin1@example.com"
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=admin_email)
    tokens = login_with_mfa(account_id, admin_email, Role.ADMIN)

    response = client.post(
        "/api/v1/employees",
        headers=auth_headers(tokens["access_token"]),
        json={
            "employee_number": "EMP-100",
            "full_name": "Ada Okafor",
            "state_of_residence": "Lagos",
            "employment_type": "permanent",
            "date_of_joining": "2025-01-01",
            "basic_minor": 30000000,
            "housing_minor": 15000000,
            "transport_minor": 5000000,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["employee_number"] == "EMP-100"


def test_employee_role_cannot_create_an_employee() -> None:
    org_id = create_org()
    employee_account_email = "worker@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=employee_account_email)
    create_employee(org_id, account_id=account_id)
    tokens = login(employee_account_email)

    response = client.post(
        "/api/v1/employees",
        headers=auth_headers(tokens["access_token"]),
        json={
            "employee_number": "EMP-999",
            "full_name": "Someone Else",
            "state_of_residence": "Lagos",
            "employment_type": "permanent",
            "date_of_joining": "2025-01-01",
            "basic_minor": 1,
            "housing_minor": 1,
            "transport_minor": 1,
        },
    )
    assert response.status_code == 403


def test_employee_sees_own_record_via_me_but_not_via_list() -> None:
    org_id = create_org()
    email = "self-service@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    employee_id = create_employee(org_id, account_id=account_id, employee_number="EMP-200")
    tokens = login(email)
    headers = auth_headers(tokens["access_token"])

    me = client.get("/api/v1/employees/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == str(employee_id)

    listing = client.get("/api/v1/employees", headers=headers)
    assert listing.status_code == 403


def test_employee_with_no_linked_record_gets_403_on_me() -> None:
    org_id = create_org()
    email = "no-link@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    tokens = login(email)

    response = client.get("/api/v1/employees/me", headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 403


def test_manager_sees_only_direct_reports() -> None:
    org_id = create_org()
    manager_email = "manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-001")
    report_id = create_employee(org_id, employee_number="EMP-300", manager_id=manager_id)
    create_employee(org_id, employee_number="EMP-301")  # not a report

    tokens = login(manager_email)
    response = client.get("/api/v1/employees", headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 200
    ids = {e["id"] for e in response.json()}
    assert ids == {str(report_id)}


def test_admin_can_link_account_and_update_employee() -> None:
    org_id = create_org()
    admin_email = "employees-admin@example.com"
    admin_account_id = create_account_with_membership(org_id, Role.ADMIN, email=admin_email)
    tokens = login_with_mfa(admin_account_id, admin_email, Role.ADMIN)
    headers = auth_headers(tokens["access_token"])

    employee_id = create_employee(org_id, employee_number="EMP-400")
    worker_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="worker2@example.com"
    )

    link = client.post(
        f"/api/v1/employees/{employee_id}/link-account",
        headers=headers,
        json={"account_id": str(worker_account_id)},
    )
    assert link.status_code == 200
    assert link.json()["account_id"] == str(worker_account_id)

    update = client.patch(
        f"/api/v1/employees/{employee_id}", headers=headers, json={"basic_minor": 500_000_00}
    )
    assert update.status_code == 200
    assert update.json()["basic_minor"] == 500_000_00
