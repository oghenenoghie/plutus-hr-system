import uuid

from app.core.db import tenant_session
from app.models import Role
from app.models.fixed_asset import FixedAsset
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "fixedasset-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> dict[str, str]:
    _org_id, headers = _setup_with_org(email)
    return headers


def _setup_with_org(email: str) -> tuple[uuid.UUID, dict[str, str]]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    return org_id, headers


def _create_asset(
    headers: dict[str, str],
    asset_tag: str = "FA-001",
    cost_minor: int = 200_000_00,
    useful_life_months: int = 2,
) -> dict:
    response = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Office Printer",
            "asset_tag": asset_tag,
            "acquisition_date": "2026-01-01",
            "cost_minor": cost_minor,
            "useful_life_months": useful_life_months,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_transfer_asset_between_departments() -> None:
    headers = _setup("fixedasset-admin10@example.com")
    asset = _create_asset(headers, asset_tag="FA-100")
    dept_a = client.post(
        "/api/v1/departments", headers=headers, json={"name": "Engineering"}
    ).json()["id"]
    dept_b = client.post("/api/v1/departments", headers=headers, json={"name": "Sales"}).json()[
        "id"
    ]

    first_transfer = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/transfer",
        headers=headers,
        json={"to_department_id": dept_a, "transfer_date": "2026-02-01"},
    )
    assert first_transfer.status_code == 200, first_transfer.text
    assert first_transfer.json()["department_id"] == dept_a

    second_transfer = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/transfer",
        headers=headers,
        json={"to_department_id": dept_b, "transfer_date": "2026-03-01", "note": "reassigned"},
    )
    assert second_transfer.status_code == 200
    assert second_transfer.json()["department_id"] == dept_b

    no_op = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/transfer",
        headers=headers,
        json={"to_department_id": dept_b, "transfer_date": "2026-03-02"},
    )
    assert no_op.status_code == 400


def test_revalue_asset_upward_posts_surplus_and_resets_depreciation() -> None:
    headers = _setup("fixedasset-admin11@example.com")
    asset = _create_asset(headers, asset_tag="FA-101", cost_minor=200_000_00, useful_life_months=2)
    client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)

    revalued = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/revalue",
        headers=headers,
        json={
            "new_value_minor": 150_000_00,
            "revaluation_date": "2026-02-01",
            "reason": "market appraisal",
        },
    )
    assert revalued.status_code == 200, revalued.text
    body = revalued.json()
    assert body["cost_minor"] == 150_000_00
    assert body["accumulated_depreciation_minor"] == 0
    assert body["book_value_minor"] == 150_000_00

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    by_account = {line["account"]: line for line in trial_balance.json()}
    # old book value was 100_000_00 (200_000_00 cost - 100_000_00 accumulated
    # depreciation after one month); revalued up to 150_000_00, a 50_000_00
    # surplus.
    assert by_account["revaluation_surplus"]["balance_minor"] == -50_000_00


def test_revalue_to_same_book_value_is_rejected() -> None:
    headers = _setup("fixedasset-admin12@example.com")
    asset = _create_asset(headers, asset_tag="FA-102", cost_minor=200_000_00, useful_life_months=2)

    same_value = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/revalue",
        headers=headers,
        json={
            "new_value_minor": 200_000_00,
            "revaluation_date": "2026-02-01",
            "reason": "no change",
        },
    )
    assert same_value.status_code == 400


def test_batch_depreciation_skips_fully_depreciated_assets() -> None:
    headers = _setup("fixedasset-admin13@example.com")
    active_asset = _create_asset(
        headers, asset_tag="FA-103", cost_minor=200_000_00, useful_life_months=2
    )
    fully_depreciated = _create_asset(
        headers, asset_tag="FA-104", cost_minor=100_000_00, useful_life_months=1
    )
    client.post(f"/api/v1/fixed-assets/{fully_depreciated['id']}/depreciate", headers=headers)

    batch = client.post("/api/v1/fixed-assets/batch-depreciation", headers=headers)
    assert batch.status_code == 200, batch.text
    depreciated_ids = {a["id"] for a in batch.json()}
    assert depreciated_ids == {active_asset["id"]}


