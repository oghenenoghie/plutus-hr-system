from pyotp import TOTP

from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def test_signup_creates_org_and_mfa_enabled_admin() -> None:
    response = client.post(
        "/api/v1/organisation/signup",
        json={
            "org_name": "Brand New Co",
            "admin_email": "founder@example.com",
            "admin_password": "s3cret-pass",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "founder@example.com"
    assert body["totp_secret"]
    assert body["totp_provisioning_uri"].startswith("otpauth://")

    code = TOTP(body["totp_secret"]).now()
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": "founder@example.com",
            "password": "s3cret-pass",
            "totp_code": code,
        },
    )
    assert login_response.status_code == 200, login_response.text

    headers = auth_headers(login_response.json()["access_token"])
    org_response = client.get("/api/v1/organisation", headers=headers)
    assert org_response.status_code == 200, org_response.text
    assert org_response.json()["name"] == "Brand New Co"


def test_signup_rejects_a_duplicate_admin_email() -> None:
    client.post(
        "/api/v1/organisation/signup",
        json={
            "org_name": "First Co",
            "admin_email": "dupe-founder@example.com",
            "admin_password": "s3cret-pass",
        },
    )
    response = client.post(
        "/api/v1/organisation/signup",
        json={
            "org_name": "Second Co",
            "admin_email": "dupe-founder@example.com",
            "admin_password": "s3cret-pass",
        },
    )
    assert response.status_code == 409, response.text


def test_signup_rejects_a_short_password() -> None:
    response = client.post(
        "/api/v1/organisation/signup",
        json={
            "org_name": "Short Password Co",
            "admin_email": "short-pw@example.com",
            "admin_password": "short",
        },
    )
    assert response.status_code == 422, response.text


def _admin_headers(org_id, email: str) -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_get_organisation_defaults() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "org-admin1@example.com")

    response = client.get("/api/v1/organisation", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["name"] == "Test Co"
    assert body["default_pay_frequency"] == "monthly"
    assert body["default_pfa"] is None
    assert body["states_of_operation"] == []


def test_update_organisation_registration_and_defaults() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "org-admin2@example.com")

    response = client.put(
        "/api/v1/organisation",
        headers=headers,
        json={
            "rc_number": "RC123456",
            "company_tin": "12345678-0001",
            "default_pay_frequency": "weekly",
            "default_pfa": "ARM Pension Managers",
            "states_of_operation": ["Lagos", "Rivers"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["rc_number"] == "RC123456"
    assert body["company_tin"] == "12345678-0001"
    assert body["default_pay_frequency"] == "weekly"
    assert body["default_pfa"] == "ARM Pension Managers"
    assert body["states_of_operation"] == ["Lagos", "Rivers"]

    refetched = client.get("/api/v1/organisation", headers=headers)
    assert refetched.json() == body


def test_organisation_requires_admin_role() -> None:
    org_id = create_org()
    email = "org-employee@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/organisation", headers=headers)
    assert response.status_code == 403
