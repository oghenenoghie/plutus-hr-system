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


def _admin_headers(org_id, email: str = "branch-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_branches() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/branches",
        headers=headers,
        json={"name": "Lagos HQ", "state": "Lagos", "address": "1 Marina Road"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Lagos HQ"
    assert body["state"] == "Lagos"
    assert body["address"] == "1 Marina Road"
    assert body["manager_id"] is None

    listed = client.get("/api/v1/branches", headers=headers)
    assert listed.status_code == 200
    assert [b["name"] for b in listed.json()] == ["Lagos HQ"]


def test_duplicate_branch_name_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="branch-admin2@example.com")

    first = client.post("/api/v1/branches", headers=headers, json={"name": "Abuja Branch"})
    assert first.status_code == 201

    dupe = client.post("/api/v1/branches", headers=headers, json={"name": "Abuja Branch"})
    assert dupe.status_code in (400, 409, 500)


def test_assign_branch_manager_and_update() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="branch-admin3@example.com")
    manager_id = create_employee(org_id, employee_number="EMP-100")

    created = client.post(
        "/api/v1/branches",
        headers=headers,
        json={"name": "Port Harcourt", "manager_id": str(manager_id)},
    )
    assert created.status_code == 201, created.text
    assert created.json()["manager_id"] == str(manager_id)

    branch_id = created.json()["id"]
    renamed = client.patch(
        f"/api/v1/branches/{branch_id}",
        headers=headers,
        json={"name": "PH Branch", "state": "Rivers"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "PH Branch"
    assert renamed.json()["state"] == "Rivers"
    assert renamed.json()["manager_id"] == str(manager_id)


def test_manager_can_view_but_not_manage_branches() -> None:
    org_id = create_org()
    email = "branch-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-300")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/branches", headers=headers)
    assert listed.status_code == 200

    denied = client.post("/api/v1/branches", headers=headers, json={"name": "Should Not Work"})
    assert denied.status_code == 403


def test_employee_role_cannot_view_branches() -> None:
    org_id = create_org()
    email = "branch-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-400")
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/branches", headers=headers)
    assert response.status_code == 403
