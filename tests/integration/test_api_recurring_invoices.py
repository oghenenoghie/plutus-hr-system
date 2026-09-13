from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "recurinv-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> tuple[dict[str, str], str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer_id = client.post(
        "/api/v1/customers", headers=headers, json={"name": "Recurring Customer"}
    ).json()["id"]
    return headers, customer_id


def test_generate_due_invoices_creates_one_invoice_and_advances_next_run_date() -> None:
    headers, customer_id = _setup("recurinv-admin1@example.com")

    created = client.post(
        "/api/v1/recurring-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number_prefix": "SUB",
            "revenue_account_code": "revenue",
            "amount_minor": 30_000_00,
            "frequency": "quarterly",
            "next_run_date": "2026-01-01",
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    generated = client.post(
        "/api/v1/recurring-invoices/generate-due", headers=headers, params={"as_of": "2026-01-02"}
    )
    assert generated.status_code == 200, generated.text
    invoices = generated.json()
    assert len(invoices) == 1
    assert invoices[0]["invoice_number"] == "SUB-2026-01-01"

    templates = client.get("/api/v1/recurring-invoices", headers=headers).json()
    assert next(t for t in templates if t["id"] == template_id)["next_run_date"] == "2026-04-01"


def test_non_admin_cannot_manage_recurring_invoices() -> None:
    org_id = create_org()
    email = "recurinv-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=email)
    headers = auth_headers(login(email)["access_token"])
    denied = client.get("/api/v1/recurring-invoices", headers=headers)
    assert denied.status_code == 403
