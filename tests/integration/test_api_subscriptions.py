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


def _admin_headers(org_id, email: str = "sub-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_new_org_defaults_to_the_free_plan() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    subscription = client.get("/api/v1/subscription", headers=headers)
    assert subscription.status_code == 200, subscription.text
    assert subscription.json()["plan_code"] == "free"
    assert subscription.json()["status"] == "active"


def test_usage_summary_counts_employees_against_the_plan_limit() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="sub-admin2@example.com")
    for i in range(6):
        create_employee(org_id, employee_number=f"EMP-500{i}")

    usage = client.get("/api/v1/subscription/usage", headers=headers)
    assert usage.status_code == 200, usage.text
    body = usage.json()
    assert body["plan_code"] == "free"
    assert body["employee_count"] == 6
    assert body["employee_limit"] == 5
    assert body["over_limit"] is True


def test_change_plan_updates_the_usage_limit() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="sub-admin3@example.com")
    for i in range(6):
        create_employee(org_id, employee_number=f"EMP-600{i}")

    changed = client.post(
        "/api/v1/subscription/change-plan", headers=headers, json={"plan_code": "starter"}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["plan_code"] == "starter"

    usage = client.get("/api/v1/subscription/usage", headers=headers)
    assert usage.json()["over_limit"] is False


def test_cancel_subscription_then_cannot_change_plan_or_cancel_again() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="sub-admin4@example.com")

    canceled = client.post("/api/v1/subscription/cancel", headers=headers)
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"

    again = client.post("/api/v1/subscription/cancel", headers=headers)
    assert again.status_code == 400

    change_after_cancel = client.post(
        "/api/v1/subscription/change-plan", headers=headers, json={"plan_code": "starter"}
    )
    assert change_after_cancel.status_code == 400


def test_non_admin_cannot_manage_subscription() -> None:
    org_id = create_org()
    email = "sub-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    headers = auth_headers(login(email)["access_token"])
    denied = client.get("/api/v1/subscription", headers=headers)
    assert denied.status_code == 403
