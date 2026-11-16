from app.models import Role
from app.services.posting import today_lagos
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


def test_balance_sheet_leaves_out_accounts_with_nothing_on_them() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text

    balance_sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers)
    assert balance_sheet.status_code == 200, balance_sheet.text
    body = balance_sheet.json()
    # A freshly seeded chart has nothing on it, so the sheet shows nothing:
    # no row of zeros for every account (the reviewing accountant's note).
    assert body["assets"] == []
    assert body["liabilities"] == []
    assert body["equity"] == []
    for section in (
        "non_current_assets",
        "current_assets",
        "current_liabilities",
        "non_current_liabilities",
        "capital_and_reserves",
    ):
        assert body[section]["lines"] == []
        assert body[section]["total_minor"] == 0
    assert body["balanced"] is True
    assert body["non_current_assets"]["label"] == "Fixed assets"
    assert body["current_liabilities"]["label"] == (
        "Current liabilities: amounts falling due within one year"
    )
    assert body["non_current_liabilities"]["label"] == (
        "Long-term liabilities: amounts falling due after more than one year"
    )

    capital = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "Share capital paid in",
            "lines": [
                {"account_code": "cash", "debit_minor": 1_000_000_00},
                {"account_code": "share_capital", "credit_minor": 1_000_000_00},
            ],
        },
    )
    assert capital.status_code == 201, capital.text
    body = client.get("/api/v1/financial-statements/balance-sheet", headers=headers).json()
    assert [line["account"] for line in body["current_assets"]["lines"]] == ["cash"]
    cash = body["current_assets"]["lines"][0]
    assert cash["account_name"] == "Cash and Bank"
    assert cash["account_number"] == "1000"
    # Share capital, and no Revaluation Surplus or Profit and Loss Reserve
    # line while neither holds anything.
    assert [line["account"] for line in body["capital_and_reserves"]["lines"]] == ["share_capital"]
    assert body["balanced"] is True


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
    # The bill was paid, so Accounts Payable is back at nothing and left out.
    liabilities_by_account = {
        line["account"]: line["balance_minor"] for line in balance_sheet["liabilities"]
    }
    assert "accounts_payable" not in liabilities_by_account

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


def _journal(headers: dict[str, str], description: str, *lines: tuple[str, int, int]) -> None:
    response = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": description,
            "lines": [
                {"account_code": code, "debit_minor": debit, "credit_minor": credit}
                for code, debit, credit in lines
            ],
        },
    )
    assert response.status_code == 201, response.text


def test_balance_sheet_summarises_fixed_assets_whatever_accounts_hold_them() -> None:
    # The reviewing accountant's case: printers and computers on accounts of
    # their own, each with its accumulated depreciation. The sheet shows one
    # figure at cost and one written off, not a pair per kind of asset; the
    # account by account figures stay in `assets`.
    org_id = create_org()
    headers = _admin_headers(org_id, email="finstmt-summary@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    for code, name in (
        ("printers", "Printers"),
        ("printers_depreciation", "Accumulated depreciation — printers"),
        ("computers", "Computers"),
        ("computers_depreciation", "Accumulated depreciation — computers"),
    ):
        created = client.post(
            "/api/v1/chart-of-accounts",
            headers=headers,
            json={"name": name, "code": code, "type": "asset", "category": "non_current_asset"},
        )
        assert created.status_code == 201, created.text
    _journal(
        headers,
        "Capital",
        ("cash", 10_000_000_00, 0),
        ("share_capital", 0, 10_000_000_00),
    )
    _journal(
        headers,
        "Printers and computers bought",
        ("printers", 600_000_00, 0),
        ("computers", 1_200_000_00, 0),
        ("cash", 0, 1_800_000_00),
    )
    _journal(
        headers,
        "Depreciation",
        ("depreciation_expense", 300_000_00, 0),
        ("printers_depreciation", 0, 100_000_00),
        ("computers_depreciation", 0, 200_000_00),
    )

    sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers).json()
    fixed = sheet["non_current_assets"]
    assert fixed["label"] == "Fixed assets"
    assert [(line["account_name"], line["balance_minor"]) for line in fixed["lines"]] == [
        ("Fixed assets at cost", 1_800_000_00),
        ("Accumulated depreciation and amortisation", -300_000_00),
    ]
    assert fixed["total_minor"] == 1_500_000_00
    # Net fixed assets plus current assets, less liabilities, is net assets,
    # and capital and reserves (share capital and the year's loss) equal it.
    assert sheet["current_assets"]["total_minor"] == 8_200_000_00
    assert sheet["net_assets_minor"] == 9_700_000_00
    assert [line["account"] for line in sheet["capital_and_reserves"]["lines"]] == [
        "share_capital",
        "profit_and_loss_reserve",
    ]
    assert sheet["capital_and_reserves"]["total_minor"] == 9_700_000_00
    assert sheet["balanced"] is True
    assert {line["account"] for line in sheet["assets"]} >= {
        "printers",
        "printers_depreciation",
        "computers",
        "computers_depreciation",
    }


