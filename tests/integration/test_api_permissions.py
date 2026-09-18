from pyotp import TOTP

from app.models import Role
from tests.integration.api_helpers import (
    DEFAULT_PASSWORD,
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    get_membership_id,
    login,
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


def test_admin_creates_a_manager_who_can_log_in_immediately() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin6@example.com")

    created = client.post(
        "/api/v1/memberships",
        headers=headers,
        json={"email": "new-manager@example.com", "password": "s3cret-pass", "role": "manager"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "new-manager@example.com"
    assert body["role"] == "manager"
    assert body["totp_secret"] is None
    assert body["totp_provisioning_uri"] is None

    tokens = login("new-manager@example.com", "s3cret-pass")
    assert "access_token" in tokens


def test_admin_creates_a_new_admin_with_totp_already_enabled() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin7@example.com")

    created = client.post(
        "/api/v1/memberships",
        headers=headers,
        json={"email": "new-admin@example.com", "password": "s3cret-pass", "role": "admin"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["totp_secret"] is not None
    assert body["totp_provisioning_uri"] is not None

    code = TOTP(body["totp_secret"]).now()
    login_response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "new-admin@example.com", "password": "s3cret-pass", "totp_code": code},
    )
    assert login_response.status_code == 200, login_response.text


def test_duplicate_email_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin8@example.com")

    client.post(
        "/api/v1/memberships",
        headers=headers,
        json={"email": "dupe@example.com", "password": "s3cret-pass", "role": "employee"},
    )
    dupe = client.post(
        "/api/v1/memberships",
        headers=headers,
        json={"email": "dupe@example.com", "password": "s3cret-pass", "role": "employee"},
    )
    assert dupe.status_code == 409


def test_admin_promotes_an_employee_to_admin() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin9@example.com")
    employee_email = "promote-me@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    membership_id = get_membership_id(org_id, employee_account_id)

    response = client.put(
        f"/api/v1/memberships/{membership_id}/role",
        headers=headers,
        json={"role": "admin"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "admin"
    assert body["totp_secret"] is not None

    code = TOTP(body["totp_secret"]).now()
    login_response = client.post(
        "/api/v1/auth/login",
        json={"identifier": employee_email, "password": DEFAULT_PASSWORD, "totp_code": code},
    )
    assert login_response.status_code == 200, login_response.text
    claims = client.get(
        "/api/v1/auth/me", headers=auth_headers(login_response.json()["access_token"])
    )
    assert claims.json()["role"] == "admin"


def test_role_change_to_non_mfa_role_does_not_return_a_totp_secret() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin10@example.com")
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="promote-to-manager@example.com"
    )
    membership_id = get_membership_id(org_id, employee_account_id)

    response = client.put(
        f"/api/v1/memberships/{membership_id}/role",
        headers=headers,
        json={"role": "manager"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["totp_secret"] is None


def test_promoting_a_role_that_already_has_totp_does_not_reissue_a_secret() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin11@example.com")
    payroll_manager_email = "pm-to-admin@example.com"
    payroll_manager_account_id = create_account_with_membership(
        org_id, Role.PAYROLL_MANAGER, email=payroll_manager_email
    )
    login_with_mfa(payroll_manager_account_id, payroll_manager_email, Role.PAYROLL_MANAGER)
    membership_id = get_membership_id(org_id, payroll_manager_account_id)

    response = client.put(
        f"/api/v1/memberships/{membership_id}/role",
        headers=headers,
        json={"role": "admin"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"
    assert response.json()["totp_secret"] is None


def test_admin_cannot_change_their_own_role() -> None:
    org_id = create_org()
    account_id = create_account_with_membership(org_id, Role.ADMIN, email="perm-self@example.com")
    tokens = login_with_mfa(account_id, "perm-self@example.com", Role.ADMIN)
    headers = auth_headers(tokens["access_token"])
    membership_id = get_membership_id(org_id, account_id)

    response = client.put(
        f"/api/v1/memberships/{membership_id}/role",
        headers=headers,
        json={"role": "manager"},
    )
    assert response.status_code == 409


def test_changing_to_the_same_role_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="perm-admin12@example.com")
    manager_account_id = create_account_with_membership(
        org_id, Role.MANAGER, email="perm-manager3@example.com"
    )
    membership_id = get_membership_id(org_id, manager_account_id)

    response = client.put(
        f"/api/v1/memberships/{membership_id}/role",
        headers=headers,
        json={"role": "manager"},
    )
    assert response.status_code == 409


def test_only_admin_can_change_a_membership_role() -> None:
    org_id = create_org()
    payroll_manager_email = "perm-pm2@example.com"
    payroll_manager_account_id = create_account_with_membership(
        org_id, Role.PAYROLL_MANAGER, email=payroll_manager_email
    )
    tokens = login_with_mfa(payroll_manager_account_id, payroll_manager_email, Role.PAYROLL_MANAGER)
    headers = auth_headers(tokens["access_token"])
    membership_id = get_membership_id(org_id, payroll_manager_account_id)

    response = client.put(
        f"/api/v1/memberships/{membership_id}/role",
        headers=headers,
        json={"role": "admin"},
    )
    assert response.status_code == 403


def test_non_admin_cannot_create_a_membership() -> None:
    org_id = create_org()
    email = "perm-manager2@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    tokens = login(email)
    headers = auth_headers(tokens["access_token"])

    denied = client.post(
        "/api/v1/memberships",
        headers=headers,
        json={"email": "sneaky@example.com", "password": "s3cret-pass", "role": "employee"},
    )
    assert denied.status_code == 403
