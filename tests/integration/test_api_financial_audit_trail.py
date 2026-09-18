"""Every write action across Bills, Invoices, Credit Notes, Budgets, the
General Ledger, Fixed Assets and Bank Reconciliation records an audit
event — these modules previously logged nothing at all, unlike the
payroll-adjacent ones (expenses, loans, pay runs, ...)."""

from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str) -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> dict[str, str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    return headers


def _audit_actions(headers: dict[str, str], entity_type: str) -> list[str]:
    response = client.get("/api/v1/audit-log", headers=headers, params={"entity_type": entity_type})
    assert response.status_code == 200, response.text
    return [entry["action"] for entry in response.json()]


def test_bill_lifecycle_is_audited() -> None:
    headers = _setup("audit-bill-admin@example.com")
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Audit Vendor"}
    ).json()["id"]
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "AUDIT-BILL-1",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
        },
    ).json()
    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)

    actions = _audit_actions(headers, "bill")
    assert actions == ["bill.pay", "bill.approve", "bill.create"]


def test_bill_void_is_audited() -> None:
    headers = _setup("audit-bill-void-admin@example.com")
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Audit Vendor 2"}
    ).json()["id"]
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "AUDIT-BILL-2",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 50_000_00,
        },
    ).json()
    client.post(f"/api/v1/bills/{bill['id']}/void", headers=headers)

    assert _audit_actions(headers, "bill") == ["bill.void", "bill.create"]


def test_invoice_lifecycle_is_audited() -> None:
    headers = _setup("audit-invoice-admin@example.com")
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Audit Customer"}
    ).json()["id"]
    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "AUDIT-INV-1",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "revenue",
            "amount_minor": 200_000_00,
        },
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    client.post(f"/api/v1/invoices/{invoice['id']}/pay", headers=headers)

    assert _audit_actions(headers, "invoice") == [
        "invoice.pay",
        "invoice.send",
        "invoice.create",
    ]


def test_credit_note_is_audited() -> None:
    headers = _setup("audit-credit-note-admin@example.com")
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Audit CN Customer"}
    ).json()["id"]
    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "AUDIT-CN-INV-1",
            "issue_date": "2026-01-01",
            "due_date": "2026-01-31",
            "revenue_account_code": "revenue",
            "amount_minor": 500_000_00,
        },
    ).json()
    sent = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers).json()

    created = client.post(
        f"/api/v1/invoices/{sent['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-1",
            "issue_date": "2026-01-15",
            "amount_minor": 50_000_00,
            "reason": "goodwill adjustment",
        },
    )
    assert created.status_code == 201, created.text

    assert _audit_actions(headers, "credit_note") == ["credit_note.create"]


def test_budget_lifecycle_is_audited() -> None:
    headers = _setup("audit-budget-admin@example.com")
    budget = client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "Audit Budget",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "lines": [{"account_code": "revenue", "amount_minor": 1_000_000_00}],
        },
    ).json()

    client.put(
        f"/api/v1/budgets/{budget['id']}",
        headers=headers,
        json={
            "name": "Audit Budget",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "lines": [{"account_code": "revenue", "amount_minor": 2_000_000_00}],
        },
    )
    client.delete(f"/api/v1/budgets/{budget['id']}", headers=headers)

    assert _audit_actions(headers, "budget") == [
        "budget.delete",
        "budget.update",
        "budget.create",
    ]


def test_manual_journal_entry_is_audited() -> None:
    headers = _setup("audit-ledger-admin@example.com")
    posted = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "Manual correction",
            "lines": [
                {"account_code": "contractor_expense", "debit_minor": 10_000_00},
                {"account_code": "cash", "credit_minor": 10_000_00},
            ],
        },
    )
    assert posted.status_code == 201, posted.text

    entries = client.get(
        "/api/v1/audit-log", headers=headers, params={"entity_type": "ledger_entry"}
    ).json()
    assert len(entries) == 1
    assert entries[0]["action"] == "ledger_entry.create"
    assert entries[0]["event_metadata"]["line_count"] == 2


def test_fixed_asset_lifecycle_is_audited() -> None:
    headers = _setup("audit-fixed-asset-admin@example.com")
    asset = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Audit Printer",
            "asset_tag": "AUDIT-FA-1",
            "acquisition_date": "2026-01-01",
            "cost_minor": 200_000_00,
            "useful_life_months": 2,
        },
    ).json()
    client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
    client.post(
        f"/api/v1/fixed-assets/{asset['id']}/revalue",
        headers=headers,
        json={
            "new_value_minor": 150_000_00,
            "revaluation_date": "2026-02-01",
            "reason": "market appraisal",
        },
    )
    department_id = client.post(
        "/api/v1/departments", headers=headers, json={"name": "Operations"}
    ).json()["id"]
    client.post(
        f"/api/v1/fixed-assets/{asset['id']}/transfer",
        headers=headers,
        json={"to_department_id": department_id, "transfer_date": "2026-02-02"},
    )
    client.post(
        f"/api/v1/fixed-assets/{asset['id']}/dispose",
        headers=headers,
        json={"proceeds_minor": 100_000_00},
    )

    assert _audit_actions(headers, "fixed_asset") == [
        "fixed_asset.dispose",
        "fixed_asset.transfer",
        "fixed_asset.revalue",
        "fixed_asset.depreciate",
        "fixed_asset.create",
    ]


def test_bank_reconciliation_match_and_unmatch_are_audited() -> None:
    headers = _setup("audit-recon-admin@example.com")
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Recon Audit Vendor"}
    ).json()["id"]
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "AUDIT-RECON-1",
            "bill_date": "2026-02-01",
            "due_date": "2026-02-28",
            "expense_account_code": "contractor_expense",
            "amount_minor": 250_000_00,
        },
    ).json()
    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)
    ledger_entry_id = client.get(
        "/api/v1/general-ledger/entries", headers=headers, params={"account": "cash"}
    ).json()[0]["id"]

    imported = client.post(
        "/api/v1/bank-reconciliation/statement-lines",
        headers=headers,
        json={
            "account_code": "cash",
            "lines": [
                {
                    "transaction_date": "2026-02-05",
                    "description": "Payment to Recon Audit Vendor",
                    "amount_minor": -250_000_00,
                    "external_reference": "AUDIT-TXN-1",
                }
            ],
        },
    )
    line_id = imported.json()[0]["id"]

    client.post(
        f"/api/v1/bank-reconciliation/statement-lines/{line_id}/match",
        headers=headers,
        json={"ledger_entry_id": ledger_entry_id},
    )
    client.post(f"/api/v1/bank-reconciliation/statement-lines/{line_id}/unmatch", headers=headers)

    assert _audit_actions(headers, "ledger_statement_line") == [
        "bank_reconciliation.unmatch",
        "bank_reconciliation.match",
        "bank_reconciliation.import_statement_lines",
    ]
