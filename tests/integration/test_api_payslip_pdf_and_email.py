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


def _admin_headers(org_id, email: str = "payslip-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def _run_pay_run(headers: dict[str, str]) -> dict:
    return create_and_lock_pay_run(headers)


def test_admin_can_download_payslip_pdf() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    create_employee(org_id, employee_number="EMP-PDF-1", email="pdf1@example.com")

    pay_run = _run_pay_run(headers)
    payslip = client.get(f"/api/v1/pay-runs/{pay_run['id']}/payslips", headers=headers).json()[0]

    response = client.get(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips/{payslip['id']}/pdf", headers=headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_employee_can_download_own_payslip_pdf_but_not_someone_elses() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payslip-admin2@example.com")

    email = "pdf-self@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(
        org_id, account_id=account_id, employee_number="EMP-PDF-2", email="pdf2@example.com"
    )

    other_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="pdf-other@example.com"
    )
    create_employee(
        org_id,
        account_id=other_account_id,
        employee_number="EMP-PDF-3",
        email="pdf3@example.com",
    )

    pay_run = _run_pay_run(headers)
    payslips = client.get(f"/api/v1/pay-runs/{pay_run['id']}/payslips", headers=headers).json()
    my_payslip_id = next(
        p["id"]
        for p in payslips
        if p["employee_id"]
        == client.get(
            "/api/v1/employees/me", headers=auth_headers(login(email)["access_token"])
        ).json()["id"]
    )
    other_payslip_id = next(p["id"] for p in payslips if p["id"] != my_payslip_id)

    employee_headers = auth_headers(login(email)["access_token"])
    mine = client.get(f"/api/v1/pay-runs/me/payslips/{my_payslip_id}/pdf", headers=employee_headers)
    assert mine.status_code == 200
    assert mine.content.startswith(b"%PDF")

    not_mine = client.get(
        f"/api/v1/pay-runs/me/payslips/{other_payslip_id}/pdf", headers=employee_headers
    )
    assert not_mine.status_code == 404


def test_pay_run_creation_records_failed_delivery_when_email_not_configured() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payslip-admin3@example.com")
    create_employee(org_id, employee_number="EMP-PDF-4", email="configured@example.com")

    pay_run = _run_pay_run(headers)
    payslip = client.get(f"/api/v1/pay-runs/{pay_run['id']}/payslips", headers=headers).json()[0]

    deliveries = client.get(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips/{payslip['id']}/deliveries", headers=headers
    )
    assert deliveries.status_code == 200
    entries = deliveries.json()
    assert len(entries) == 1
    assert entries[0]["status"] == "failed"
    assert "not configured" in entries[0]["error"]
    assert entries[0]["recipient_email"] == "configured@example.com"


def test_pay_run_creation_records_failed_delivery_when_employee_has_no_email() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payslip-admin4@example.com")
    create_employee(org_id, employee_number="EMP-PDF-5")  # no email

    pay_run = _run_pay_run(headers)
    payslip = client.get(f"/api/v1/pay-runs/{pay_run['id']}/payslips", headers=headers).json()[0]

    deliveries = client.get(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips/{payslip['id']}/deliveries", headers=headers
    )
    entries = deliveries.json()
    assert len(entries) == 1
    assert entries[0]["status"] == "failed"
    assert entries[0]["error"] == "employee has no email on file"


def test_resend_payslip_email_succeeds_with_mocked_provider(monkeypatch) -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="payslip-admin5@example.com")
    create_employee(org_id, employee_number="EMP-PDF-6", email="resend@example.com")

    pay_run = _run_pay_run(headers)
    payslip = client.get(f"/api/v1/pay-runs/{pay_run['id']}/payslips", headers=headers).json()[0]

    def _fake_send(**kwargs) -> str:
        return "msg_test_123"

    monkeypatch.setattr("app.services.payslip_delivery.send_email_with_attachment", _fake_send)

    resend = client.post(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips/{payslip['id']}/resend", headers=headers
    )
    assert resend.status_code == 202

    deliveries = client.get(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips/{payslip['id']}/deliveries", headers=headers
    ).json()
    assert len(deliveries) == 2  # the original failed attempt + this resend
    sent = next(d for d in deliveries if d["status"] == "sent")
    assert sent["provider_message_id"] == "msg_test_123"


def test_employee_role_cannot_view_deliveries_or_resend() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="payslip-admin6@example.com")
    create_employee(org_id, employee_number="EMP-PDF-7", email="blocked@example.com")

    pay_run = _run_pay_run(admin_headers)
    payslip = client.get(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips", headers=admin_headers
    ).json()[0]

    email = "not-privileged-payslip@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-PDF-8")
    headers = auth_headers(login(email)["access_token"])

    deliveries = client.get(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips/{payslip['id']}/deliveries", headers=headers
    )
    assert deliveries.status_code == 403

    resend = client.post(
        f"/api/v1/pay-runs/{pay_run['id']}/payslips/{payslip['id']}/resend", headers=headers
    )
    assert resend.status_code == 403
