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

    response = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    assert response.status_code == 201, response.text
    pay_run = response.json()
    assert pay_run["status"] == "completed"
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


def test_reverse_a_completed_run_balances_the_ledger_and_marks_reversed() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin4@example.com")
    create_employee(org_id, employee_number="EMP-700")

    run = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    assert run.status_code == 201, run.text
    pay_run_id = run.json()["id"]

    reversal = client.post(f"/api/v1/pay-runs/{pay_run_id}/reverse", headers=headers)
    assert reversal.status_code == 200, reversal.text
    assert reversal.json()["status"] == "reversed"
    assert reversal.json()["reversed_at"] is not None

    # Every account this run posted to nets back to zero — a fresh org, one
    # pay run, now fully reversed, should have a flat trial balance.
    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    assert trial_balance.status_code == 200
    for line in trial_balance.json():
        assert line["balance_minor"] == 0, line

    entries = client.get(
        "/api/v1/general-ledger/entries", headers=headers, params={"pay_run_id": pay_run_id}
    )
    assert entries.status_code == 200
    # Original postings plus one flipped compensating posting per original.
    assert len(entries.json()) % 2 == 0
    assert len(entries.json()) > 0


def test_cannot_reverse_a_run_that_is_already_reversed() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin5@example.com")
    create_employee(org_id, employee_number="EMP-701")

    run = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    pay_run_id = run.json()["id"]
    first = client.post(f"/api/v1/pay-runs/{pay_run_id}/reverse", headers=headers)
    assert first.status_code == 200

    second = client.post(f"/api/v1/pay-runs/{pay_run_id}/reverse", headers=headers)
    assert second.status_code == 400


def test_reverse_restores_loan_balance_and_reactivates_a_paid_off_loan() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="payroll-admin6@example.com")
    email = "loan-borrower@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-702")
    employee_headers = auth_headers(login(email)["access_token"])

    # A single-installment loan fully repaid by the very next pay run.
    loan_response = client.post(
        "/api/v1/loans/me",
        headers=employee_headers,
        json={"principal_minor": 10_000_00, "num_installments": 1, "start_date": "2026-01-01"},
    )
    assert loan_response.status_code == 201, loan_response.text
    loan_id = loan_response.json()["id"]

    run = client.post(
        "/api/v1/pay-runs",
        headers=admin_headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    assert run.status_code == 201, run.text
    pay_run_id = run.json()["id"]

    paid_off = client.get(f"/api/v1/loans/{loan_id}", headers=admin_headers)
    assert paid_off.json()["status"] == "paid_off"
    assert paid_off.json()["outstanding_minor"] == 0

    reversal = client.post(f"/api/v1/pay-runs/{pay_run_id}/reverse", headers=admin_headers)
    assert reversal.status_code == 200, reversal.text

    restored = client.get(f"/api/v1/loans/{loan_id}", headers=admin_headers)
    assert restored.json()["status"] == "active"
    assert restored.json()["outstanding_minor"] == 10_000_00


def test_reverse_blocked_by_filed_liability_until_acknowledged() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin7@example.com")
    create_employee(org_id, employee_number="EMP-703")

    run = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    pay_run_id = run.json()["id"]

    liabilities = client.get("/api/v1/statutory-liabilities", headers=headers)
    this_run_liabilities = [
        liability for liability in liabilities.json() if liability["pay_run_id"] == pay_run_id
    ]
    assert this_run_liabilities
    filed = client.post(
        f"/api/v1/statutory-liabilities/{this_run_liabilities[0]['id']}/file", headers=headers
    )
    assert filed.status_code == 200

    blocked = client.post(f"/api/v1/pay-runs/{pay_run_id}/reverse", headers=headers)
    assert blocked.status_code == 400

    acknowledged = client.post(
        f"/api/v1/pay-runs/{pay_run_id}/reverse",
        headers=headers,
        json={"acknowledge_filed_or_remitted": True},
    )
    assert acknowledged.status_code == 200, acknowledged.text

    # The filed liability itself is untouched — reversal can't undo a real
    # filing with a government authority, only acknowledge it happened.
    still_filed = client.get("/api/v1/statutory-liabilities", headers=headers)
    refetched = [
        liability
        for liability in still_filed.json()
        if liability["id"] == this_run_liabilities[0]["id"]
    ]
    assert refetched[0]["status"] == "filed"


def test_non_manage_role_cannot_reverse_pay_run() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin8@example.com")
    create_employee(org_id, employee_number="EMP-704")
    run = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    pay_run_id = run.json()["id"]

    email = "not-payroll@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-705")
    employee_headers = auth_headers(login(email)["access_token"])

    response = client.post(f"/api/v1/pay-runs/{pay_run_id}/reverse", headers=employee_headers)
    assert response.status_code == 403


def test_disbursement_file_reflects_verified_bank_accounts() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payroll-admin3@example.com")
    create_employee(org_id, employee_number="EMP-600")

    run = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-01-01", "period_end": "2026-01-31", "frequency": "monthly"},
    )
    assert run.status_code == 201, run.text

    disbursement = client.get(f"/api/v1/pay-runs/{run.json()['id']}/disbursement", headers=headers)
    assert disbursement.status_code == 200
    body = disbursement.json()
    # No bank account on file for this employee -> skipped, not included.
    assert body["skipped_employee_numbers"] == ["EMP-600"]
    assert body["total_minor"] == 0
