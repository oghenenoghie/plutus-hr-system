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


def _admin_headers(org_id, email: str = "review-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_admin_can_create_review_and_full_lifecycle_completes() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    employee_email = "reviewee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-500")

    created = client.post(
        "/api/v1/performance-reviews",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "goals": "Ship the new payroll pipeline.",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    review_id = body["id"]

    submitted = client.post(
        f"/api/v1/performance-reviews/{review_id}/submit",
        headers=headers,
        json={"rating": 4, "manager_comments": "Strong first half."},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["rating"] == 4
    assert submitted.json()["submitted_date"] is not None

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/performance-reviews/me", headers=employee_headers)
    assert mine.status_code == 200
    assert [r["id"] for r in mine.json()] == [review_id]

    acknowledged = client.post(
        f"/api/v1/performance-reviews/{review_id}/acknowledge",
        headers=employee_headers,
        json={"employee_comments": "Agreed, thanks for the feedback."},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "acknowledged"
    assert acknowledged.json()["acknowledged_date"] is not None


def test_cannot_submit_twice_or_acknowledge_before_submission() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="review-admin2@example.com")

    employee_email = "reviewee2@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-501")

    review_id = client.post(
        "/api/v1/performance-reviews",
        headers=headers,
        json={
            "employee_id": str(employee_id),
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
        },
    ).json()["id"]

    employee_headers = auth_headers(login(employee_email)["access_token"])
    too_early = client.post(
        f"/api/v1/performance-reviews/{review_id}/acknowledge",
        headers=employee_headers,
        json={},
    )
    assert too_early.status_code == 400

    first_submit = client.post(
        f"/api/v1/performance-reviews/{review_id}/submit", headers=headers, json={"rating": 3}
    )
    assert first_submit.status_code == 200

    second_submit = client.post(
        f"/api/v1/performance-reviews/{review_id}/submit", headers=headers, json={"rating": 5}
    )
    assert second_submit.status_code == 400


def test_manager_can_manage_direct_reports_review_but_not_others() -> None:
    org_id = create_org()
    manager_email = "review-manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-020")

    report_email = "review-report@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    report_id = create_employee(
        org_id, account_id=report_account_id, employee_number="EMP-502", manager_id=manager_id
    )

    outsider_email = "review-outsider@example.com"
    outsider_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=outsider_email
    )
    outsider_id = create_employee(org_id, account_id=outsider_account_id, employee_number="EMP-503")

    manager_headers = auth_headers(login(manager_email)["access_token"])

    for_report = client.post(
        "/api/v1/performance-reviews",
        headers=manager_headers,
        json={
            "employee_id": str(report_id),
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
        },
    )
    assert for_report.status_code == 201, for_report.text

    for_outsider = client.post(
        "/api/v1/performance-reviews",
        headers=manager_headers,
        json={
            "employee_id": str(outsider_id),
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
        },
    )
    assert for_outsider.status_code == 403

    listed = client.get("/api/v1/performance-reviews", headers=manager_headers)
    assert listed.status_code == 200
    assert [r["employee_id"] for r in listed.json()] == [str(report_id)]


def test_employee_role_cannot_create_or_list_reviews() -> None:
    org_id = create_org()
    email = "review-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-504")
    headers = auth_headers(login(email)["access_token"])

    denied_list = client.get("/api/v1/performance-reviews", headers=headers)
    assert denied_list.status_code == 403

    denied_create = client.post(
        "/api/v1/performance-reviews",
        headers=headers,
        json={
            "employee_id": "00000000-0000-0000-0000-000000000000",
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
        },
    )
    assert denied_create.status_code == 403
