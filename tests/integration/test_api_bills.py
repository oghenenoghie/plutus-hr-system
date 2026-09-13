from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "bill-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> tuple[dict[str, str], str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    vendor = client.post("/api/v1/vendors", headers=headers, json={"name": "Acme Supplies"})
    assert vendor.status_code == 201, vendor.text
    return headers, vendor.json()["id"]


def _create_bill(headers: dict[str, str], vendor_id: str, bill_number: str = "INV-001") -> dict:
    response = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": bill_number,
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 500_000_00,
            "description": "September office supplies",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_bill_lifecycle_draft_to_approved_to_paid_posts_balanced_ledger_entries() -> None:
    headers, vendor_id = _setup("bill-admin1@example.com")
    bill = _create_bill(headers, vendor_id)
    assert bill["status"] == "draft"

    approved = client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    paid = client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"
    assert paid.json()["paid_at"] is not None

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    by_account = {line["account"]: line for line in trial_balance.json()}
    assert by_account["contractor_expense"]["balance_minor"] == 500_000_00
    assert by_account["accounts_payable"]["balance_minor"] == 0
    assert by_account["cash"]["balance_minor"] == -500_000_00


def test_bill_cannot_be_paid_before_approval() -> None:
    headers, vendor_id = _setup("bill-admin2@example.com")
    bill = _create_bill(headers, vendor_id)

    response = client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)
    assert response.status_code == 400
    assert "approved" in response.json()["detail"]


def test_bill_cannot_be_approved_twice() -> None:
    headers, vendor_id = _setup("bill-admin3@example.com")
    bill = _create_bill(headers, vendor_id)

    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    second = client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    assert second.status_code == 400


def test_approved_bill_cannot_be_voided_but_draft_bill_can() -> None:
    headers, vendor_id = _setup("bill-admin4@example.com")
    bill = _create_bill(headers, vendor_id)

    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    denied = client.post(f"/api/v1/bills/{bill['id']}/void", headers=headers)
    assert denied.status_code == 400

    draft_bill = _create_bill(headers, vendor_id, bill_number="INV-002")
    voided = client.post(f"/api/v1/bills/{draft_bill['id']}/void", headers=headers)
    assert voided.status_code == 200


def test_bill_with_vat_posts_input_vat_and_inflates_the_payable() -> None:
    headers, vendor_id = _setup("bill-admin8@example.com")
    created = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "VAT-1",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
            "vat_minor": 7_500_00,
        },
    )
    assert created.status_code == 201, created.text
    bill = created.json()
    assert bill["net_payable_minor"] == 107_500_00

    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    paid = client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)
    assert paid.status_code == 200, paid.text

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    by_account = {line["account"]: line for line in trial_balance.json()}
    assert by_account["contractor_expense"]["balance_minor"] == 100_000_00
    assert by_account["vat_receivable"]["balance_minor"] == 7_500_00
    assert by_account["accounts_payable"]["balance_minor"] == 0
    assert by_account["cash"]["balance_minor"] == -107_500_00


def test_bill_with_wht_category_withholds_tax_and_reduces_the_payable() -> None:
    headers, vendor_id = _setup("bill-admin9@example.com")
    created = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "WHT-1",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
            "wht_category": "services",
        },
    )
    assert created.status_code == 201, created.text
    bill = created.json()
    assert bill["wht_amount_minor"] == 0  # not yet computed before approval

    approved = client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    # "services" is a 10% WHT category in NG_2026_1.
    assert approved_body["wht_amount_minor"] == 10_000_00
    assert approved_body["net_payable_minor"] == 90_000_00

    paid = client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)
    assert paid.status_code == 200, paid.text

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    by_account = {line["account"]: line for line in trial_balance.json()}
    assert by_account["contractor_expense"]["balance_minor"] == 100_000_00
    assert by_account["wht_payable"]["balance_minor"] == -10_000_00
    assert by_account["accounts_payable"]["balance_minor"] == 0
    assert by_account["cash"]["balance_minor"] == -90_000_00


def test_bill_rejects_unknown_wht_category() -> None:
    headers, vendor_id = _setup("bill-admin10@example.com")
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "WHT-2",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
            "wht_category": "not_a_real_category",
        },
    ).json()

    denied = client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    assert denied.status_code == 400


def test_bill_rejects_unknown_expense_account() -> None:
    headers, vendor_id = _setup("bill-admin5@example.com")

    response = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "INV-003",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "not_a_real_account",
            "amount_minor": 1_000_00,
        },
    )
    assert response.status_code == 400
