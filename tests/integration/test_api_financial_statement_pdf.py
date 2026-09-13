from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "finpdf-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_download_balance_sheet_pdf() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)

    response = client.get("/api/v1/financial-statements/balance-sheet/pdf", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_email_balance_sheet_requires_a_recipient() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finpdf-admin2@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)

    missing = client.post(
        "/api/v1/financial-statements/balance-sheet/email", headers=headers, json={}
    )
    assert missing.status_code == 422

    sent = client.post(
        "/api/v1/financial-statements/balance-sheet/email",
        headers=headers,
        json={"to": "finance@example.com"},
    )
    # RESEND_API_KEY is unset in tests, so delivery itself fails — this
    # proves the request otherwise succeeded (recipient accepted, PDF built).
    assert sent.status_code == 502


def test_download_income_statement_pdf() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finpdf-admin3@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)

    response = client.get("/api/v1/financial-statements/income-statement/pdf", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_email_income_statement_requires_a_recipient() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="finpdf-admin4@example.com")
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)

    missing = client.post(
        "/api/v1/financial-statements/income-statement/email", headers=headers, json={}
    )
    assert missing.status_code == 422

    sent = client.post(
        "/api/v1/financial-statements/income-statement/email",
        headers=headers,
        json={"to": "finance@example.com"},
    )
    assert sent.status_code == 502


def test_manager_cannot_view_or_download_financial_statement_pdfs() -> None:
    org_id = create_org()
    create_account_with_membership(org_id, Role.MANAGER, email="finpdf-manager@example.com")
    manager_headers = auth_headers(login("finpdf-manager@example.com")["access_token"])

    balance_sheet_response = client.get(
        "/api/v1/financial-statements/balance-sheet/pdf", headers=manager_headers
    )
    assert balance_sheet_response.status_code == 403
    income_statement_response = client.get(
        "/api/v1/financial-statements/income-statement/pdf", headers=manager_headers
    )
    assert income_statement_response.status_code == 403
