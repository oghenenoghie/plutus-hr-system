from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "credit-note-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> tuple[dict[str, str], str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Credit Note Customer"}
    ).json()["id"]
    return headers, customer_id


def _sent_invoice(headers: dict[str, str], customer_id: str) -> dict:
    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "CN-INV-1",
            "issue_date": "2026-01-01",
            "due_date": "2026-01-31",
            "revenue_account_code": "revenue",
            "amount_minor": 500_000_00,
        },
    ).json()
    sent = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    return sent.json()


def test_credit_note_reduces_receivable_and_revenue_on_the_ledger() -> None:
    headers, customer_id = _setup("credit-note-admin1@example.com")
    invoice = _sent_invoice(headers, customer_id)

    created = client.post(
        f"/api/v1/invoices/{invoice['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-1",
            "issue_date": "2026-01-15",
            "amount_minor": 100_000_00,
            "reason": "partial return of goods",
        },
    )
    assert created.status_code == 201, created.text

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    by_account = {line["account"]: line for line in trial_balance.json()}
    assert by_account["accounts_receivable"]["balance_minor"] == 400_000_00
    assert by_account["revenue"]["balance_minor"] == -400_000_00


def test_credit_note_cannot_exceed_remaining_invoice_balance() -> None:
    headers, customer_id = _setup("credit-note-admin2@example.com")
    invoice = _sent_invoice(headers, customer_id)

    first = client.post(
        f"/api/v1/invoices/{invoice['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-2",
            "issue_date": "2026-01-15",
            "amount_minor": 400_000_00,
            "reason": "correction",
        },
    )
    assert first.status_code == 201

    second = client.post(
        f"/api/v1/invoices/{invoice['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-3",
            "issue_date": "2026-01-16",
            "amount_minor": 200_000_00,
            "reason": "too much",
        },
    )
    assert second.status_code == 400
    assert "remaining balance" in second.json()["detail"]


def test_credit_note_cannot_be_issued_against_a_draft_invoice() -> None:
    headers, customer_id = _setup("credit-note-admin3@example.com")
    draft_invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "CN-INV-2",
            "issue_date": "2026-01-01",
            "due_date": "2026-01-31",
            "revenue_account_code": "revenue",
            "amount_minor": 100_000_00,
        },
    ).json()

    denied = client.post(
        f"/api/v1/invoices/{draft_invoice['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-4",
            "issue_date": "2026-01-05",
            "amount_minor": 50_000_00,
            "reason": "n/a",
        },
    )
    assert denied.status_code == 400


def test_fully_credited_invoice_drops_out_of_ar_aging() -> None:
    headers, customer_id = _setup("credit-note-admin4@example.com")
    invoice = _sent_invoice(headers, customer_id)

    client.post(
        f"/api/v1/invoices/{invoice['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-5",
            "issue_date": "2026-01-15",
            "amount_minor": 500_000_00,
            "reason": "full refund",
        },
    )

    report = client.get("/api/v1/reports/ar-aging", headers=headers, params={"as_of": "2026-02-01"})
    assert report.status_code == 200
    assert report.json() == []
