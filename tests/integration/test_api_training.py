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


def _admin_headers(org_id, email: str = "training-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_training_courses() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/training-courses",
        headers=headers,
        json={
            "title": "Payroll Compliance 101",
            "description": "Nigeria PAYE/pension fundamentals.",
            "provider": "Internal L&D",
            "duration_hours": 4,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Payroll Compliance 101"

    listed = client.get("/api/v1/training-courses", headers=headers)
    assert listed.status_code == 200
    assert [c["title"] for c in listed.json()] == ["Payroll Compliance 101"]


def test_duplicate_course_title_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="training-admin2@example.com")

    first = client.post(
        "/api/v1/training-courses", headers=headers, json={"title": "Data Protection Basics"}
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/api/v1/training-courses", headers=headers, json={"title": "Data Protection Basics"}
    )
    assert duplicate.status_code == 400


def test_enroll_employee_and_track_completion() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="training-admin3@example.com")

    employee_email = "trainee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-600")

    course_id = client.post(
        "/api/v1/training-courses", headers=headers, json={"title": "Workplace Safety"}
    ).json()["id"]

    enrolled = client.post(
        f"/api/v1/training-courses/{course_id}/enrollments",
        headers=headers,
        json={"employee_id": str(employee_id), "enrolled_date": "2026-09-01"},
    )
    assert enrolled.status_code == 201, enrolled.text
    enrollment_id = enrolled.json()["id"]
    assert enrolled.json()["status"] == "enrolled"

    listed = client.get(f"/api/v1/training-courses/{course_id}/enrollments", headers=headers)
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [enrollment_id]

    completed = client.patch(
        f"/api/v1/training-enrollments/{enrollment_id}",
        headers=headers,
        json={"status": "completed", "completed_date": "2026-09-10", "score": 92},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["score"] == 92

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/training-enrollments/me", headers=employee_headers)
    assert mine.status_code == 200
    assert [e["id"] for e in mine.json()] == [enrollment_id]


def test_enrollment_cannot_be_created_for_missing_course() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="training-admin4@example.com")

    response = client.post(
        "/api/v1/training-courses/00000000-0000-0000-0000-000000000000/enrollments",
        headers=headers,
        json={
            "employee_id": "00000000-0000-0000-0000-000000000000",
            "enrolled_date": "2026-09-01",
        },
    )
    assert response.status_code == 404


def test_employee_can_view_course_catalogue_but_not_manage_it() -> None:
    org_id = create_org()
    email = "training-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-601")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/training-courses", headers=headers)
    assert listed.status_code == 200

    denied = client.post(
        "/api/v1/training-courses", headers=headers, json={"title": "Should Not Work"}
    )
    assert denied.status_code == 403


def test_manager_can_view_but_not_manage_courses_or_enrollments() -> None:
    org_id = create_org()
    email = "training-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-602")
    headers = auth_headers(login(email)["access_token"])

    admin_headers = _admin_headers(org_id, email="training-admin5@example.com")
    course_id = client.post(
        "/api/v1/training-courses", headers=admin_headers, json={"title": "Leadership Basics"}
    ).json()["id"]

    listed = client.get("/api/v1/training-courses", headers=headers)
    assert listed.status_code == 200

    enrollments_listed = client.get(
        f"/api/v1/training-courses/{course_id}/enrollments", headers=headers
    )
    assert enrollments_listed.status_code == 200

    denied_create = client.post(
        "/api/v1/training-courses", headers=headers, json={"title": "Should Not Work"}
    )
    assert denied_create.status_code == 403

    denied_enroll = client.post(
        f"/api/v1/training-courses/{course_id}/enrollments",
        headers=headers,
        json={"employee_id": "00000000-0000-0000-0000-000000000000", "enrolled_date": "2026-09-01"},
    )
    assert denied_enroll.status_code == 403
