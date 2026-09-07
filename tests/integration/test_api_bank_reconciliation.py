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


def _admin_headers(org_id, email: str = "bankrecon-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> dict[str, str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    return headers


def _create_bank_account(headers: dict[str, str], account_number: str = "0123456789") -> dict:
    response = client.post(
        "/api/v1/company-bank-accounts",
        headers=headers,
        json={
            "bank_name": "Zenith Bank",
            "account_number": account_number,
            "account_name": "Demo Co Operating Account",
            "chart_account_code": "cash",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post_journal_entry(
    headers: dict[str, str], *, cash_debit: int = 0, cash_credit: int = 0
) -> str:
    other_side = "credit_minor" if cash_debit else "debit_minor"
    amount = cash_debit or cash_credit
    posted = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "Test posting",
            "lines": [
                {"account_code": "cash", "debit_minor": cash_debit, "credit_minor": cash_credit},
                {"account_code": "revenue", other_side: amount},
            ],
        },
    )
    assert posted.status_code == 201, posted.text
    entries = posted.json()
    return next(entry["id"] for entry in entries if entry["account"] == "cash")


def test_register_bank_account_requires_asset_account() -> None:
    headers = _setup("bankrecon-admin1@example.com")
    response = client.post(
        "/api/v1/company-bank-accounts",
        headers=headers,
        json={
            "bank_name": "Zenith Bank",
            "account_number": "0123456789",
            "account_name": "Demo Co Operating Account",
            "chart_account_code": "paye_payable",
        },
    )
    assert response.status_code == 400
    assert "not a known asset account" in response.json()["detail"]


def test_create_bank_account_and_statement_line() -> None:
    headers = _setup("bankrecon-admin2@example.com")
    bank_account = _create_bank_account(headers)

    line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-01",
            "description": "Customer deposit",
            "amount_minor": 500_000_00,
        },
    )
    assert line.status_code == 201, line.text
    assert line.json()["matched_ledger_entry_id"] is None

    lines = client.get(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines", headers=headers
    )
    assert lines.status_code == 200
    assert len(lines.json()) == 1


def test_match_statement_line_to_ledger_entry() -> None:
    headers = _setup("bankrecon-admin3@example.com")
    bank_account = _create_bank_account(headers)
    entry_id = _post_journal_entry(headers, cash_debit=500_000_00)

    line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-01",
            "description": "Customer deposit",
            "amount_minor": 500_000_00,
        },
    ).json()

    matched = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": entry_id},
    )
    assert matched.status_code == 200, matched.text
    assert matched.json()["matched_ledger_entry_id"] == entry_id


def test_match_rejects_amount_mismatch() -> None:
    headers = _setup("bankrecon-admin4@example.com")
    bank_account = _create_bank_account(headers)
    entry_id = _post_journal_entry(headers, cash_debit=500_000_00)

    line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-01",
            "description": "Customer deposit",
            "amount_minor": 400_000_00,
        },
    ).json()

    mismatched = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": entry_id},
    )
    assert mismatched.status_code == 400
    assert "amount mismatch" in mismatched.json()["detail"]


def test_match_rejects_wrong_account() -> None:
    headers = _setup("bankrecon-admin5@example.com")
    bank_account = _create_bank_account(headers)
    posted = client.post(
        "/api/v1/general-ledger/journal-entries",
        headers=headers,
        json={
            "description": "Not a cash entry",
            "lines": [
                {"account_code": "accounts_receivable", "debit_minor": 500_000_00},
                {"account_code": "revenue", "credit_minor": 500_000_00},
            ],
        },
    )
    receivable_entry_id = next(
        entry["id"] for entry in posted.json() if entry["account"] == "accounts_receivable"
    )

    line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-01",
            "description": "Customer deposit",
            "amount_minor": 500_000_00,
        },
    ).json()

    wrong_account = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": receivable_entry_id},
    )
    assert wrong_account.status_code == 400
    assert "not this account's" in wrong_account.json()["detail"]


