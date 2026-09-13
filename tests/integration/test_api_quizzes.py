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


def _admin_headers(org_id, email: str = "quiz-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup_course_and_quiz(headers: dict[str, str]) -> tuple[str, str]:
    course_id = client.post(
        "/api/v1/training-courses", headers=headers, json={"title": "Data Privacy 101"}
    ).json()["id"]
    quiz_id = client.post(
        f"/api/v1/training-courses/{course_id}/quizzes",
        headers=headers,
        json={"title": "Final quiz", "passing_score": 70},
    ).json()["id"]
    client.post(
        f"/api/v1/quizzes/{quiz_id}/questions",
        headers=headers,
        json={
            "question_text": "2 + 2 = ?",
            "options": ["3", "4", "5"],
            "correct_option_index": 1,
        },
    )
    client.post(
        f"/api/v1/quizzes/{quiz_id}/questions",
        headers=headers,
        json={
            "question_text": "Capital of Nigeria?",
            "options": ["Lagos", "Abuja"],
            "correct_option_index": 1,
        },
    )
    return course_id, quiz_id


def test_passing_a_quiz_completes_the_enrollment() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    course_id, quiz_id = _setup_course_and_quiz(headers)

    employee_email = "quiz-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-7000"
    )
    client.post(
        f"/api/v1/training-courses/{course_id}/enrollments",
        headers=headers,
        json={"employee_id": str(employee_id), "enrolled_date": "2026-01-01"},
    )

    employee_headers = auth_headers(login(employee_email)["access_token"])

    questions = client.get(
        f"/api/v1/quizzes/{quiz_id}/questions/for-attempt", headers=employee_headers
    )
    assert questions.status_code == 200, questions.text
    assert "correct_option_index" not in questions.json()[0]

    attempt = client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts",
        headers=employee_headers,
        json={"answers": [1, 1]},
    )
    assert attempt.status_code == 201, attempt.text
    assert attempt.json()["score"] == 100
    assert attempt.json()["passed"] is True

    my_enrollments = client.get("/api/v1/training-enrollments/me", headers=employee_headers)
    assert my_enrollments.status_code == 200
    enrollment = my_enrollments.json()[0]
    assert enrollment["status"] == "completed"
    assert enrollment["score"] == 100


def test_failing_a_quiz_does_not_complete_the_enrollment() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="quiz-admin2@example.com")
    course_id, quiz_id = _setup_course_and_quiz(headers)

    employee_email = "quiz-employee2@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-7001"
    )
    client.post(
        f"/api/v1/training-courses/{course_id}/enrollments",
        headers=headers,
        json={"employee_id": str(employee_id), "enrolled_date": "2026-01-01"},
    )
    employee_headers = auth_headers(login(employee_email)["access_token"])

    attempt = client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts",
        headers=employee_headers,
        json={"answers": [0, 0]},
    )
    assert attempt.status_code == 201, attempt.text
    assert attempt.json()["score"] == 0
    assert attempt.json()["passed"] is False

    my_enrollments = client.get("/api/v1/training-enrollments/me", headers=employee_headers)
    assert my_enrollments.json()[0]["status"] == "enrolled"


def test_cannot_attempt_a_quiz_without_enrollment() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="quiz-admin3@example.com")
    _course_id, quiz_id = _setup_course_and_quiz(headers)

    employee_email = "quiz-employee3@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-7002")
    employee_headers = auth_headers(login(employee_email)["access_token"])

    denied = client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts",
        headers=employee_headers,
        json={"answers": [1, 1]},
    )
    assert denied.status_code == 400


def test_course_attachments_are_visible_to_employees_but_only_admin_manages() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="quiz-admin4@example.com")
    course_id = client.post(
        "/api/v1/training-courses", headers=headers, json={"title": "Onboarding Basics"}
    ).json()["id"]

    created = client.post(
        f"/api/v1/training-courses/{course_id}/attachments",
        headers=headers,
        json={"title": "Slides", "storage_url": "https://files.example.com/slides.pdf"},
    )
    assert created.status_code == 201, created.text

    employee_email = "quiz-employee4@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-7003")
    employee_headers = auth_headers(login(employee_email)["access_token"])

    listed = client.get(
        f"/api/v1/training-courses/{course_id}/attachments", headers=employee_headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    denied = client.post(
        f"/api/v1/training-courses/{course_id}/attachments",
        headers=employee_headers,
        json={"title": "Malicious", "storage_url": "https://evil.example.com/x"},
    )
    assert denied.status_code == 403
