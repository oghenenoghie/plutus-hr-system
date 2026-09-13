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


def _admin_headers(org_id, email: str = "probation-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_register_and_confirm_probation() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_id = create_employee(org_id, employee_number="EMP-800")

    created = client.post(
        f"/api/v1/employees/{employee_id}/probation-periods",
        headers=headers,
        json={"start_date": "2026-01-01", "end_date": "2026-04-01"},
    )
    assert created.status_code == 201, created.text
    period_id = created.json()["id"]
    assert created.json()["status"] == "in_progress"

    decided = client.post(
        f"/api/v1/probation-periods/{period_id}/decide",
        headers=headers,
        json={"outcome": "confirmed", "notes": "met all objectives"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "confirmed"
    assert decided.json()["decided_date"] is not None


def test_cannot_have_two_in_progress_probation_periods() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="probation-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-801")

    first = client.post(
        f"/api/v1/employees/{employee_id}/probation-periods",
        headers=headers,
        json={"start_date": "2026-01-01", "end_date": "2026-04-01"},
    )
    assert first.status_code == 201

    second = client.post(
        f"/api/v1/employees/{employee_id}/probation-periods",
        headers=headers,
        json={"start_date": "2026-01-01", "end_date": "2026-04-01"},
    )
    assert second.status_code == 400


def test_extend_then_fail_probation() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="probation-admin3@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-802")

    period_id = client.post(
        f"/api/v1/employees/{employee_id}/probation-periods",
        headers=headers,
        json={"start_date": "2026-01-01", "end_date": "2026-04-01"},
    ).json()["id"]

    extended = client.post(
        f"/api/v1/probation-periods/{period_id}/extend",
        headers=headers,
        json={"new_end_date": "2026-06-01", "notes": "needs more time"},
    )
    assert extended.status_code == 200
    assert extended.json()["end_date"] == "2026-06-01"
    assert extended.json()["status"] == "in_progress"

    failed = client.post(
        f"/api/v1/probation-periods/{period_id}/decide",
        headers=headers,
        json={"outcome": "failed"},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"

    already_decided = client.post(
        f"/api/v1/probation-periods/{period_id}/decide",
        headers=headers,
        json={"outcome": "confirmed"},
    )
    assert already_decided.status_code == 400


def test_manager_cannot_manage_probation_periods() -> None:
    org_id = create_org()
    email = "probation-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-803")
    headers = auth_headers(login(email)["access_token"])

    employee_id = create_employee(org_id, employee_number="EMP-804")

    denied = client.post(
        f"/api/v1/employees/{employee_id}/probation-periods",
        headers=headers,
        json={"start_date": "2026-01-01", "end_date": "2026-04-01"},
    )
    assert denied.status_code == 403
