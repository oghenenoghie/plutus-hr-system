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


def _admin_headers(org_id, email: str = "relations-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_admin_can_open_and_resolve_a_case() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    employee_id = create_employee(org_id, employee_number="EMP-700")

    created = client.post(
        "/api/v1/disciplinary-cases",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "category": "attendance",
            "description": "Repeated unexcused lateness this month.",
            "incident_date": "2026-09-01",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "open"
    case_id = body["id"]

    resolved = client.post(
        f"/api/v1/disciplinary-cases/{case_id}/resolve",
        headers=headers,
        json={"action_taken": "written_warning", "resolution_notes": "Issued a written warning."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["action_taken"] == "written_warning"
    assert resolved.json()["resolution_date"] is not None


def test_resolving_with_no_action_dismisses_the_case() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="relations-admin2@example.com")

    employee_id = create_employee(org_id, employee_number="EMP-701")
    case_id = client.post(
        "/api/v1/disciplinary-cases",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "category": "other",
            "description": "Anonymous complaint, unsubstantiated.",
            "incident_date": "2026-09-01",
        },
    ).json()["id"]

    resolved = client.post(
        f"/api/v1/disciplinary-cases/{case_id}/resolve",
        headers=headers,
        json={"action_taken": "none"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "dismissed"


def test_cannot_resolve_an_already_resolved_case() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="relations-admin3@example.com")

    employee_id = create_employee(org_id, employee_number="EMP-702")
    case_id = client.post(
        "/api/v1/disciplinary-cases",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "category": "misconduct",
            "description": "Policy breach.",
            "incident_date": "2026-09-01",
        },
    ).json()["id"]

    first = client.post(
        f"/api/v1/disciplinary-cases/{case_id}/resolve",
        headers=headers,
        json={"action_taken": "verbal_warning"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/disciplinary-cases/{case_id}/resolve",
        headers=headers,
        json={"action_taken": "suspension"},
    )
    assert second.status_code == 400


def test_manager_can_open_and_view_direct_reports_case_but_not_resolve_it() -> None:
    org_id = create_org()
    manager_email = "relations-manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-030")

    report_id = create_employee(org_id, employee_number="EMP-703", manager_id=manager_id)
    outsider_id = create_employee(org_id, employee_number="EMP-704")

    manager_headers = auth_headers(login(manager_email)["access_token"])

    for_report = client.post(
        "/api/v1/disciplinary-cases",
        headers=manager_headers,
        json={
            "employee_id": str(report_id),
            "category": "attendance",
            "description": "Late twice this week.",
            "incident_date": "2026-09-01",
        },
    )
    assert for_report.status_code == 201, for_report.text
    case_id = for_report.json()["id"]

    for_outsider = client.post(
        "/api/v1/disciplinary-cases",
        headers=manager_headers,
        json={
            "employee_id": str(outsider_id),
            "category": "attendance",
            "description": "Should not work.",
            "incident_date": "2026-09-01",
        },
    )
    assert for_outsider.status_code == 403

    listed = client.get("/api/v1/disciplinary-cases", headers=manager_headers)
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [case_id]

    denied_resolve = client.post(
        f"/api/v1/disciplinary-cases/{case_id}/resolve",
        headers=manager_headers,
        json={"action_taken": "verbal_warning"},
    )
    assert denied_resolve.status_code == 403


def test_employee_role_cannot_view_disciplinary_cases() -> None:
    org_id = create_org()
    email = "relations-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-705")
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/disciplinary-cases", headers=headers)
    assert response.status_code == 403