def test_register_fixed_asset_posts_acquisition_to_ledger() -> None:
    headers = _setup("fixedasset-admin1@example.com")
    asset = _create_asset(headers)
    assert asset["accumulated_depreciation_minor"] == 0
    assert asset["book_value_minor"] == 200_000_00
    assert asset["status"] == "active"

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers).json()
    by_account = {line["account"]: line["balance_minor"] for line in trial_balance}
    assert by_account["fixed_assets"] == 200_000_00
    assert by_account["cash"] == -200_000_00


def test_depreciation_reduces_book_value_and_posts_expense() -> None:
    headers = _setup("fixedasset-admin2@example.com")
    asset = _create_asset(headers)

    depreciated = client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
    assert depreciated.status_code == 200, depreciated.text
    assert depreciated.json()["accumulated_depreciation_minor"] == 100_000_00
    assert depreciated.json()["book_value_minor"] == 100_000_00

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers).json()
    by_account = {line["account"]: line["balance_minor"] for line in trial_balance}
    assert by_account["depreciation_expense"] == 100_000_00
    assert by_account["accumulated_depreciation"] == -100_000_00


def test_cannot_depreciate_past_full_depreciation() -> None:
    headers = _setup("fixedasset-admin3@example.com")
    asset = _create_asset(headers)

    client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
    second = client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
    assert second.status_code == 200
    assert second.json()["accumulated_depreciation_minor"] == 200_000_00

    third = client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
    assert third.status_code == 400
    assert "fully depreciated" in third.json()["detail"]


def test_dispose_at_book_value_posts_no_gain_or_loss() -> None:
    headers = _setup("fixedasset-admin4@example.com")
    asset = _create_asset(headers)
    client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)

    disposed = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/dispose",
        headers=headers,
        json={"proceeds_minor": 100_000_00},
    )
    assert disposed.status_code == 200, disposed.text
    assert disposed.json()["status"] == "disposed"
    assert disposed.json()["disposed_at"] is not None

    income_statement = client.get(
        "/api/v1/financial-statements/income-statement", headers=headers
    ).json()
    expenses_by_account = {
        line["account"]: line["balance_minor"] for line in income_statement["expenses"]
    }
    assert expenses_by_account["disposal_gain_loss"] == 0

    # Fully disposed of: fixed_assets and accumulated_depreciation both cleared.
    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers).json()
    by_account = {line["account"]: line["balance_minor"] for line in trial_balance}
    assert by_account["fixed_assets"] == 0
    assert by_account["accumulated_depreciation"] == 0


def test_dispose_with_loss_posts_disposal_expense() -> None:
    headers = _setup("fixedasset-admin5@example.com")
    asset = _create_asset(headers)

    disposed = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/dispose",
        headers=headers,
        json={"proceeds_minor": 0},
    )
    assert disposed.status_code == 200, disposed.text

    income_statement = client.get(
        "/api/v1/financial-statements/income-statement", headers=headers
    ).json()
    expenses_by_account = {
        line["account"]: line["balance_minor"] for line in income_statement["expenses"]
    }
    assert expenses_by_account["disposal_gain_loss"] == 200_000_00


def test_disposed_asset_cannot_be_depreciated_or_disposed_again() -> None:
    headers = _setup("fixedasset-admin6@example.com")
    asset = _create_asset(headers)
    client.post(f"/api/v1/fixed-assets/{asset['id']}/dispose", headers=headers, json={})

    denied_depreciate = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers
    )
    assert denied_depreciate.status_code == 400

    denied_dispose = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/dispose", headers=headers, json={}
    )
    assert denied_dispose.status_code == 400


