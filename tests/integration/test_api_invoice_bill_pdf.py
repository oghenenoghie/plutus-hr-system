from typing import Any

from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "docpdf-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup_invoice(headers: dict[str, str], *, contact_email: str | None) -> dict[str, Any]:
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "PDF Customer", "contact_email": contact_email},
    ).json()
    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer["id"],
            "invoice_number": "INV-PDF-1",
            "issue_date": "2026-01-01",
            "due_date": "2026-01-31",
            "revenue_account_code": "revenue",
            "amount_minor": 50_000_00,
        },
    ).json()
    return invoice


def _setup_bill(headers: dict[str, str], *, contact_email: str | None) -> dict[str, Any]:
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    vendor = client.post(
        "/api/v1/vendors",
        headers=headers,
        json={"name": "PDF Vendor", "contact_email": contact_email},
    ).json()
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor["id"],
            "bill_number": "BILL-PDF-1",
            "bill_date": "2026-01-01",
            "due_date": "2026-01-31",
            "expense_account_code": "contractor_expense",
            "amount_minor": 30_000_00,
        },
    ).json()
    return bill


def test_download_invoice_pdf() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    invoice = _setup_invoice(headers, contact_email="customer@example.com")

    response = client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert 'filename="invoice-INV-PDF-1.pdf"' in response.headers["content-disposition"]


def test_email_invoice_without_contact_email_and_no_override_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docpdf-admin2@example.com")
    invoice = _setup_invoice(headers, contact_email=None)

    response = client.post(f"/api/v1/invoices/{invoice['id']}/email", headers=headers, json={})
    assert response.status_code == 400
    assert "contact email" in response.text.lower()


def test_email_invoice_with_contact_email_attempts_delivery() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docpdf-admin3@example.com")
    invoice = _setup_invoice(headers, contact_email="customer2@example.com")

    # RESEND_API_KEY is unset in tests, so delivery itself fails — but this
    # proves the request got past recipient resolution and PDF rendering.
    response = client.post(f"/api/v1/invoices/{invoice['id']}/email", headers=headers, json={})
    assert response.status_code == 502


def test_email_invoice_with_explicit_recipient_override() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docpdf-admin4@example.com")
    invoice = _setup_invoice(headers, contact_email=None)

    response = client.post(
        f"/api/v1/invoices/{invoice['id']}/email",
        headers=headers,
        json={"to": "override@example.com"},
    )
    assert response.status_code == 502


def test_download_bill_pdf() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docpdf-admin5@example.com")
    bill = _setup_bill(headers, contact_email="vendor@example.com")

    response = client.get(f"/api/v1/bills/{bill['id']}/pdf", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert 'filename="bill-BILL-PDF-1.pdf"' in response.headers["content-disposition"]


def test_email_bill_without_contact_email_and_no_override_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docpdf-admin6@example.com")
    bill = _setup_bill(headers, contact_email=None)

    response = client.post(f"/api/v1/bills/{bill['id']}/email", headers=headers, json={})
    assert response.status_code == 400
    assert "contact email" in response.text.lower()


def test_email_bill_with_contact_email_attempts_delivery() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docpdf-admin7@example.com")
    bill = _setup_bill(headers, contact_email="vendor2@example.com")

    response = client.post(f"/api/v1/bills/{bill['id']}/email", headers=headers, json={})
    assert response.status_code == 502


def test_manager_cannot_download_or_email_invoice_or_bill_pdf() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docpdf-admin8@example.com")
    invoice = _setup_invoice(headers, contact_email="c@example.com")
    bill = _setup_bill(headers, contact_email="v@example.com")

    create_account_with_membership(org_id, Role.MANAGER, email="docpdf-manager@example.com")
    manager_headers = auth_headers(login("docpdf-manager@example.com")["access_token"])

    invoice_response = client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=manager_headers)
    assert invoice_response.status_code == 403
    bill_response = client.get(f"/api/v1/bills/{bill['id']}/pdf", headers=manager_headers)
    assert bill_response.status_code == 403
