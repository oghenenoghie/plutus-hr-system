from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    get_membership_id,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "perm-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_employee_default_permissions_are_empty() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="perm-employee@example.com"
    )
    membership_id = get_membership_id(org_id, employee_account_id)

    response = client.get(f"/api/v1/memberships/{membership_id}/permissions", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "employee"
    assert response.json()["permissions"] == []


def test_grant_and_revoke_a_permission_override() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin2@example.com")
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="perm-employee2@example.com"
    )
    membership_id = get_membership_id(org_id, employee_account_id)

    granted = client.put(
        f"/api/v1/memberships/{membership_id}/permissions/override",
        headers=headers,
        json={"permission": "reports.view", "granted": True},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["permissions"] == ["reports.view"]

    revoked = client.delete(
        f"/api/v1/memberships/{membership_id}/permissions/override/reports.view",
        headers=headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["permissions"] == []


def test_override_can_also_revoke_a_default_permission() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin3@example.com")
    manager_email = "perm-manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    membership_id = get_membership_id(org_id, manager_account_id)

    before = client.get(f"/api/v1/memberships/{membership_id}/permissions", headers=headers)
    assert "employees.view" in before.json()["permissions"]

    revoked = client.put(
        f"/api/v1/memberships/{membership_id}/permissions/override",
        headers=headers,
        json={"permission": "employees.view", "granted": False},
    )
    assert revoked.status_code == 200
    assert "employees.view" not in revoked.json()["permissions"]
    assert "performance.manage" in revoked.json()["permissions"]


def test_only_admin_can_manage_permission_overrides() -> None:
    org_id = create_org()
    payroll_manager_email = "perm-pm@example.com"
    payroll_manager_account_id = create_account_with_membership(
        org_id, Role.PAYROLL_MANAGER, email=payroll_manager_email
    )
    tokens = login_with_mfa(payroll_manager_account_id, payroll_manager_email, Role.PAYROLL_MANAGER)
    headers = auth_headers(tokens["access_token"])

    membership_id = get_membership_id(org_id, payroll_manager_account_id)
    denied = client.get(f"/api/v1/memberships/{membership_id}/permissions", headers=headers)
    assert denied.status_code == 403


def test_list_memberships_scopes_to_the_caller_org() -> None:
    org_a = create_org()
    org_b = create_org()
    headers_a = _admin_headers(org_a, email="perm-admin5@example.com")
    create_account_with_membership(org_a, Role.EMPLOYEE, email="perm-listed@example.com")
    create_account_with_membership(org_b, Role.EMPLOYEE, email="perm-other-org@example.com")

    response = client.get("/api/v1/memberships", headers=headers_a)
    assert response.status_code == 200, response.text
    emails = [row["email"] for row in response.json()]
    assert "perm-listed@example.com" in emails
    assert "perm-admin5@example.com" in emails
    assert "perm-other-org@example.com" not in emails


def test_admin_cannot_reach_a_membership_in_another_org() -> None:
    org_a = create_org()
    org_b = create_org()
    headers_a = _admin_headers(org_a, email="perm-admin4@example.com")

    other_account_id = create_account_with_membership(
        org_b, Role.EMPLOYEE, email="perm-employee-b@example.com"
    )
    other_membership_id = get_membership_id(org_b, other_account_id)

    denied = client.get(f"/api/v1/memberships/{other_membership_id}/permissions", headers=headers_a)
    assert denied.status_code == 404