def test_duplicate_asset_tag_is_rejected() -> None:
    headers = _setup("fixedasset-admin7@example.com")
    _create_asset(headers)
    duplicate = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Another Printer",
            "asset_tag": "FA-001",
            "acquisition_date": "2026-01-01",
            "cost_minor": 50_000_00,
            "useful_life_months": 12,
        },
    )
    assert duplicate.status_code == 400


def test_laptop_requires_assignee_at_creation() -> None:
    org_id, headers = _setup_with_org("fixedasset-admin20@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-700")

    missing_assignee = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "MacBook Pro",
            "asset_tag": "FA-200",
            "acquisition_date": "2026-01-01",
            "cost_minor": 250_000_00,
            "useful_life_months": 36,
            "category": "laptop",
        },
    )
    assert missing_assignee.status_code == 400
    assert "must be assigned" in missing_assignee.json()["detail"]

    with_assignee = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "MacBook Pro",
            "asset_tag": "FA-200",
            "acquisition_date": "2026-01-01",
            "cost_minor": 250_000_00,
            "useful_life_months": 36,
            "category": "laptop",
            "assigned_employee_id": str(employee_id),
        },
    )
    assert with_assignee.status_code == 201, with_assignee.text
    body = with_assignee.json()
    assert body["category"] == "laptop"
    assert body["assignment_status"] == "assigned"
    assert body["assigned_employee_id"] == str(employee_id)


def test_furniture_does_not_require_assignee() -> None:
    headers = _setup("fixedasset-admin21@example.com")
    response = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Office Chair",
            "asset_tag": "FA-201",
            "acquisition_date": "2026-01-01",
            "cost_minor": 10_000_00,
            "useful_life_months": 36,
            "category": "furniture",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assignment_status"] == "available"
    assert body["assigned_employee_id"] is None


def test_assign_then_return_asset() -> None:
    org_id, headers = _setup_with_org("fixedasset-admin22@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-701")
    response = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Spare Phone",
            "asset_tag": "FA-203",
            "acquisition_date": "2026-01-01",
            "cost_minor": 50_000_00,
            "useful_life_months": 24,
            "category": "phone",
            "assigned_employee_id": str(employee_id),
        },
    )
    phone = response.json()
    assert phone["assignment_status"] == "assigned"

    double_assign = client.post(
        f"/api/v1/fixed-assets/{phone['id']}/assignments",
        headers=headers,
        json={"employee_id": str(employee_id), "assigned_date": "2026-02-01"},
    )
    assert double_assign.status_code == 400
    assert "not available" in double_assign.json()["detail"]

    assignments = client.get(f"/api/v1/fixed-assets/{phone['id']}/assignments", headers=headers)
    assert assignments.status_code == 200
    open_assignment = assignments.json()[0]
    assert open_assignment["returned_date"] is None

    returned = client.post(
        f"/api/v1/fixed-assets/assignments/{open_assignment['id']}/return",
        headers=headers,
        json={"returned_date": "2026-03-01", "condition_notes": "good condition"},
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["returned_date"] == "2026-03-01"

    refreshed = client.get(f"/api/v1/fixed-assets/{phone['id']}", headers=headers)
    assert refreshed.json()["assignment_status"] == "available"
    assert refreshed.json()["assigned_employee_id"] is None

    double_return = client.post(
        f"/api/v1/fixed-assets/assignments/{open_assignment['id']}/return",
        headers=headers,
        json={"returned_date": "2026-03-02"},
    )
    assert double_return.status_code == 400
    assert "already been returned" in double_return.json()["detail"]

    reassign = client.post(
        f"/api/v1/fixed-assets/{phone['id']}/assignments",
        headers=headers,
        json={"employee_id": str(employee_id), "assigned_date": "2026-03-05"},
    )
    assert reassign.status_code == 201, reassign.text
    assert (
        client.get(f"/api/v1/fixed-assets/{phone['id']}", headers=headers).json()[
            "assignment_status"
        ]
        == "assigned"
    )


def test_employee_sees_own_assigned_assets_via_me_endpoint() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="fixedasset-admin23@example.com")
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=admin_headers)
    assert seeded.status_code == 200, seeded.text

    employee_email = "fixedasset-employee-self@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-702")

    asset = client.post(
        "/api/v1/fixed-assets",
        headers=admin_headers,
        json={
            "name": "MacBook Air",
            "asset_tag": "FA-204",
            "acquisition_date": "2026-01-01",
            "cost_minor": 200_000_00,
            "useful_life_months": 36,
            "category": "laptop",
            "assigned_employee_id": str(employee_id),
        },
    ).json()

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/fixed-assets/me", headers=employee_headers)
    assert mine.status_code == 200, mine.text
    assert len(mine.json()) == 1
    entry = mine.json()[0]
    assert entry["fixed_asset_id"] == asset["id"]
    assert entry["asset_tag"] == "FA-204"
    assert entry["category"] == "laptop"
    assert "cost_minor" not in entry

    denied = client.get("/api/v1/fixed-assets", headers=employee_headers)
    assert denied.status_code == 403


