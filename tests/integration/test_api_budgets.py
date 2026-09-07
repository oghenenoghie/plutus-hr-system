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


def _admin_headers(org_id, email: str = "budget-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> dict[str, str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    return headers


def _create_budget(
    headers: dict[str, str],
    name: str = "Q1 Operating Budget",
    lines: list[dict] | None = None,
) -> dict:
    body = {
        "name": name,
        "period_start": "2020-01-01",
        "period_end": "2030-12-31",
        "lines": lines
        or [
            {"account_code": "revenue", "amount_minor": 1_000_000_00},
            {"account_code": "contractor_expense", "amount_minor": 200_000_00},
        ],
    }
    response = client.post("/api/v1/budgets", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_budget_lists_lines_with_account_names_and_total() -> None:
    headers = _setup("budget-admin1@example.com")
    budget = _create_budget(headers)

    assert budget["total_budgeted_minor"] == 1_200_000_00
    by_code = {line["account_code"]: line for line in budget["lines"]}
    assert by_code["revenue"]["account_name"] == "Revenue"
    assert by_code["revenue"]["amount_minor"] == 1_000_000_00


def test_budget_rejects_balance_sheet_account() -> None:
    headers = _setup("budget-admin2@example.com")
    response = client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "Bad Budget",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "lines": [{"account_code": "cash", "amount_minor": 100_00}],
        },
    )
    assert response.status_code == 400
    assert "not a known revenue/expense account" in response.json()["detail"]


def test_budget_rejects_duplicate_account_lines() -> None:
    headers = _setup("budget-admin3@example.com")
    response = client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "Dup Budget",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "lines": [
                {"account_code": "revenue", "amount_minor": 100_00},
                {"account_code": "revenue", "amount_minor": 200_00},
            ],
        },
    )
    assert response.status_code == 400
    assert "duplicate account code" in response.json()["detail"]


def test_budget_actuals_reflects_ledger_activity_within_period() -> None:
    headers = _setup("budget-admin4@example.com")
    budget = _create_budget(
        headers,
        lines=[
            {"account_code": "revenue", "amount_minor": 500_000_00},
            {"account_code": "contractor_expense", "amount_minor": 100_000_00},
        ],
    )

    # Inside the budget period: counts toward actuals.
    posted = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "February contractor invoice",
            "lines": [
                {"account_code": "contractor_expense", "debit_minor": 60_000_00},
                {"account_code": "cash", "credit_minor": 60_000_00},
            ],
        },
    )
    assert posted.status_code == 201, posted.text

    actuals = client.get(f"/api/v1/budgets/{budget['id']}/actuals", headers=headers)
    assert actuals.status_code == 200, actuals.text
    body = actuals.json()
    by_code = {line["account_code"]: line for line in body["lines"]}

    assert by_code["contractor_expense"]["budgeted_minor"] == 100_000_00
    assert by_code["contractor_expense"]["actual_minor"] == 60_000_00
    assert by_code["contractor_expense"]["variance_minor"] == -40_000_00

    assert by_code["revenue"]["actual_minor"] == 0
    assert by_code["revenue"]["variance_minor"] == -500_000_00

    assert body["total_budgeted_minor"] == 600_000_00
    assert body["total_actual_minor"] == 60_000_00


def test_update_budget_replaces_lines_wholesale() -> None:
    headers = _setup("budget-admin5@example.com")
    budget = _create_budget(headers)

    updated = client.put(
        f"/api/v1/budgets/{budget['id']}",
        headers=headers,
        json={
            "name": "Q1 Operating Budget",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "lines": [{"account_code": "revenue", "amount_minor": 2_000_000_00}],
        },
    )
    assert updated.status_code == 200, updated.text
    assert len(updated.json()["lines"]) == 1
    assert updated.json()["total_budgeted_minor"] == 2_000_000_00


def test_delete_budget() -> None:
    headers = _setup("budget-admin6@example.com")
    budget = _create_budget(headers)

    deleted = client.delete(f"/api/v1/budgets/{budget['id']}", headers=headers)
    assert deleted.status_code == 204

    missing = client.get(f"/api/v1/budgets/{budget['id']}", headers=headers)
    assert missing.status_code == 404


def test_duplicate_budget_name_is_rejected() -> None:
    headers = _setup("budget-admin7@example.com")
    _create_budget(headers)
    duplicate = client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "Q1 Operating Budget",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "lines": [{"account_code": "revenue", "amount_minor": 100_00}],
        },
    )
    assert duplicate.status_code == 400


def test_manager_and_employee_cannot_manage_budgets() -> None:
    org_id = create_org()

    manager_email = "budget-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied_manager = client.get("/api/v1/budgets", headers=manager_headers)
    assert denied_manager.status_code == 403

    employee_email = "budget-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-966")
    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied_employee = client.post(
        "/api/v1/budgets",
        headers=employee_headers,
        json={
            "name": "Should not work",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "lines": [{"account_code": "revenue", "amount_minor": 100_00}],
        },
    )
    assert denied_employee.status_code == 403
