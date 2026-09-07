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


def _admin_headers(org_id, email: str = "coa-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_seed_defaults_creates_default_accounts_and_is_idempotent() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    codes = {account["code"] for account in seeded.json()}
    assert "cash" in codes
    assert "paye_payable" in codes
    assert all(account["is_system"] for account in seeded.json())

    listed = client.get("/api/v1/chart-of-accounts", headers=headers)
    assert len(listed.json()) == len(codes)

    reseeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert reseeded.status_code == 200
    assert reseeded.json() == []

    listed_again = client.get("/api/v1/chart-of-accounts", headers=headers)
    assert len(listed_again.json()) == len(codes)


def test_admin_can_create_custom_account_and_duplicate_code_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="coa-admin2@example.com")

    created = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={"code": "accounts_receivable", "name": "Accounts Receivable", "type": "asset"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_system"] is False

    duplicate = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={"code": "accounts_receivable", "name": "Duplicate", "type": "asset"},
    )
    assert duplicate.status_code == 400

    account_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/chart-of-accounts/{account_id}",
        headers=headers,
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False


def test_manager_and_employee_cannot_manage_chart_of_accounts() -> None:
    org_id = create_org()

    manager_email = "coa-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied_manager = client.get("/api/v1/chart-of-accounts", headers=manager_headers)
    assert denied_manager.status_code == 403

    employee_email = "coa-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-961")
    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied_employee = client.post(
        "/api/v1/chart-of-accounts",
        headers=employee_headers,
        json={"code": "x", "name": "X", "type": "asset"},
    )
    assert denied_employee.status_code == 403