def test_disposal_auto_returns_open_assignment() -> None:
    org_id, headers = _setup_with_org("fixedasset-admin24@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-703")
    asset = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Company Car",
            "asset_tag": "FA-205",
            "acquisition_date": "2026-01-01",
            "cost_minor": 5_000_000_00,
            "useful_life_months": 60,
            "category": "vehicle",
            "assigned_employee_id": str(employee_id),
        },
    ).json()

    disposed = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/dispose",
        headers=headers,
        json={"proceeds_minor": 0},
    )
    assert disposed.status_code == 200, disposed.text
    body = disposed.json()
    assert body["assignment_status"] is None
    assert body["assigned_employee_id"] is None

    assignments = client.get(f"/api/v1/fixed-assets/{asset['id']}/assignments", headers=headers)
    assert assignments.status_code == 200
    assert assignments.json()[0]["returned_date"] is not None


def test_manager_and_employee_cannot_manage_fixed_assets() -> None:
    org_id = create_org()

    manager_email = "fixedasset-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied_manager = client.get("/api/v1/fixed-assets", headers=manager_headers)
    assert denied_manager.status_code == 403

    employee_email = "fixedasset-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-965")
    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied_employee = client.post(
        "/api/v1/fixed-assets",
        headers=employee_headers,
        json={
            "name": "Should not work",
            "asset_tag": "FA-999",
            "acquisition_date": "2026-01-01",
            "cost_minor": 10_000_00,
            "useful_life_months": 12,
        },
    )
    assert denied_employee.status_code == 403


def _create_owned_asset(
    headers: dict[str, str],
    *,
    asset_tag: str,
    cost_minor: int,
    useful_life_months: int,
    opening_accumulated_depreciation_minor: int,
    salvage_value_minor: int = 0,
    opening_balance: bool = True,
):
    return client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Delivery Van",
            "asset_tag": asset_tag,
            "acquisition_date": "2023-01-01",
            "cost_minor": cost_minor,
            "salvage_value_minor": salvage_value_minor,
            "useful_life_months": useful_life_months,
            "opening_balance": opening_balance,
            "opening_accumulated_depreciation_minor": opening_accumulated_depreciation_minor,
        },
    )


def _balances(headers: dict[str, str]) -> dict[str, int]:
    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers).json()
    return {line["account"]: line["balance_minor"] for line in trial_balance}


