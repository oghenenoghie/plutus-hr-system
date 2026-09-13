from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "recurbill-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> tuple[dict[str, str], str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Recurring Vendor"}
    ).json()["id"]
    return headers, vendor_id


def test_generate_due_bills_creates_one_bill_and_advances_next_run_date() -> None:
    headers, vendor_id = _setup("recurbill-admin1@example.com")

    created = client.post(
        "/api/v1/recurring-bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number_prefix": "RENT",
            "expense_account_code": "contractor_expense",
            "amount_minor": 50_000_00,
            "frequency": "monthly",
            "next_run_date": "2026-01-01",
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    generated = client.post(
        "/api/v1/recurring-bills/generate-due", headers=headers, params={"as_of": "2026-01-15"}
    )
    assert generated.status_code == 200, generated.text
    bills = generated.json()
    assert len(bills) == 1
    assert bills[0]["bill_number"] == "RENT-2026-01-01"
    assert bills[0]["bill_date"] == "2026-01-01"
    assert bills[0]["amount_minor"] == 50_000_00

    templates = client.get("/api/v1/recurring-bills", headers=headers).json()
    assert next(t for t in templates if t["id"] == template_id)["next_run_date"] == "2026-02-01"

    # Running again the same day generates nothing further.
    again = client.post(
        "/api/v1/recurring-bills/generate-due", headers=headers, params={"as_of": "2026-01-15"}
    )
    assert again.json() == []


def test_paused_recurring_bill_is_not_generated() -> None:
    headers, vendor_id = _setup("recurbill-admin2@example.com")

    template_id = client.post(
        "/api/v1/recurring-bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number_prefix": "SUB",
            "expense_account_code": "contractor_expense",
            "amount_minor": 20_000_00,
            "frequency": "monthly",
            "next_run_date": "2026-01-01",
        },
    ).json()["id"]

    client.patch(
        f"/api/v1/recurring-bills/{template_id}", headers=headers, json={"is_active": False}
    )

    generated = client.post(
        "/api/v1/recurring-bills/generate-due", headers=headers, params={"as_of": "2026-01-15"}
    )
    assert generated.json() == []
