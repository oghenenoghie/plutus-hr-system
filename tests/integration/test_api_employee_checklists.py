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


def _admin_headers(org_id, email: str = "checklist-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_admin_creates_and_completes_a_checklist_item() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_id = create_employee(org_id, employee_number="EMP-700")

    created = client.post(
        f"/api/v1/employees/{employee_id}/checklist-items",
        headers=headers,
        json={"checklist_type": "onboarding", "title": "Issue laptop"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending"
    assert body["completed_at"] is None
    item_id = body["id"]

    listed = client.get(f"/api/v1/employees/{employee_id}/checklist-items", headers=headers)
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()] == [item_id]

    completed = client.post(
        f"/api/v1/employees/checklist-items/{item_id}/complete", headers=headers
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert completed.json()["completed_at"] is not None


def test_completing_an_already_done_item_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="checklist-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-701")

    item_id = client.post(
        f"/api/v1/employees/{employee_id}/checklist-items",
        headers=headers,
        json={"checklist_type": "offboarding", "title": "Revoke system access"},
    ).json()["id"]

    first = client.post(f"/api/v1/employees/checklist-items/{item_id}/complete", headers=headers)
    assert first.status_code == 200

    second = client.post(f"/api/v1/employees/checklist-items/{item_id}/complete", headers=headers)
    assert second.status_code == 400


def test_employee_cannot_manage_checklist_items() -> None:
    org_id = create_org()
    email = "checklist-worker@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    employee_id = create_employee(org_id, account_id=account_id, employee_number="EMP-702")
    headers = auth_headers(login(email)["access_token"])

    denied_create = client.post(
        f"/api/v1/employees/{employee_id}/checklist-items",
        headers=headers,
        json={"checklist_type": "onboarding", "title": "Sign contract"},
    )
    assert denied_create.status_code == 403

    denied_list = client.get(f"/api/v1/employees/{employee_id}/checklist-items", headers=headers)
    assert denied_list.status_code == 403
