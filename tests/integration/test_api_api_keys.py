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


def _admin_headers(org_id, email: str = "keys-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_key_returns_plaintext_once_and_list_never_shows_it() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post("/api/v1/api-keys", headers=headers, json={"name": "Zapier"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["key"].startswith("plk_")
    assert body["key_prefix"] == body["key"][:12]
    assert body["revoked_at"] is None

    listed = client.get("/api/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "key" not in listed.json()[0]
    assert listed.json()[0]["key_prefix"] == body["key_prefix"]


def test_revoke_key_then_cannot_revoke_again() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="keys-admin2@example.com")

    key_id = client.post(
        "/api/v1/api-keys", headers=headers, json={"name": "Internal tool"}
    ).json()["id"]

    revoked = client.post(f"/api/v1/api-keys/{key_id}/revoke", headers=headers)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None

    already_revoked = client.post(f"/api/v1/api-keys/{key_id}/revoke", headers=headers)
    assert already_revoked.status_code == 400


def test_payroll_manager_and_employee_cannot_manage_api_keys() -> None:
    org_id = create_org()

    payroll_email = "keys-payroll@example.com"
    payroll_account_id = create_account_with_membership(
        org_id, Role.PAYROLL_MANAGER, email=payroll_email
    )
    payroll_tokens = login_with_mfa(payroll_account_id, payroll_email, Role.PAYROLL_MANAGER)
    payroll_headers = auth_headers(payroll_tokens["access_token"])

    denied_payroll = client.post(
        "/api/v1/api-keys", headers=payroll_headers, json={"name": "Should not work"}
    )
    assert denied_payroll.status_code == 403

    employee_email = "keys-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-960")
    employee_headers = auth_headers(login(employee_email)["access_token"])

    denied_employee = client.get("/api/v1/api-keys", headers=employee_headers)
    assert denied_employee.status_code == 403
