from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "recon-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _cash_ledger_entry_id(headers: dict[str, str]) -> str:
    entries = client.get(
        "/api/v1/general-ledger/entries", headers=headers, params={"account": "cash"}
    ).json()
    assert len(entries) == 1
    return str(entries[0]["id"])


def test_matching_a_bill_payment_reconciles_the_withdrawal() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Recon Vendor"}
    ).json()["id"]
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "RECON-1",
            "bill_date": "2026-02-01",
            "due_date": "2026-02-28",
            "expense_account_code": "contractor_expense",
            "amount_minor": 250_000_00,
        },
    ).json()
    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)
    ledger_entry_id = _cash_ledger_entry_id(headers)

    imported = client.post(
        "/api/v1/bank-reconciliation/statement-lines",
        headers=headers,
        json={
            "account_code": "cash",
            "lines": [
                {
                    "transaction_date": "2026-02-05",
                    "description": "Payment to Recon Vendor",
                    "amount_minor": -250_000_00,
                    "external_reference": "TXN-1",
                }
            ],
        },
    )
    assert imported.status_code == 201, imported.text
    line_id = imported.json()[0]["id"]

    status_before = client.get(
        "/api/v1/bank-reconciliation/status", headers=headers, params={"account_code": "cash"}
    )
    assert len(status_before.json()["unmatched_statement_lines"]) == 1
    assert len(status_before.json()["unmatched_ledger_entries"]) == 1

    matched = client.post(
        f"/api/v1/bank-reconciliation/statement-lines/{line_id}/match",
        headers=headers,
        json={"ledger_entry_id": ledger_entry_id},
    )
    assert matched.status_code == 200, matched.text
    assert matched.json()["matched_ledger_entry_id"] == ledger_entry_id

    status_after = client.get(
        "/api/v1/bank-reconciliation/status", headers=headers, params={"account_code": "cash"}
    )
    assert status_after.json()["unmatched_statement_lines"] == []
    assert status_after.json()["unmatched_ledger_entries"] == []


def test_amount_mismatch_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="recon-admin2@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Recon Vendor 2"}
    ).json()["id"]
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "RECON-2",
            "bill_date": "2026-02-01",
            "due_date": "2026-02-28",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
        },
    ).json()
    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)
    ledger_entry_id = _cash_ledger_entry_id(headers)

    line_id = client.post(
        "/api/v1/bank-reconciliation/statement-lines",
        headers=headers,
        json={
            "account_code": "cash",
            "lines": [
                {
                    "transaction_date": "2026-02-05",
                    "description": "Wrong amount",
                    "amount_minor": -999_00,
                }
            ],
        },
    ).json()[0]["id"]

    mismatch = client.post(
        f"/api/v1/bank-reconciliation/statement-lines/{line_id}/match",
        headers=headers,
        json={"ledger_entry_id": ledger_entry_id},
    )
    assert mismatch.status_code == 400
    assert "mismatch" in mismatch.json()["detail"]


def test_unmatch_restores_both_sides_to_unreconciled() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="recon-admin3@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Recon Customer"}
    ).json()["id"]
    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "RECON-INV-1",
            "issue_date": "2026-02-01",
            "due_date": "2026-02-28",
            "revenue_account_code": "revenue",
            "amount_minor": 300_000_00,
        },
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    client.post(f"/api/v1/invoices/{invoice['id']}/pay", headers=headers)
    ledger_entry_id = _cash_ledger_entry_id(headers)

    line_id = client.post(
        "/api/v1/bank-reconciliation/statement-lines",
        headers=headers,
        json={
            "account_code": "cash",
            "lines": [
                {
                    "transaction_date": "2026-02-06",
                    "description": "Deposit from Recon Customer",
                    "amount_minor": 300_000_00,
                }
            ],
        },
    ).json()[0]["id"]

    client.post(
        f"/api/v1/bank-reconciliation/statement-lines/{line_id}/match",
        headers=headers,
        json={"ledger_entry_id": ledger_entry_id},
    )

    unmatched = client.post(
        f"/api/v1/bank-reconciliation/statement-lines/{line_id}/unmatch", headers=headers
    )
    assert unmatched.status_code == 200
    assert unmatched.json()["matched_ledger_entry_id"] is None

    status_after = client.get(
        "/api/v1/bank-reconciliation/status", headers=headers, params={"account_code": "cash"}
    )
    assert len(status_after.json()["unmatched_statement_lines"]) == 1
    assert len(status_after.json()["unmatched_ledger_entries"]) == 1


def test_non_admin_cannot_manage_reconciliation() -> None:
    org_id = create_org()
    email = "recon-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    headers = auth_headers(login(email)["access_token"])
    denied = client.get(
        "/api/v1/bank-reconciliation/status", headers=headers, params={"account_code": "cash"}
    )
    assert denied.status_code == 403
