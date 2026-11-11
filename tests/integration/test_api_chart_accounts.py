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


def _admin_headers(org_id, email: str = "coa-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_seed_defaults_creates_default_accounts_and_is_idempotent() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    codes = {account["code"] for account in seeded.json()}
    assert "cash" in codes
    assert "paye_payable" in codes
    assert all(account["is_system"] for account in seeded.json())

    listed = client.get("/api/v1/chart-of-accounts", headers=headers)
    assert len(listed.json()) == len(codes)

    reseeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert reseeded.status_code == 200
    assert reseeded.json() == []

    listed_again = client.get("/api/v1/chart-of-accounts", headers=headers)
    assert len(listed_again.json()) == len(codes)


def test_admin_can_create_custom_account_and_duplicate_code_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="coa-admin2@example.com")

    created = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={"code": "accounts_receivable", "name": "Accounts Receivable", "type": "asset"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_system"] is False

    duplicate = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={"code": "accounts_receivable", "name": "Duplicate", "type": "asset"},
    )
    assert duplicate.status_code == 400

    account_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/chart-of-accounts/{account_id}",
        headers=headers,
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False


def test_manager_and_employee_cannot_manage_chart_of_accounts() -> None:
    org_id = create_org()

    manager_email = "coa-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied_manager = client.get("/api/v1/chart-of-accounts", headers=manager_headers)
    assert denied_manager.status_code == 403

    employee_email = "coa-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-961")
    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied_employee = client.post(
        "/api/v1/chart-of-accounts",
        headers=employee_headers,
        json={"code": "x", "name": "X", "type": "asset"},
    )
    assert denied_employee.status_code == 403


def test_accounts_are_numbered_in_their_category_ranges() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="coa-admin3@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)

    listed = client.get("/api/v1/chart-of-accounts", headers=headers).json()
    by_code = {account["code"]: account for account in listed}
    assert by_code["cash"]["account_number"] == "1000"
    assert by_code["cash"]["name"] == "Cash and Bank"
    assert by_code["fixed_assets"]["category"] == "non_current_asset"
    assert by_code["revenue"]["account_number"] == "4000"
    assert by_code["payroll_expense_gross"]["category"] == "operating_expense"
    assert by_code["payroll_expense_gross"]["category_label"] == "Overheads"
    assert by_code["revenue"]["statement"] == "profit_and_loss"
    assert by_code["accounts_payable"]["statement"] == "balance_sheet"
    numbers = [account["account_number"] for account in listed]
    assert numbers == sorted(numbers)

    # A new sales account, numbered for the user: the next free ten in 4000-4799.
    next_number = client.get(
        "/api/v1/chart-of-accounts/next-number", headers=headers, params={"category": "revenue"}
    )
    assert next_number.status_code == 200, next_number.text
    assert next_number.json() == {
        "category": "revenue",
        "account_number": "4010",
        "range_from": 4000,
        "range_to": 4799,
    }
    sales = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={"name": "Consulting Fees", "type": "revenue", "category": "revenue"},
    )
    assert sales.status_code == 201, sales.text
    assert sales.json()["account_number"] == "4010"
    assert sales.json()["code"] == "acct_4010"

    # A cost of sales account at a number the user picks.
    cost = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={
            "name": "Purchases",
            "type": "expense",
            "category": "cost_of_sales",
            "account_number": "5100",
        },
    )
    assert cost.status_code == 201, cost.text
    assert cost.json()["category"] == "cost_of_sales"

    out_of_range = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={
            "name": "Rent",
            "type": "expense",
            "category": "operating_expense",
            "account_number": "5200",
        },
    )
    assert out_of_range.status_code == 400
    assert "6000–7999" in out_of_range.json()["detail"]

    wrong_type = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={"name": "Rent", "type": "revenue", "category": "operating_expense"},
    )
    assert wrong_type.status_code == 400

    taken = client.post(
        "/api/v1/chart-of-accounts",
        headers=headers,
        json={
            "name": "Rent",
            "type": "expense",
            "category": "cost_of_sales",
            "account_number": "5100",
        },
    )
    assert taken.status_code == 400
    assert "already in use" in taken.json()["detail"]
