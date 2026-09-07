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


def _admin_headers(org_id, email: str = "grade-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_job_grades() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/job-grades",
        headers=headers,
        json={
            "name": "L1",
            "level": 1,
            "min_salary_minor": 200_000_00,
            "max_salary_minor": 350_000_00,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "L1"
    assert body["level"] == 1
    assert body["min_salary_minor"] == 200_000_00
    assert body["max_salary_minor"] == 350_000_00

    listed = client.get("/api/v1/job-grades", headers=headers)
    assert listed.status_code == 200
    assert [g["name"] for g in listed.json()] == ["L1"]


def test_duplicate_job_grade_name_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="grade-admin2@example.com")

    first = client.post("/api/v1/job-grades", headers=headers, json={"name": "Senior"})
    assert first.status_code == 201

    dupe = client.post("/api/v1/job-grades", headers=headers, json={"name": "Senior"})
    assert dupe.status_code in (400, 409, 500)


def test_update_job_grade() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="grade-admin3@example.com")

    created = client.post("/api/v1/job-grades", headers=headers, json={"name": "L2", "level": 2})
    assert created.status_code == 201, created.text

    job_grade_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/job-grades/{job_grade_id}",
        headers=headers,
        json={"min_salary_minor": 400_000_00, "max_salary_minor": 600_000_00},
    )
    assert updated.status_code == 200
    assert updated.json()["min_salary_minor"] == 400_000_00
    assert updated.json()["max_salary_minor"] == 600_000_00
    assert updated.json()["level"] == 2


def test_employee_can_be_assigned_to_a_job_grade() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="grade-admin4@example.com")

    job_grade = client.post("/api/v1/job-grades", headers=headers, json={"name": "L3"})
    job_grade_id = job_grade.json()["id"]

    employee_id = create_employee(org_id, employee_number="EMP-200")
    updated = client.patch(
        f"/api/v1/employees/{employee_id}",
        headers=headers,
        json={"job_grade_id": job_grade_id},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["job_grade_id"] == job_grade_id


def test_manager_can_view_but_not_manage_job_grades() -> None:
    org_id = create_org()
    email = "grade-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-300")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/job-grades", headers=headers)
    assert listed.status_code == 200

    denied = client.post("/api/v1/job-grades", headers=headers, json={"name": "Should Not Work"})
    assert denied.status_code == 403


def test_employee_role_cannot_view_job_grades() -> None:
    org_id = create_org()
    email = "grade-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-400")
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/job-grades", headers=headers)
    assert response.status_code == 403
