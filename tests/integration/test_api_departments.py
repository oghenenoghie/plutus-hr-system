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


def _admin_headers(org_id, email: str = "dept-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_departments() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post("/api/v1/departments", headers=headers, json={"name": "Finance"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Finance"
    assert body["manager_id"] is None

    listed = client.get("/api/v1/departments", headers=headers)
    assert listed.status_code == 200
    assert [d["name"] for d in listed.json()] == ["Finance"]


def test_duplicate_department_name_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="dept-admin2@example.com")

    first = client.post("/api/v1/departments", headers=headers, json={"name": "Engineering"})
    assert first.status_code == 201

    dupe = client.post("/api/v1/departments", headers=headers, json={"name": "Engineering"})
    assert dupe.status_code in (400, 409, 500)


def test_assign_department_manager_and_update() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="dept-admin3@example.com")
    manager_id = create_employee(org_id, employee_number="EMP-100")

    created = client.post(
        "/api/v1/departments",
        headers=headers,
        json={"name": "Operations", "manager_id": str(manager_id)},
    )
    assert created.status_code == 201, created.text
    assert created.json()["manager_id"] == str(manager_id)

    department_id = created.json()["id"]
    renamed = client.patch(
        f"/api/v1/departments/{department_id}", headers=headers, json={"name": "Ops"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Ops"
    assert renamed.json()["manager_id"] == str(manager_id)


def test_employee_can_be_assigned_to_a_department() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="dept-admin4@example.com")

    department = client.post("/api/v1/departments", headers=headers, json={"name": "Sales"})
    department_id = department.json()["id"]

    employee_id = create_employee(org_id, employee_number="EMP-200")
    updated = client.patch(
        f"/api/v1/employees/{employee_id}",
        headers=headers,
        json={"department_id": department_id},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["department_id"] == department_id


def test_manager_can_view_but_not_manage_departments() -> None:
    org_id = create_org()
    email = "dept-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-300")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/departments", headers=headers)
    assert listed.status_code == 200

    denied = client.post("/api/v1/departments", headers=headers, json={"name": "Should Not Work"})
    assert denied.status_code == 403


def test_employee_role_cannot_view_departments() -> None:
    org_id = create_org()
    email = "dept-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-400")
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/departments", headers=headers)
    assert response.status_code == 403
