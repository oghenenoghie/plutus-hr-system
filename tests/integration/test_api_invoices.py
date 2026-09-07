from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "invoice-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> tuple[dict[str, str], str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Zenith Retail Ltd"})
    assert customer.status_code == 201, customer.text
    return headers, customer.json()["id"]


def _create_invoice(
    headers: dict[str, str], customer_id: str, invoice_number: str = "INV-2001"
) -> dict:
    response = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": invoice_number,
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "revenue",
            "amount_minor": 800_000_00,
            "description": "September services rendered",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_invoice_lifecycle_draft_to_sent_to_paid_posts_balanced_ledger_entries() -> None:
    headers, customer_id = _setup("invoice-admin1@example.com")
    invoice = _create_invoice(headers, customer_id)
    assert invoice["status"] == "draft"

    sent = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"

    paid = client.post(f"/api/v1/invoices/{invoice['id']}/pay", headers=headers)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"
    assert paid.json()["paid_at"] is not None

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    by_account = {line["account"]: line for line in trial_balance.json()}
    assert by_account["revenue"]["balance_minor"] == -800_000_00
    assert by_account["accounts_receivable"]["balance_minor"] == 0
    assert by_account["cash"]["balance_minor"] == 800_000_00


def test_invoice_cannot_be_paid_before_being_sent() -> None:
    headers, customer_id = _setup("invoice-admin2@example.com")
    invoice = _create_invoice(headers, customer_id)

    response = client.post(f"/api/v1/invoices/{invoice['id']}/pay", headers=headers)
    assert response.status_code == 400
    assert "sent" in response.json()["detail"]


def test_invoice_cannot_be_sent_twice() -> None:
    headers, customer_id = _setup("invoice-admin3@example.com")
    invoice = _create_invoice(headers, customer_id)

    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    second = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    assert second.status_code == 400


def test_sent_invoice_cannot_be_voided_but_draft_invoice_can() -> None:
    headers, customer_id = _setup("invoice-admin4@example.com")
    invoice = _create_invoice(headers, customer_id)

    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    denied = client.post(f"/api/v1/invoices/{invoice['id']}/void", headers=headers)
    assert denied.status_code == 400

    draft_invoice = _create_invoice(headers, customer_id, invoice_number="INV-2002")
    voided = client.post(f"/api/v1/invoices/{draft_invoice['id']}/void", headers=headers)
    assert voided.status_code == 200
    assert voided.json()["status"] == "void"


def test_invoice_rejects_unknown_revenue_account() -> None:
    headers, customer_id = _setup("invoice-admin5@example.com")

    response = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-2003",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "not_a_real_account",
            "amount_minor": 1_000_00,
        },
    )
    assert response.status_code == 400
