from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "finstmt-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_balance_sheet_lists_seeded_accounts_with_zero_balance() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text

    balance_sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers)
    assert balance_sheet.status_code == 200, balance_sheet.text
    body = balance_sheet.json()
    asset_codes = {line["account"] for line in body["assets"]}
    liability_codes = {line["account"] for line in body["liabilities"]}
    assert "cash" in asset_codes
    assert "accounts_payable" in liability_codes
    assert body["total_assets_minor"] == 0
    assert body["total_liabilities_minor"] == 0
    assert body["equity"] == []


def test_balance_sheet_and_income_statement_reflect_a_paid_bill() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finstmt-admin2@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    vendor = client.post("/api/v1/vendors", headers=headers, json={"name": "Acme Supplies"})
    vendor_id = vendor.json()["id"]

    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "INV-01",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 200_000_00,
        },
    ).json()
    client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
    client.post(f"/api/v1/bills/{bill['id']}/pay", headers=headers)

    balance_sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers).json()
    by_account = {line["account"]: line["balance_minor"] for line in balance_sheet["assets"]}
    assert by_account["cash"] == -200_000_00
    liabilities_by_account = {
        line["account"]: line["balance_minor"] for line in balance_sheet["liabilities"]
    }
    assert liabilities_by_account["accounts_payable"] == 0

    income_statement = client.get(
        "/api/v1/financial-statements/income-statement", headers=headers
    ).json()
    expenses_by_account = {
        line["account"]: line["balance_minor"] for line in income_statement["expenses"]
    }
    assert expenses_by_account["contractor_expense"] == 200_000_00
    assert income_statement["net_income_minor"] == -200_000_00


def test_income_statement_reflects_a_sent_invoice() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finstmt-admin3@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Zenith Retail"})
    customer_id = customer.json()["id"]

    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-01",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "revenue",
            "amount_minor": 500_000_00,
        },
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)

    income_statement = client.get(
        "/api/v1/financial-statements/income-statement", headers=headers
    ).json()
    revenue_by_account = {
        line["account"]: line["balance_minor"] for line in income_statement["revenue"]
    }
    assert revenue_by_account["revenue"] == 500_000_00
    assert income_statement["net_income_minor"] == 500_000_00

    balance_sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers).json()
    assets_by_account = {line["account"]: line["balance_minor"] for line in balance_sheet["assets"]}
    assert assets_by_account["accounts_receivable"] == 500_000_00


def test_income_statement_with_future_date_range_excludes_current_activity() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finstmt-admin4@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Zenith Retail"})
    customer_id = customer.json()["id"]
    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-01",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "revenue",
            "amount_minor": 500_000_00,
        },
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)

    income_statement = client.get(
        "/api/v1/financial-statements/income-statement",
        headers=headers,
        params={"from_date": "2099-01-01"},
    ).json()
    assert income_statement["total_revenue_minor"] == 0
    assert income_statement["net_income_minor"] == 0


def test_manager_and_employee_cannot_view_financial_statements() -> None:
    org_id = create_org()

    manager_email = "finstmt-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied_manager = client.get(
        "/api/v1/financial-statements/balance-sheet", headers=manager_headers
    )
    assert denied_manager.status_code == 403

    employee_email = "finstmt-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-964")
    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied_employee = client.get(
        "/api/v1/financial-statements/income-statement", headers=employee_headers
    )
    assert denied_employee.status_code == 403
