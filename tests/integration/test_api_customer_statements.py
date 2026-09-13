from typing import Any

from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "custstatement-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _create_invoice(
    headers: dict[str, str], customer_id: str, invoice_number: str, issue_date: str
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": invoice_number,
            "issue_date": issue_date,
            "due_date": "2026-12-31",
            "revenue_account_code": "revenue",
            "amount_minor": 80_000_00,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_customer_statement_tracks_running_balance_across_invoice_states() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Statement Customer"}
    ).json()["id"]

    invoice_one = _create_invoice(headers, customer_id, "CSTMT-1", "2026-01-01")
    client.post(f"/api/v1/invoices/{invoice_one['id']}/send", headers=headers)

    invoice_two = _create_invoice(headers, customer_id, "CSTMT-2", "2026-01-05")
    client.post(f"/api/v1/invoices/{invoice_two['id']}/send", headers=headers)
    client.post(f"/api/v1/invoices/{invoice_two['id']}/pay", headers=headers)

    _create_invoice(headers, customer_id, "CSTMT-3", "2026-01-10")  # left in draft

    statement = client.get(f"/api/v1/reports/customers/{customer_id}/statement", headers=headers)
    assert statement.status_code == 200, statement.text
    lines = statement.json()
    assert [line["invoice_number"] for line in lines] == ["CSTMT-1", "CSTMT-2", "CSTMT-3"]

    assert lines[0]["status"] == "sent"
    assert lines[0]["running_balance_minor"] == 80_000_00

    assert lines[1]["status"] == "paid"
    # invoice_two settled, so it drops back out of the running balance.
    assert lines[1]["running_balance_minor"] == 80_000_00

    assert lines[2]["status"] == "draft"
    # never posted, so it never contributes to the balance.
    assert lines[2]["running_balance_minor"] == 80_000_00


def test_customer_statement_nets_out_credit_notes() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="custstatement-admin2@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Credited Customer"}
    ).json()["id"]

    invoice = _create_invoice(headers, customer_id, "CSTMT-CN-1", "2026-01-01")
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    credit_note = client.post(
        f"/api/v1/invoices/{invoice['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-1",
            "issue_date": "2026-01-02",
            "amount_minor": 30_000_00,
            "reason": "Billing correction",
        },
    )
    assert credit_note.status_code == 201, credit_note.text

    statement = client.get(f"/api/v1/reports/customers/{customer_id}/statement", headers=headers)
    assert statement.status_code == 200, statement.text
    lines = statement.json()
    assert lines[0]["running_balance_minor"] == 50_000_00


def test_download_customer_statement_pdf() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="custstatement-admin3@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer_id = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "PDF Statement Customer", "contact_email": "customer@example.com"},
    ).json()["id"]
    invoice = _create_invoice(headers, customer_id, "CSTMT-PDF-1", "2026-01-01")
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)

    response = client.get(f"/api/v1/reports/customers/{customer_id}/statement/pdf", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_email_customer_statement_without_contact_email_and_no_override_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="custstatement-admin4@example.com")
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "No-Email Customer"}
    ).json()["id"]

    response = client.post(
        f"/api/v1/reports/customers/{customer_id}/statement/email", headers=headers, json={}
    )
    assert response.status_code == 400
    assert "contact email" in response.text.lower()


def test_email_customer_statement_with_contact_email_attempts_delivery() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="custstatement-admin5@example.com")
    customer_id = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "Emailable Customer", "contact_email": "customer2@example.com"},
    ).json()["id"]

    response = client.post(
        f"/api/v1/reports/customers/{customer_id}/statement/email", headers=headers, json={}
    )
    assert response.status_code == 502
