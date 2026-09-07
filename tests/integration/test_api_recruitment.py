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


def _admin_headers(org_id, email: str = "recruit-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_and_list_job_postings() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/job-postings",
        headers=headers,
        json={
            "title": "Backend Engineer",
            "opened_date": "2026-09-01",
            "description": "Build the API.",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Backend Engineer"
    assert body["status"] == "open"
    assert body["closed_date"] is None

    listed = client.get("/api/v1/job-postings", headers=headers)
    assert listed.status_code == 200
    assert [p["title"] for p in listed.json()] == ["Backend Engineer"]


def test_close_job_posting() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="recruit-admin2@example.com")

    created = client.post(
        "/api/v1/job-postings",
        headers=headers,
        json={"title": "Recruiter", "opened_date": "2026-08-01"},
    )
    assert created.status_code == 201, created.text

    job_posting_id = created.json()["id"]
    closed = client.patch(
        f"/api/v1/job-postings/{job_posting_id}",
        headers=headers,
        json={"status": "closed", "closed_date": "2026-09-05"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["closed_date"] == "2026-09-05"


def test_create_and_list_candidates_for_a_posting() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="recruit-admin3@example.com")

    posting = client.post(
        "/api/v1/job-postings",
        headers=headers,
        json={"title": "Payroll Analyst", "opened_date": "2026-09-01"},
    )
    job_posting_id = posting.json()["id"]

    created = client.post(
        f"/api/v1/job-postings/{job_posting_id}/candidates",
        headers=headers,
        json={
            "full_name": "Bisi Adewale",
            "email": "bisi@example.com",
            "applied_date": "2026-09-02",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["full_name"] == "Bisi Adewale"
    assert body["status"] == "applied"
    assert body["job_posting_id"] == job_posting_id

    listed = client.get(f"/api/v1/job-postings/{job_posting_id}/candidates", headers=headers)
    assert listed.status_code == 200
    assert [c["full_name"] for c in listed.json()] == ["Bisi Adewale"]


def test_candidate_cannot_be_created_for_missing_posting() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="recruit-admin4@example.com")

    response = client.post(
        "/api/v1/job-postings/00000000-0000-0000-0000-000000000000/candidates",
        headers=headers,
        json={"full_name": "Ghost Candidate", "applied_date": "2026-09-02"},
    )
    assert response.status_code == 404


def test_update_candidate_status_through_pipeline() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="recruit-admin5@example.com")

    posting = client.post(
        "/api/v1/job-postings",
        headers=headers,
        json={"title": "Support Lead", "opened_date": "2026-09-01"},
    )
    job_posting_id = posting.json()["id"]
    candidate = client.post(
        f"/api/v1/job-postings/{job_posting_id}/candidates",
        headers=headers,
        json={"full_name": "Femi Balogun", "applied_date": "2026-09-02"},
    )
    candidate_id = candidate.json()["id"]

    updated = client.patch(
        f"/api/v1/candidates/{candidate_id}", headers=headers, json={"status": "interviewing"}
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "interviewing"

    got = client.get(f"/api/v1/candidates/{candidate_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["status"] == "interviewing"


def test_manager_can_view_but_not_manage_recruitment() -> None:
    org_id = create_org()
    email = "recruit-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-300")
    headers = auth_headers(login(email)["access_token"])

    listed = client.get("/api/v1/job-postings", headers=headers)
    assert listed.status_code == 200

    denied = client.post(
        "/api/v1/job-postings",
        headers=headers,
        json={"title": "Should Not Work", "opened_date": "2026-09-01"},
    )
    assert denied.status_code == 403


def test_employee_role_cannot_view_recruitment() -> None:
    org_id = create_org()
    email = "recruit-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-400")
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/job-postings", headers=headers)
    assert response.status_code == 403
