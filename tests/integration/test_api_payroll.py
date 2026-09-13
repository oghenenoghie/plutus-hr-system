from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "payroll-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def test_admin_creates_and_runs_a_pay_run_visible_to_admin_and_employee_self_service() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    employee_email = "payee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-500")

    pay_run = create_and_lock_pay_run(headers)
    assert pay_run["status"] == "locked"
    assert pay_run["employee_count"] == 1

    payslips = client.get(f"/api/v1/pay-runs/{pay_run['id']}/payslips", headers=headers)
    assert payslips.status_code == 200
    assert len(payslips.json()) == 1

    employee_tokens = login(employee_email)
    my_payslips = client.get(
        "/api/v1/pay-runs/me/payslips", headers=auth_headers(employee_tokens["access_token"])
    )
    assert my_payslips.status_code == 200
    assert len(my_payslips.json()) == 1
    assert my_payslips.json()[0]["gross_minor"] == payslips.json()[0]["gross_minor"]


def test_pay_run_with_no_active_employees_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin2@example.com")

    response = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    assert response.status_code == 400


def test_employee_cannot_list_pay_runs() -> None:
    org_id = create_org()
    email = "not-admin@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id)
    tokens = login(email)

    response = client.get("/api/v1/pay-runs", headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 403


def test_disbursement_file_reflects_verified_bank_accounts() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin3@example.com")
    create_employee(org_id, employee_number="EMP-600")

    run = create_and_lock_pay_run(headers)

    disbursement = client.get(f"/api/v1/pay-runs/{run['id']}/disbursement", headers=headers)
    assert disbursement.status_code == 200
    body = disbursement.json()
    # No bank account on file for this employee -> skipped, not included.
    assert body["skipped_employee_numbers"] == ["EMP-600"]
    assert body["total_minor"] == 0


def test_payslip_disbursement_outcome_is_recorded_and_history_is_append_only() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin4@example.com")
    create_employee(org_id, employee_number="EMP-700")

    run = create_and_lock_pay_run(headers)
    payslip_id = client.get(f"/api/v1/pay-runs/{run['id']}/payslips", headers=headers).json()[0][
        "id"
    ]

    failed = client.post(
        f"/api/v1/pay-runs/{run['id']}/payslips/{payslip_id}/disbursement-outcome",
        headers=headers,
        json={"status": "failed", "note": "account number rejected by bank"},
    )
    assert failed.status_code == 201, failed.text
    assert failed.json()["status"] == "failed"

    settled = client.post(
        f"/api/v1/pay-runs/{run['id']}/payslips/{payslip_id}/disbursement-outcome",
        headers=headers,
        json={"status": "settled", "reference": "TXN-001"},
    )
    assert settled.status_code == 201, settled.text
    assert settled.json()["reference"] == "TXN-001"

    history = client.get(
        f"/api/v1/pay-runs/{run['id']}/payslips/{payslip_id}/disbursement-outcomes",
        headers=headers,
    )
    assert history.status_code == 200
    entries = history.json()
    # Both attempts are kept — the retry doesn't overwrite the failure.
    assert len(entries) == 2
    assert entries[0]["status"] == "settled"  # newest first
    assert entries[1]["status"] == "failed"
