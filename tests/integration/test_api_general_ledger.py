from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "gl-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _seed_org_with_accounts(email: str) -> tuple[object, dict[str, str]]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    return org_id, headers


def test_unbalanced_journal_entry_is_rejected() -> None:
    _org_id, headers = _seed_org_with_accounts("gl-admin1@example.com")

    response = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "opening balance",
            "lines": [
                {"account_code": "cash", "debit_minor": 100_000},
                {"account_code": "payroll_expense_gross", "credit_minor": 50_000},
            ],
        },
    )
    assert response.status_code == 400
    assert "does not balance" in response.json()["detail"]


def test_journal_entry_with_unknown_account_is_rejected() -> None:
    _org_id, headers = _seed_org_with_accounts("gl-admin2@example.com")

    response = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "bad account",
            "lines": [
                {"account_code": "cash", "debit_minor": 10_000},
                {"account_code": "does_not_exist", "credit_minor": 10_000},
            ],
        },
    )
    assert response.status_code == 400
    assert "unknown account code" in response.json()["detail"]


def test_balanced_journal_entry_appears_in_entries_and_trial_balance() -> None:
    _org_id, headers = _seed_org_with_accounts("gl-admin3@example.com")

    posted = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "owner capital injection",
            "lines": [
                {"account_code": "cash", "debit_minor": 500_000},
                {"account_code": "net_pay_payable", "credit_minor": 500_000},
            ],
        },
    )
    assert posted.status_code == 201, posted.text
    lines = posted.json()
    assert len(lines) == 2
    assert {line["account_name"] for line in lines} == {"Cash", "Net Pay Payable"}
    journal_entry_id = lines[0]["journal_entry_id"]
    assert lines[1]["journal_entry_id"] == journal_entry_id

    entries = client.get(
        "/api/v1/general-ledger/entries", headers=headers, params={"account": "cash"}
    )
    assert entries.status_code == 200
    assert len(entries.json()) == 1
    assert entries.json()[0]["debit_minor"] == 500_000
    assert entries.json()[0]["account_name"] == "Cash"

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    assert trial_balance.status_code == 200
    by_account = {line["account"]: line for line in trial_balance.json()}
    assert by_account["cash"]["balance_minor"] == 500_000
    assert by_account["net_pay_payable"]["balance_minor"] == -500_000


def test_manager_cannot_view_general_ledger() -> None:
    org_id, _headers = _seed_org_with_accounts("gl-admin4@example.com")

    manager_email = "gl-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])

    denied = client.get("/api/v1/general-ledger/entries", headers=manager_headers)
    assert denied.status_code == 403