def _history(headers: dict[str, str], asset_id: str) -> dict:
    response = client.get(f"/api/v1/fixed-assets/{asset_id}/depreciation-history", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_asset_already_owned_comes_on_as_an_opening_balance() -> None:
    headers = _setup("fixedasset-admin30@example.com")
    created = _create_owned_asset(
        headers,
        asset_tag="FA-300",
        cost_minor=120_000_00,
        useful_life_months=12,
        opening_accumulated_depreciation_minor=30_000_00,
    )
    assert created.status_code == 201, created.text
    asset = created.json()
    assert asset["accumulated_depreciation_minor"] == 30_000_00
    assert asset["book_value_minor"] == 90_000_00

    # Paid for before Plutus: no cash moves; the book value is equity.
    balances = _balances(headers)
    assert balances["fixed_assets"] == 120_000_00
    assert balances["accumulated_depreciation"] == -30_000_00
    assert balances["opening_balance_equity"] == -90_000_00
    assert balances.get("cash", 0) == 0

    sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers).json()
    assets = {line["account"]: line["balance_minor"] for line in sheet["assets"]}
    equity = {line["account"]: line["balance_minor"] for line in sheet["equity"]}
    assert assets["fixed_assets"] == 120_000_00
    assert assets["accumulated_depreciation"] == -30_000_00
    assert equity["opening_balance_equity"] == 90_000_00

    # Depreciation carries on from what was built up, at cost / life a month.
    depreciated = client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
    assert depreciated.status_code == 200, depreciated.text
    assert depreciated.json()["accumulated_depreciation_minor"] == 40_000_00
    assert _balances(headers)["accumulated_depreciation"] == -40_000_00

    history = _history(headers, asset["id"])
    assert [(e["kind"], e["amount_minor"], e["accumulated_minor"]) for e in history["events"]] == [
        ("opening", 30_000_00, 30_000_00),
        ("depreciation", 10_000_00, 40_000_00),
    ]
    assert all(e["journal_entry_id"] for e in history["events"])
    assert history["accumulated_depreciation_minor"] == 40_000_00
    assert history["unexplained_minor"] == 0


def test_fully_depreciated_asset_already_owned_carries_no_equity() -> None:
    headers = _setup("fixedasset-admin31@example.com")
    created = _create_owned_asset(
        headers,
        asset_tag="FA-310",
        cost_minor=50_000_00,
        useful_life_months=24,
        opening_accumulated_depreciation_minor=50_000_00,
    )
    assert created.status_code == 201, created.text
    assert created.json()["book_value_minor"] == 0

    balances = _balances(headers)
    assert balances["fixed_assets"] == 50_000_00
    assert balances["accumulated_depreciation"] == -50_000_00
    assert balances.get("opening_balance_equity", 0) == 0

    again = client.post(f"/api/v1/fixed-assets/{created.json()['id']}/depreciate", headers=headers)
    assert again.status_code == 400
    assert "fully depreciated" in again.json()["detail"]


def test_asset_already_owned_without_depreciation_is_all_equity() -> None:
    headers = _setup("fixedasset-admin32@example.com")
    created = _create_owned_asset(
        headers,
        asset_tag="FA-320",
        cost_minor=40_000_00,
        useful_life_months=10,
        opening_accumulated_depreciation_minor=0,
    )
    assert created.status_code == 201, created.text
    balances = _balances(headers)
    assert balances["fixed_assets"] == 40_000_00
    assert balances.get("accumulated_depreciation", 0) == 0
    assert balances["opening_balance_equity"] == -40_000_00
    assert balances.get("cash", 0) == 0
    assert _history(headers, created.json()["id"])["events"] == []


def test_opening_accumulated_depreciation_is_validated() -> None:
    headers = _setup("fixedasset-admin33@example.com")

    bought_now = _create_owned_asset(
        headers,
        asset_tag="FA-330",
        cost_minor=100_000_00,
        useful_life_months=12,
        opening_accumulated_depreciation_minor=10_000_00,
        opening_balance=False,
    )
    assert bought_now.status_code == 400
    assert "already owned" in bought_now.json()["detail"]

    beyond_salvage = _create_owned_asset(
        headers,
        asset_tag="FA-331",
        cost_minor=100_000_00,
        salvage_value_minor=10_000_00,
        useful_life_months=12,
        opening_accumulated_depreciation_minor=95_000_00,
    )
    assert beyond_salvage.status_code == 400
    assert "cost less salvage" in beyond_salvage.json()["detail"]

    negative = _create_owned_asset(
        headers,
        asset_tag="FA-332",
        cost_minor=100_000_00,
        useful_life_months=12,
        opening_accumulated_depreciation_minor=-1,
    )
    assert negative.status_code == 400

    # Nothing was registered or posted by the rejected requests.
    assert client.get("/api/v1/fixed-assets", headers=headers).json() == []
    assert _balances(headers).get("fixed_assets", 0) == 0


