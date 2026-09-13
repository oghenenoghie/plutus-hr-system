from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "aging-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_ap_aging_only_includes_approved_bills_bucketed_by_due_date() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Overdue Supplies Ltd"}
    ).json()["id"]

    overdue_bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "BILL-AGE-1",
            "bill_date": "2026-01-01",
            "due_date": "2026-01-10",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
        },
    ).json()
    client.post(f"/api/v1/bills/{overdue_bill['id']}/approve", headers=headers)

    draft_bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "BILL-AGE-2",
            "bill_date": "2026-01-01",
            "due_date": "2026-01-10",
            "expense_account_code": "contractor_expense",
            "amount_minor": 50_000_00,
        },
    ).json()
    # left in draft — should not appear in the aging report at all

    report = client.get("/api/v1/reports/ap-aging", headers=headers, params={"as_of": "2026-03-01"})
    assert report.status_code == 200, report.text
    lines = report.json()
    assert [line["reference_number"] for line in lines] == ["BILL-AGE-1"]
    assert lines[0]["counterparty_name"] == "Overdue Supplies Ltd"
    assert lines[0]["amount_minor"] == 100_000_00
    # 2026-01-10 to 2026-03-01 is 50 days overdue.
    assert lines[0]["bucket"] == "31_60"
    assert draft_bill["status"] == "draft"


def test_ar_aging_only_includes_sent_invoices() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="aging-admin2@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Northgate Traders"}
    ).json()["id"]

    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-AGE-1",
            "issue_date": "2026-01-01",
            "due_date": "2026-01-15",
            "revenue_account_code": "revenue",
            "amount_minor": 200_000_00,
        },
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)

    report = client.get("/api/v1/reports/ar-aging", headers=headers, params={"as_of": "2026-01-20"})
    assert report.status_code == 200, report.text
    lines = report.json()
    assert [line["reference_number"] for line in lines] == ["INV-AGE-1"]
    assert lines[0]["bucket"] == "1_30"


def test_non_admin_cannot_view_aging_reports() -> None:
    org_id = create_org()
    email = "aging-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    headers = auth_headers(login(email)["access_token"])
    denied = client.get("/api/v1/reports/ap-aging", headers=headers)
    assert denied.status_code == 403
