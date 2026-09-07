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


def _admin_headers(org_id, email: str = "assets-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_assets() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/company-assets",
        headers=headers,
        json={"name": "MacBook Pro 14", "asset_tag": "AST-001", "category": "laptop"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "available"

    listed = client.get("/api/v1/company-assets", headers=headers)
    assert listed.status_code == 200
    assert [a["asset_tag"] for a in listed.json()] == ["AST-001"]


def test_duplicate_asset_tag_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="assets-admin2@example.com")

    first = client.post(
        "/api/v1/company-assets",
        headers=headers,
        json={"name": "iPhone 15", "asset_tag": "AST-100", "category": "phone"},
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/api/v1/company-assets",
        headers=headers,
        json={"name": "iPhone 15 Pro", "asset_tag": "AST-100", "category": "phone"},
    )
    assert duplicate.status_code == 400


def test_assign_and_return_asset_updates_status() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="assets-admin3@example.com")

    employee_email = "asset-holder@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-950")

    asset_id = client.post(
        "/api/v1/company-assets",
        headers=headers,
        json={"name": "Dell Latitude", "asset_tag": "AST-200", "category": "laptop"},
    ).json()["id"]

    assigned = client.post(
        f"/api/v1/company-assets/{asset_id}/assignments",
        headers=headers,
        json={"employee_id": str(employee_id), "assigned_date": "2026-09-01"},
    )
    assert assigned.status_code == 201, assigned.text
    assignment_id = assigned.json()["id"]

    asset_after_assign = client.get(f"/api/v1/company-assets/{asset_id}", headers=headers)
    assert asset_after_assign.json()["status"] == "assigned"

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/company-assets/me", headers=employee_headers)
    assert mine.status_code == 200
    assert [a["id"] for a in mine.json()] == [assignment_id]

    returned = client.post(
        f"/api/v1/company-assets/assignments/{assignment_id}/return",
        headers=headers,
        json={"returned_date": "2026-09-10", "condition_notes": "Minor scratches."},
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["returned_date"] == "2026-09-10"

    asset_after_return = client.get(f"/api/v1/company-assets/{asset_id}", headers=headers)
    assert asset_after_return.json()["status"] == "available"

    mine_after_return = client.get("/api/v1/company-assets/me", headers=employee_headers)
    assert mine_after_return.json() == []


def test_cannot_assign_an_already_assigned_asset() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="assets-admin4@example.com")

    employee_id_1 = create_employee(org_id, employee_number="EMP-951")
    employee_id_2 = create_employee(org_id, employee_number="EMP-952")

    asset_id = client.post(
        "/api/v1/company-assets",
        headers=headers,
        json={"name": "Office Chair", "asset_tag": "AST-300", "category": "furniture"},
    ).json()["id"]

    first = client.post(
        f"/api/v1/company-assets/{asset_id}/assignments",
        headers=headers,
        json={"employee_id": str(employee_id_1), "assigned_date": "2026-09-01"},
    )
    assert first.status_code == 201

    second = client.post(
        f"/api/v1/company-assets/{asset_id}/assignments",
        headers=headers,
        json={"employee_id": str(employee_id_2), "assigned_date": "2026-09-02"},
    )
    assert second.status_code == 400


def test_manager_can_view_but_not_manage_assets() -> None:
    org_id = create_org()
    email = "assets-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-953")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/company-assets", headers=headers)
    assert listed.status_code == 200

    denied = client.post(
        "/api/v1/company-assets",
        headers=headers,
        json={"name": "Should Not Work", "asset_tag": "AST-999", "category": "other"},
    )
    assert denied.status_code == 403
