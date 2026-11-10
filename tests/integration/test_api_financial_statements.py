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
    # The seeded equity accounts, and the profit and loss reserve the sheet
    # works out — all at zero until something is posted.
    assert {line["account"] for line in body["equity"]} == {
        "revaluation_surplus",
        "share_capital",
        "profit_and_loss_reserve",
    }
    assert body["total_equity_minor"] == 0
    assert body["balanced"] is True
    assert body["non_current_assets"]["label"] == "Non-current assets"
    assert [line["account"] for line in body["non_current_assets"]["lines"]] == [
        "fixed_assets",
        "accumulated_depreciation",
    ]
    cash = next(line for line in body["current_assets"]["lines"] if line["account"] == "cash")
    assert cash["account_name"] == "Cash and Bank"
    assert cash["account_number"] == "1000"


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
    # The invoice's profit is carried to the balance sheet as the profit and
    # loss reserve, so the sheet balances.
    assert balance_sheet["profit_and_loss_reserve_minor"] == 500_000_00
    assert balance_sheet["net_assets_minor"] == 500_000_00
    assert balance_sheet["capital_and_reserves"]["total_minor"] == 500_000_00
    assert balance_sheet["balanced"] is True


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


def test_statements_balance_and_split_sales_cost_of_sales_and_overheads() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finstmt-admin5@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    purchases = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={"name": "Purchases", "type": "expense", "category": "cost_of_sales"},
    ).json()
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Zenith"}).json()
    vendor = client.post("/api/v1/vendors", headers=headers, json={"name": "Acme"}).json()

    invoice = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer["id"],
            "invoice_number": "INV-01",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "revenue",
            "amount_minor": 1_000_000_00,
        },
    ).json()
    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    for number, account, amount in (
        ("B-1", purchases["code"], 400_000_00),
        ("B-2", "contractor_expense", 300_000_00),
    ):
        bill = client.post(
            "/api/v1/bills",
            headers=headers,
            json={
                "vendor_id": vendor["id"],
                "bill_number": number,
                "bill_date": "2026-09-01",
                "due_date": "2026-09-30",
                "expense_account_code": account,
                "amount_minor": amount,
            },
        ).json()
        approved = client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
        assert approved.status_code == 200, approved.text

    profit = client.get("/api/v1/financial-statements/income-statement", headers=headers).json()
    assert profit["sales"]["total_minor"] == 1_000_000_00
    assert profit["cost_of_sales"]["total_minor"] == 400_000_00
    assert profit["gross_profit_minor"] == 600_000_00
    assert profit["overheads"]["total_minor"] == 300_000_00
    assert profit["net_income_minor"] == 300_000_00

    sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers).json()
    assert sheet["current_assets"]["total_minor"] == 1_000_000_00
    assert sheet["current_liabilities"]["total_minor"] == 700_000_00
    assert sheet["net_current_assets_minor"] == 300_000_00
    assert sheet["net_assets_minor"] == 300_000_00
    reserve = sheet["capital_and_reserves"]["lines"][-1]
    assert reserve == {
        "account": "profit_and_loss_reserve",
        "account_name": "Profit and Loss Reserve",
        "balance_minor": 300_000_00,
        "account_number": None,
    }
    assert sheet["balanced"] is True

    pdf = client.get("/api/v1/financial-statements/balance-sheet/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    pdf = client.get("/api/v1/financial-statements/income-statement/pdf", headers=headers)
    assert pdf.status_code == 200
