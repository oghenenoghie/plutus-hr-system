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


def _admin_headers(org_id, email: str = "audit-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def test_employee_creation_is_audited_and_listable() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "employee_number": "EMP-AUDIT-1",
            "full_name": "Audited Employee",
            "state_of_residence": "Lagos",
            "employment_type": "permanent",
            "date_of_joining": "2025-01-01",
            "basic_minor": 30000000,
            "housing_minor": 15000000,
            "transport_minor": 5000000,
        },
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]

    log = client.get(
        "/api/v1/audit-log",
        headers=headers,
        params={"entity_type": "employee", "entity_id": employee_id},
    )
    assert log.status_code == 200, log.text
    entries = log.json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "employee.create"
    assert entry["entity_type"] == "employee"
    assert entry["entity_id"] == employee_id
    assert entry["role"] == "payroll_manager"
    assert entry["event_metadata"]["employee_number"] == "EMP-AUDIT-1"


def test_leave_approval_by_manager_is_audited_with_actor_identity() -> None:
    org_id = create_org()
    manager_email = "audit-manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-AUD")

    report_email = "audit-report@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    create_employee(
        org_id, account_id=report_account_id, employee_number="EMP-AUD", manager_id=manager_id
    )

    report_headers = auth_headers(login(report_email)["access_token"])
    submit = client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-02-01",
            "end_date": "2026-02-02",
            "days": 2,
        },
    )
    assert submit.status_code == 201, submit.text
    request_id = submit.json()["id"]

    manager_headers = auth_headers(login(manager_email)["access_token"])
    approve = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=manager_headers)
    assert approve.status_code == 200

    admin_headers = _admin_headers(org_id, email="audit-admin2@example.com")
    log = client.get(
        "/api/v1/audit-log",
        headers=admin_headers,
        params={"entity_type": "leave_request", "entity_id": request_id},
    )
    assert log.status_code == 200
    actions = {entry["action"]: entry for entry in log.json()}
    assert set(actions) == {"leave_request.submit", "leave_request.approve"}
    assert actions["leave_request.submit"]["account_id"] == str(report_account_id)
    assert actions["leave_request.approve"]["account_id"] == str(manager_account_id)
    assert actions["leave_request.approve"]["role"] == "manager"


def test_employee_role_cannot_view_audit_log() -> None:
    org_id = create_org()
    email = "not-privileged@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id)
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/audit-log", headers=headers)
    assert response.status_code == 403


def test_response_carries_a_request_id_header() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_login_is_rate_limited_after_ten_attempts_per_minute() -> None:
    org_id = create_org()
    email = "rate-limited@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)

    statuses = [
        client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": "wrong-password"}
        ).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
