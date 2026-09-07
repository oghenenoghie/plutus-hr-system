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


def _admin_headers(org_id, email: str = "policy-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_policies() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/policies",
        headers=headers,
        json={
            "title": "Leave Policy",
            "body": "All employees get 20 days annual leave.",
            "category": "HR",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Leave Policy"
    assert body["category"] == "HR"

    listed = client.get("/api/v1/policies", headers=headers)
    assert listed.status_code == 200
    assert [p["title"] for p in listed.json()] == ["Leave Policy"]


def test_duplicate_policy_title_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="policy-admin2@example.com")

    first = client.post(
        "/api/v1/policies",
        headers=headers,
        json={"title": "Code of Conduct", "body": "Be professional."},
    )
    assert first.status_code == 201

    dupe = client.post(
        "/api/v1/policies",
        headers=headers,
        json={"title": "Code of Conduct", "body": "Different body."},
    )
    assert dupe.status_code in (400, 409, 500)


def test_update_policy() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="policy-admin3@example.com")

    created = client.post(
        "/api/v1/policies",
        headers=headers,
        json={"title": "Expense Policy", "body": "Original text."},
    )
    assert created.status_code == 201, created.text

    policy_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/policies/{policy_id}",
        headers=headers,
        json={"body": "Updated text.", "effective_date": "2026-01-01"},
    )
    assert updated.status_code == 200
    assert updated.json()["body"] == "Updated text."
    assert updated.json()["effective_date"] == "2026-01-01"
    assert updated.json()["title"] == "Expense Policy"


def test_manager_can_view_but_not_manage_policies() -> None:
    org_id = create_org()
    email = "policy-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-300")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/policies", headers=headers)
    assert listed.status_code == 200

    denied = client.post(
        "/api/v1/policies", headers=headers, json={"title": "Should Not Work", "body": "x"}
    )
    assert denied.status_code == 403


def test_employee_can_view_but_not_manage_policies() -> None:
    org_id = create_org()
    email = "policy-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-400")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/policies", headers=headers)
    assert listed.status_code == 200

    denied = client.post(
        "/api/v1/policies", headers=headers, json={"title": "Should Not Work", "body": "x"}
    )
    assert denied.status_code == 403