def test_depreciation_history_lists_postings_and_revaluation_resets() -> None:
    headers = _setup("fixedasset-admin34@example.com")
    asset = _create_asset(headers, asset_tag="FA-340", cost_minor=300_000_00, useful_life_months=3)
    for _ in range(2):
        assert (
            client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
        ).status_code == 200
    revalued = client.post(
        f"/api/v1/fixed-assets/{asset['id']}/revalue",
        headers=headers,
        json={
            "new_value_minor": 150_000_00,
            "revaluation_date": "2026-03-01",
            "reason": "market appraisal",
        },
    )
    assert revalued.status_code == 200, revalued.text
    after = client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers)
    assert after.status_code == 200, after.text
    assert after.json()["accumulated_depreciation_minor"] == 50_000_00

    history = _history(headers, asset["id"])
    assert [(e["kind"], e["amount_minor"], e["accumulated_minor"]) for e in history["events"]] == [
        ("depreciation", 100_000_00, 100_000_00),
        ("depreciation", 100_000_00, 200_000_00),
        ("revaluation", -200_000_00, 0),
        ("depreciation", 50_000_00, 50_000_00),
    ]
    assert history["events"][2]["date"] == "2026-03-01"
    assert history["events"][2]["description"] == "Revalued: market appraisal"
    assert history["events"][2]["journal_entry_id"] is None
    assert history["accumulated_depreciation_minor"] == 50_000_00
    assert history["unexplained_minor"] == 0

    # Each period's journal is linked to the asset, and they're distinct.
    journal_ids = [e["journal_entry_id"] for e in history["events"] if e["kind"] == "depreciation"]
    assert len(set(journal_ids)) == 3
    journal = client.get(f"/api/v1/general-ledger/journals/{journal_ids[0]}", headers=headers)
    assert journal.status_code == 200, journal.text
    assert journal.json()["source_type"] == "fixed_asset"
    assert journal.json()["source_id"] == asset["id"]
    assert journal.json()["source_event"] == "asset.depreciated:1"
    assert journal.json()["description"] == "Depreciation for FA-340"


def test_depreciation_history_includes_postings_from_before_journals_were_linked() -> None:
    org_id, headers = _setup_with_org("fixedasset-admin35@example.com")
    asset = _create_asset(headers, asset_tag="FA-350", cost_minor=120_000_00, useful_life_months=12)
    # Depreciation as it was posted before journals carried their asset:
    # an unlinked manual journal whose lines say "Depreciation for <tag>",
    # plus the asset's own running total.
    legacy = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "Depreciation for FA-350",
            "lines": [
                {"account_code": "depreciation_expense", "debit_minor": 10_000_00},
                {"account_code": "accumulated_depreciation", "credit_minor": 10_000_00},
            ],
        },
    )
    assert legacy.status_code == 201, legacy.text
    # A different asset's tag that merely starts the same is not matched.
    other = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "Depreciation for FA-3500",
            "lines": [
                {"account_code": "depreciation_expense", "debit_minor": 7_00},
                {"account_code": "accumulated_depreciation", "credit_minor": 7_00},
            ],
        },
    )
    assert other.status_code == 201, other.text
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        stored = db.get(FixedAsset, uuid.UUID(asset["id"]))
        # Plus 5_000_00 no posting explains, e.g. an asset migrated in.
        stored.accumulated_depreciation_minor = 15_000_00

    assert (
        client.post(f"/api/v1/fixed-assets/{asset['id']}/depreciate", headers=headers).json()[
            "accumulated_depreciation_minor"
        ]
        == 25_000_00
    )

    history = _history(headers, asset["id"])
    assert [(e["kind"], e["amount_minor"], e["accumulated_minor"]) for e in history["events"]] == [
        ("depreciation", 10_000_00, 10_000_00),
        ("depreciation", 10_000_00, 20_000_00),
    ]
    assert history["events"][0]["journal_entry_id"] == legacy.json()[0]["journal_entry_id"]
    assert history["unexplained_minor"] == 5_000_00