def test_match_rejects_already_matched_statement_line_and_ledger_entry() -> None:
    headers = _setup("bankrecon-admin6@example.com")
    bank_account = _create_bank_account(headers)
    entry_id = _post_journal_entry(headers, cash_debit=500_000_00)

    line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-01",
            "description": "Customer deposit",
            "amount_minor": 500_000_00,
        },
    ).json()
    client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": entry_id},
    )

    # Same line, already matched.
    already_matched = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": entry_id},
    )
    assert already_matched.status_code == 400
    assert "already matched" in already_matched.json()["detail"]

    # A different line, same ledger entry.
    other_line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-02",
            "description": "Duplicate attempt",
            "amount_minor": 500_000_00,
        },
    ).json()
    conflicting = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{other_line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": entry_id},
    )
    assert conflicting.status_code == 400
    assert "already matched to another statement line" in conflicting.json()["detail"]


def test_unmatch_line() -> None:
    headers = _setup("bankrecon-admin7@example.com")
    bank_account = _create_bank_account(headers)
    entry_id = _post_journal_entry(headers, cash_debit=500_000_00)

    line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-01",
            "description": "Customer deposit",
            "amount_minor": 500_000_00,
        },
    ).json()
    client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": entry_id},
    )

    unmatched = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{line['id']}/unmatch",
        headers=headers,
    )
    assert unmatched.status_code == 200, unmatched.text
    assert unmatched.json()["matched_ledger_entry_id"] is None


def test_reconciliation_summary_reports_unmatched_items_and_difference() -> None:
    headers = _setup("bankrecon-admin8@example.com")
    bank_account = _create_bank_account(headers)

    matched_entry_id = _post_journal_entry(headers, cash_debit=500_000_00)
    matched_line = client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-01",
            "description": "Matched deposit",
            "amount_minor": 500_000_00,
        },
    ).json()
    client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines/{matched_line['id']}/match",
        headers=headers,
        json={"ledger_entry_id": matched_entry_id},
    )

    # An unmatched ledger posting to cash (e.g. not yet on the statement).
    _post_journal_entry(headers, cash_debit=100_000_00)

    # An unmatched statement line (e.g. a bank fee not yet in the ledger).
    client.post(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/statement-lines",
        headers=headers,
        json={
            "statement_date": "2026-09-03",
            "description": "Bank charges",
            "amount_minor": -2_500_00,
        },
    )

    summary = client.get(
        f"/api/v1/company-bank-accounts/{bank_account['id']}/reconciliation", headers=headers
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["bank_balance_minor"] == 500_000_00 - 2_500_00
    assert body["ledger_balance_minor"] == 500_000_00 + 100_000_00
    assert body["difference_minor"] == body["bank_balance_minor"] - body["ledger_balance_minor"]
    assert len(body["unmatched_statement_lines"]) == 1
    assert body["unmatched_statement_lines"][0]["description"] == "Bank charges"
    assert len(body["unmatched_ledger_entries"]) == 1
    assert body["unmatched_ledger_entries"][0]["debit_minor"] == 100_000_00


def test_duplicate_account_number_is_rejected() -> None:
    headers = _setup("bankrecon-admin9@example.com")
    _create_bank_account(headers)
    duplicate = client.post(
        "/api/v1/company-bank-accounts",
        headers=headers,
        json={
            "bank_name": "GTBank",
            "account_number": "0123456789",
            "account_name": "Another Account",
            "chart_account_code": "cash",
        },
    )
    assert duplicate.status_code == 400


def test_manager_and_employee_cannot_manage_bank_reconciliation() -> None:
    org_id = create_org()

    manager_email = "bankrecon-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied_manager = client.get("/api/v1/company-bank-accounts", headers=manager_headers)
    assert denied_manager.status_code == 403

    employee_email = "bankrecon-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-967")
    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied_employee = client.post(
        "/api/v1/company-bank-accounts",
        headers=employee_headers,
        json={
            "bank_name": "Should not work",
            "account_number": "9999999999",
            "account_name": "Nope",
            "chart_account_code": "cash",
        },
    )
    assert denied_employee.status_code == 403
