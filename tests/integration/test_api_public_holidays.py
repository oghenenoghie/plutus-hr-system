from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _headers(org_id, role: Role, email: str) -> dict[str, str]:
    account_id = create_account_with_membership(org_id, role, email=email)
    tokens = (
        login_with_mfa(account_id, email, role)
        if role in (Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)
        else login(email)
    )
    return auth_headers(tokens["access_token"])


def test_hr_manager_can_create_and_list_public_holidays() -> None:
    org_id = create_org()
    headers = _headers(org_id, Role.HR_MANAGER, "holiday-hr@example.com")

    created = client.post(
        "/api/v1/public-holidays",
        headers=headers,
        json={"holiday_date": "2026-10-01", "name": "Independence Day"},
    )
    assert created.status_code == 201, created.text

    listing = client.get("/api/v1/public-holidays", headers=headers)
    assert listing.status_code == 200, listing.text
    assert [holiday["name"] for holiday in listing.json()] == ["Independence Day"]


def test_manager_department_manager_and_auditor_can_read_but_not_manage() -> None:
    org_id = create_org()
    creator_headers = _headers(org_id, Role.ADMIN, "holiday-admin@example.com")
    client.post(
        "/api/v1/public-holidays",
        headers=creator_headers,
        json={"holiday_date": "2026-05-01", "name": "Workers' Day"},
    )

    for role, email in (
        (Role.MANAGER, "holiday-manager@example.com"),
        (Role.DEPARTMENT_MANAGER, "holiday-dept-manager@example.com"),
        (Role.AUDITOR, "holiday-auditor@example.com"),
    ):
        headers = _headers(org_id, role, email)

        listing = client.get("/api/v1/public-holidays", headers=headers)
        assert listing.status_code == 200, listing.text
        assert [holiday["name"] for holiday in listing.json()] == ["Workers' Day"]

        denied_create = client.post(
            "/api/v1/public-holidays",
            headers=headers,
            json={"holiday_date": "2026-06-12", "name": "Should not be created"},
        )
        assert denied_create.status_code == 403, denied_create.text


def test_employee_cannot_read_public_holidays() -> None:
    org_id = create_org()
    headers = _headers(org_id, Role.EMPLOYEE, "holiday-employee@example.com")

    response = client.get("/api/v1/public-holidays", headers=headers)
    assert response.status_code == 403, response.text