def test_lease_liability_is_split_by_when_it_falls_due() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finstmt-lease@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    today = today_lagos().isoformat()
    lease = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Delivery van",
            "asset_tag": "VAN-1",
            "acquisition_date": today,
            "cost_minor": 3_600_000_00,
            "useful_life_months": 36,
            "acquisition_type": "leased",
            "lease_term_months": 36,
        },
    )
    assert lease.status_code == 201, lease.text

    sheet = client.get(
        f"/api/v1/financial-statements/balance-sheet?as_of={today}", headers=headers
    ).json()
    # A 36-month lease taken today: the next twelve instalments fall due
    # within the year, the other twenty-four after it.
    assert [
        (line["account"], line["balance_minor"]) for line in sheet["current_liabilities"]["lines"]
    ] == [("lease_liability_due_within_one_year", 1_200_000_00)]
    assert [
        (line["account"], line["balance_minor"])
        for line in sheet["non_current_liabilities"]["lines"]
    ] == [("lease_liability_due_after_one_year", 2_400_000_00)]
    assert sheet["net_current_assets_minor"] == -1_200_000_00
    assert sheet["balanced"] is True
    # The account by account figures keep the liability whole.
    assert {line["account"]: line["balance_minor"] for line in sheet["liabilities"]} == {
        "lease_liability": 3_600_000_00
    }


def test_statements_report_postings_by_their_accounting_date() -> None:
    # Year-end depreciation is dated 31 December whenever it's run, so it
    # belongs to December's figures, not to the day it was entered.
    org_id = create_org()
    headers = _admin_headers(org_id, email="finstmt-dates@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    created = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Generator",
            "asset_tag": "GEN-1",
            "acquisition_date": "2025-01-01",
            "cost_minor": 1_200_000_00,
            "useful_life_months": 12,
        },
    )
    assert created.status_code == 201, created.text

    def depreciation(from_date: str, to_date: str) -> int:
        profit = client.get(
            f"/api/v1/financial-statements/income-statement?from_date={from_date}&to_date={to_date}",
            headers=headers,
        ).json()
        lines = {line["account"]: line["balance_minor"] for line in profit["overheads"]["lines"]}
        return lines.get("depreciation_expense", 0)

    pending = client.get(
        "/api/v1/financial-statements/income-statement?from_date=2025-01-01&to_date=2025-12-31",
        headers=headers,
    ).json()
    assert pending["assets_awaiting_depreciation"] == 1

    run = client.post(
        "/api/v1/fixed-assets/year-end-depreciation", headers=headers, json={"year": 2025}
    )
    assert run.status_code == 200, run.text
    assert depreciation("2025-12-31", "2025-12-31") == 1_200_000_00
    assert depreciation("2025-01-01", "2025-12-30") == 0
    after = client.get(
        "/api/v1/financial-statements/income-statement?from_date=2025-01-01&to_date=2025-12-31",
        headers=headers,
    ).json()
    assert after["assets_awaiting_depreciation"] == 0
