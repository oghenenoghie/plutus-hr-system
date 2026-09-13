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


def _admin_headers(org_id, email: str = "payrollreport-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_payroll_register_lists_every_payslip_in_the_run() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_id = create_employee(org_id, employee_number="EMP-2000")

    run = create_and_lock_pay_run(headers, employee_ids=[employee_id])

    register = client.get(f"/api/v1/reports/payroll-register/{run['id']}", headers=headers)
    assert register.status_code == 200, register.text
    lines = register.json()
    assert len(lines) == 1
    assert lines[0]["employee_id"] == str(employee_id)
    assert lines[0]["employee_number"] == "EMP-2000"
    assert lines[0]["gross_minor"] > 0
    assert lines[0]["net_minor"] > 0


def test_paye_by_state_groups_by_employee_state() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payrollreport-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-2001")

    create_and_lock_pay_run(headers, employee_ids=[employee_id])

    report = client.get("/api/v1/reports/paye-by-state", headers=headers)
    assert report.status_code == 200, report.text
    lines = report.json()
    assert len(lines) == 1
    assert lines[0]["state_of_residence"] == "Lagos"
    assert lines[0]["employee_count"] == 1
    assert lines[0]["total_paye_minor"] >= 0


def test_annual_tax_reconciliation_and_certificate() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payrollreport-admin3@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-2002")

    create_and_lock_pay_run(headers, employee_ids=[employee_id])

    reconciliation = client.get(
        "/api/v1/reports/annual-tax-reconciliation", headers=headers, params={"tax_year": 2026}
    )
    assert reconciliation.status_code == 200, reconciliation.text
    lines = reconciliation.json()
    assert len(lines) == 1
    assert lines[0]["employee_id"] == str(employee_id)
    assert lines[0]["payslip_count"] == 1

    certificate = client.get(
        f"/api/v1/reports/annual-tax-reconciliation/{employee_id}/certificate",
        headers=headers,
        params={"tax_year": 2026},
    )
    assert certificate.status_code == 200, certificate.text
    assert certificate.headers["content-type"] == "application/pdf"
    assert certificate.content.startswith(b"%PDF")

    missing_year = client.get(
        f"/api/v1/reports/annual-tax-reconciliation/{employee_id}/certificate",
        headers=headers,
        params={"tax_year": 1999},
    )
    assert missing_year.status_code == 404


def test_non_admin_cannot_view_payroll_reports() -> None:
    org_id = create_org()
    email = "payrollreport-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    headers = auth_headers(login(email)["access_token"])
    denied = client.get("/api/v1/reports/paye-by-state", headers=headers)
    assert denied.status_code == 403
