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


def _admin_headers(org_id, email: str = "fixedasset-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> dict[str, str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    return headers


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