def test_depreciation_history_of_unknown_asset_is_404() -> None:
    headers = _setup("fixedasset-admin36@example.com")
    missing = client.get(
        f"/api/v1/fixed-assets/{uuid.uuid4()}/depreciation-history", headers=headers
    )
    assert missing.status_code == 404


def _statements(headers: dict[str, str]) -> tuple[dict, dict]:
    sheet = client.get("/api/v1/financial-statements/balance-sheet", headers=headers).json()
    profit = client.get("/api/v1/financial-statements/income-statement", headers=headers).json()
    return sheet, profit


def test_year_end_run_applies_each_assets_method_once_a_year() -> None:
    headers = _setup("fixedasset-yearend@example.com")
    category = client.post(
        "/api/v1/fixed-assets/categories",
        headers=headers,
        json={
            "name": "Motor Vehicles",
            "depreciation_method": "reducing_balance",
            "depreciation_rate_ppm": 250_000,
        },
    )
    assert category.status_code == 201, category.text
    listed = client.get("/api/v1/fixed-assets/categories", headers=headers).json()
    assert [entry["name"] for entry in listed] == ["Motor Vehicles"]
    duplicate = client.post(
        "/api/v1/fixed-assets/categories",
        headers=headers,
        json={"name": "Motor Vehicles", "depreciation_method": "straight_line"},
    )
    assert duplicate.status_code == 400

    def create(tag: str, **extra: object) -> dict:
        body = {
            "name": tag,
            "asset_tag": tag,
            "acquisition_date": "2025-01-01",
            "cost_minor": 1_000_000_00,
            "useful_life_months": 60,
            **extra,
        }
        response = client.post("/api/v1/fixed-assets", headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    car = create(
        "CAR-1",
        depreciation_method="reducing_balance",
        depreciation_rate_ppm=250_000,
        asset_category_id=category.json()["id"],
    )
    assert car["depreciation_method"] == "reducing_balance"
    assert car["asset_category_id"] == category.json()["id"]
    create("DESK-1")  # straight line over 5 years
    create("LAPTOP-1", depreciation_method="write_off", acquisition_date="2025-06-01")
    create("PRINTER-1", acquisition_date="2025-10-01", depreciation_rate_ppm=200_000)
    no_rate = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Van",
            "asset_tag": "VAN-1",
            "acquisition_date": "2025-01-01",
            "cost_minor": 1_000_000_00,
            "useful_life_months": 60,
            "depreciation_method": "reducing_balance",
        },
    )
    assert no_rate.status_code == 400
    assert "needs a depreciation rate" in no_rate.json()["detail"]

    first = client.post(
        "/api/v1/fixed-assets/year-end-depreciation", headers=headers, json={"year": 2025}
    )
    assert first.status_code == 200, first.text
    charges = {line["asset_tag"]: line["charge_minor"] for line in first.json()["charged"]}
    assert charges == {
        "CAR-1": 250_000_00,  # 25% of 1,000,000
        "DESK-1": 200_000_00,  # 1,000,000 over 5 years
        "LAPTOP-1": 1_000_000_00,  # written off at once
        "PRINTER-1": 50_000_00,  # 20% a year for October to December
    }
    assert first.json()["total_minor"] == 1_500_000_00

    again = client.post(
        "/api/v1/fixed-assets/year-end-depreciation", headers=headers, json={"year": 2025}
    )
    assert again.json()["charged"] == []
    assert sorted(again.json()["already_run"]) == ["CAR-1", "DESK-1", "LAPTOP-1", "PRINTER-1"]

    second = client.post(
        "/api/v1/fixed-assets/year-end-depreciation", headers=headers, json={"year": 2026}
    )
    charges = {line["asset_tag"]: line["charge_minor"] for line in second.json()["charged"]}
    # Reducing balance: 25% of the 750,000 left. The laptop has nothing left.
    assert charges == {"CAR-1": 187_500_00, "DESK-1": 200_000_00, "PRINTER-1": 200_000_00}

    sheet, profit = _statements(headers)
    depreciation = next(
        line for line in profit["overheads"]["lines"] if line["account"] == "depreciation_expense"
    )
    assert depreciation["balance_minor"] == 1_500_000_00 + 587_500_00
    accumulated = next(
        line
        for line in sheet["non_current_assets"]["lines"]
        if line["account"] == "accumulated_depreciation"
    )
    assert accumulated["balance_minor"] == -(1_500_000_00 + 587_500_00)
    assert sheet["balanced"] is True


