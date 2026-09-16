from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
)


def _headers(org_id, email: str, role: Role = Role.EMPLOYEE) -> dict[str, str]:
    create_account_with_membership(org_id, role, email=email)
    tokens = login(email)
    return auth_headers(tokens["access_token"])


def test_create_task_defaults_to_assigning_the_caller() -> None:
    org_id = create_org()
    headers = _headers(org_id, email="task-owner@example.com")

    response = client.post("/api/v1/tasks", headers=headers, json={"title": "Follow up on filing"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Follow up on filing"
    assert body["status"] == "todo"
    assert body["priority"] == "medium"
    assert body["assigned_to_account_id"] == body["created_by_account_id"]


def test_create_task_assigned_to_another_org_member() -> None:
    org_id = create_org()
    creator_headers = _headers(org_id, email="task-creator@example.com")
    assignee_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="task-assignee@example.com"
    )

    response = client.post(
        "/api/v1/tasks",
        headers=creator_headers,
        json={"title": "Submit timesheet", "assigned_to_account_id": str(assignee_id)},
    )
    assert response.status_code == 201, response.text
    assert response.json()["assigned_to_account_id"] == str(assignee_id)
    assert response.json()["assigned_to_email"] == "task-assignee@example.com"


def test_create_task_rejects_assignee_outside_the_org() -> None:
    org_id = create_org()
    other_org_id = create_org()
    headers = _headers(org_id, email="task-creator2@example.com")
    outsider_id = create_account_with_membership(
        other_org_id, Role.EMPLOYEE, email="task-outsider@example.com"
    )

    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Should fail", "assigned_to_account_id": str(outsider_id)},
    )
    assert response.status_code == 400, response.text


def test_list_tasks_mine_scope_excludes_others_tasks() -> None:
    org_id = create_org()
    mine_headers = _headers(org_id, email="mine@example.com")
    other_headers = _headers(org_id, email="other@example.com")

    client.post("/api/v1/tasks", headers=mine_headers, json={"title": "Mine"})
    client.post("/api/v1/tasks", headers=other_headers, json={"title": "Not mine"})

    response = client.get("/api/v1/tasks", headers=mine_headers)
    assert response.status_code == 200, response.text
    titles = [task["title"] for task in response.json()]
    assert titles == ["Mine"]

    all_response = client.get("/api/v1/tasks?scope=all", headers=mine_headers)
    assert all_response.status_code == 200, all_response.text
    all_titles = {task["title"] for task in all_response.json()}
    assert {"Mine", "Not mine"} <= all_titles


def test_update_task_status_sets_and_clears_completed_at() -> None:
    org_id = create_org()
    headers = _headers(org_id, email="status-owner@example.com")
    created = client.post("/api/v1/tasks", headers=headers, json={"title": "Do the thing"})
    task_id = created.json()["id"]

    done = client.patch(f"/api/v1/tasks/{task_id}", headers=headers, json={"status": "done"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["completed_at"] is not None

    reopened = client.patch(f"/api/v1/tasks/{task_id}", headers=headers, json={"status": "todo"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["completed_at"] is None


def test_only_assignee_or_creator_can_update_a_task() -> None:
    org_id = create_org()
    creator_headers = _headers(org_id, email="creator3@example.com")
    bystander_headers = _headers(org_id, email="bystander@example.com")
    created = client.post("/api/v1/tasks", headers=creator_headers, json={"title": "Private"})
    task_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/tasks/{task_id}", headers=bystander_headers, json={"status": "done"}
    )
    assert response.status_code == 403, response.text


def test_only_the_creator_can_delete_a_task() -> None:
    org_id = create_org()
    creator_headers = _headers(org_id, email="creator4@example.com")
    assignee_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="assignee4@example.com"
    )
    assignee_headers = auth_headers(login("assignee4@example.com")["access_token"])
    created = client.post(
        "/api/v1/tasks",
        headers=creator_headers,
        json={"title": "Assigned out", "assigned_to_account_id": str(assignee_id)},
    )
    task_id = created.json()["id"]

    denied = client.delete(f"/api/v1/tasks/{task_id}", headers=assignee_headers)
    assert denied.status_code == 403, denied.text

    allowed = client.delete(f"/api/v1/tasks/{task_id}", headers=creator_headers)
    assert allowed.status_code == 204, allowed.text
