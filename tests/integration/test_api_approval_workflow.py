import uuid

from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "workflow-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_two_step_workflow_requires_manager_then_admin_approval() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id)

    template = client.post(
        "/api/v1/approval-workflows/templates",
        headers=admin_headers,
        json={
            "entity_type": "expense",
            "name": "Expense sign-off",
            "approver_roles": ["manager", "admin"],
        },
    )
    assert template.status_code == 201, template.text

    manager_email = "workflow-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])

    entity_id = str(uuid.uuid4())
    request = client.post(
        "/api/v1/approval-workflows/requests",
        headers=admin_headers,
        json={"entity_type": "expense", "entity_id": entity_id},
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]
    assert request.json()["current_step"] == 1
    assert request.json()["status"] == "pending"

    # Admin cannot decide step 1 — it belongs to a manager.
    wrong_role = client.post(
        f"/api/v1/approval-workflows/requests/{request_id}/decide",
        headers=admin_headers,
        json={"decision": "approved"},
    )
    assert wrong_role.status_code == 403

    step_one = client.post(
        f"/api/v1/approval-workflows/requests/{request_id}/decide",
        headers=manager_headers,
        json={"decision": "approved", "comments": "looks fine"},
    )
    assert step_one.status_code == 200
    assert step_one.json()["current_step"] == 2
    assert step_one.json()["status"] == "pending"

    step_two = client.post(
        f"/api/v1/approval-workflows/requests/{request_id}/decide",
        headers=admin_headers,
        json={"decision": "approved"},
    )
    assert step_two.status_code == 200
    assert step_two.json()["status"] == "approved"

    decisions = client.get(
        f"/api/v1/approval-workflows/requests/{request_id}/decisions", headers=admin_headers
    )
    assert decisions.status_code == 200
    assert [d["decision"] for d in decisions.json()] == ["approved", "approved"]

    # Terminal — no further decisions allowed.
    already_done = client.post(
        f"/api/v1/approval-workflows/requests/{request_id}/decide",
        headers=admin_headers,
        json={"decision": "approved"},
    )
    assert already_done.status_code == 400


def test_rejection_at_first_step_ends_the_chain() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="workflow-admin2@example.com")

    client.post(
        "/api/v1/approval-workflows/templates",
        headers=admin_headers,
        json={"entity_type": "bill", "name": "Bill sign-off", "approver_roles": ["admin"]},
    )

    entity_id = str(uuid.uuid4())
    request_id = client.post(
        "/api/v1/approval-workflows/requests",
        headers=admin_headers,
        json={"entity_type": "bill", "entity_id": entity_id},
    ).json()["id"]

    rejected = client.post(
        f"/api/v1/approval-workflows/requests/{request_id}/decide",
        headers=admin_headers,
        json={"decision": "rejected", "comments": "missing receipts"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_cannot_have_two_active_templates_for_same_entity_type() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="workflow-admin3@example.com")

    first = client.post(
        "/api/v1/approval-workflows/templates",
        headers=admin_headers,
        json={"entity_type": "loan", "name": "Loan sign-off v1", "approver_roles": ["admin"]},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/approval-workflows/templates",
        headers=admin_headers,
        json={"entity_type": "loan", "name": "Loan sign-off v2", "approver_roles": ["admin"]},
    )
    assert second.status_code == 400

    deactivated = client.patch(
        f"/api/v1/approval-workflows/templates/{first.json()['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200

    now_allowed = client.post(
        "/api/v1/approval-workflows/templates",
        headers=admin_headers,
        json={"entity_type": "loan", "name": "Loan sign-off v2", "approver_roles": ["admin"]},
    )
    assert now_allowed.status_code == 201


def test_non_admin_cannot_manage_templates() -> None:
    org_id = create_org()
    email = "workflow-manager2@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    headers = auth_headers(login(email)["access_token"])

    denied = client.post(
        "/api/v1/approval-workflows/templates",
        headers=headers,
        json={"entity_type": "expense", "name": "X", "approver_roles": ["admin"]},
    )
    assert denied.status_code == 403