def test_a_leased_asset_is_a_right_of_use_asset_amortised_over_the_lease() -> None:
    headers = _setup("fixedasset-lease@example.com")
    no_term = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Office lease",
            "asset_tag": "LEASE-0",
            "acquisition_date": "2026-01-01",
            "cost_minor": 2_400_000_00,
            "useful_life_months": 24,
            "acquisition_type": "leased",
        },
    )
    assert no_term.status_code == 400
    assert "lease term" in no_term.json()["detail"]

    lease = client.post(
        "/api/v1/fixed-assets",
        headers=headers,
        json={
            "name": "Office lease",
            "asset_tag": "LEASE-1",
            "acquisition_date": "2026-01-01",
            "cost_minor": 2_400_000_00,
            "useful_life_months": 24,
            "acquisition_type": "leased",
            "lease_term_months": 24,
        },
    )
    assert lease.status_code == 201, lease.text
    assert lease.json()["acquisition_type"] == "leased"

    sheet, _ = _statements(headers)
    by_account = {line["account"]: line for line in sheet["non_current_assets"]["lines"]}
    assert by_account["right_of_use_assets"]["balance_minor"] == 2_400_000_00
    assert by_account["right_of_use_assets"]["account_number"] == "1600"
    liabilities = {line["account"]: line for line in sheet["non_current_liabilities"]["lines"]}
    assert liabilities["lease_liability"]["balance_minor"] == 2_400_000_00

    run = client.post(
        "/api/v1/fixed-assets/year-end-depreciation", headers=headers, json={"year": 2026}
    )
    assert run.json()["charged"][0]["charge_minor"] == 1_200_000_00
    paid = client.post(
        f"/api/v1/fixed-assets/{lease.json()['id']}/lease-payment",
        headers=headers,
        json={"amount_minor": 600_000_00, "payment_date": "2026-06-30"},
    )
    assert paid.status_code == 204, paid.text

    sheet, profit = _statements(headers)
    by_account = {line["account"]: line for line in sheet["non_current_assets"]["lines"]}
    assert by_account["accumulated_amortisation"]["balance_minor"] == -1_200_000_00
    liabilities = {line["account"]: line for line in sheet["non_current_liabilities"]["lines"]}
    assert liabilities["lease_liability"]["balance_minor"] == 1_800_000_00
    amortisation = next(
        line for line in profit["overheads"]["lines"] if line["account"] == "amortisation_expense"
    )
    assert amortisation["balance_minor"] == 1_200_000_00
    assert sheet["balanced"] is True

    history = client.get(
        f"/api/v1/fixed-assets/{lease.json()['id']}/depreciation-history", headers=headers
    ).json()
    assert history["accumulated_depreciation_minor"] == 1_200_000_00
    assert history["unexplained_minor"] == 0
    revalue = client.post(
        f"/api/v1/fixed-assets/{lease.json()['id']}/revalue",
        headers=headers,
        json={"new_value_minor": 1, "revaluation_date": "2026-12-31", "reason": "x"},
    )
    assert revalue.status_code == 400
