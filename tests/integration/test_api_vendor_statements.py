from typing import Any

from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "statement-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _create_bill(
    headers: dict[str, str], vendor_id: str, bill_number: str, bill_date: str
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": bill_number,
            "bill_date": bill_date,
            "due_date": "2026-12-31",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_vendor_statement_tracks_running_balance_across_bill_states() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    vendor_id = client.post(
        "/api/v1/vendors", headers=headers, json={"name": "Statement Vendor"}
    ).json()["id"]

    bill_one = _create_bill(headers, vendor_id, "STMT-1", "2026-01-01")
    client.post(f"/api/v1/bills/{bill_one['id']}/approve", headers=headers)

    bill_two = _create_bill(headers, vendor_id, "STMT-2", "2026-01-05")
    client.post(f"/api/v1/bills/{bill_two['id']}/approve", headers=headers)
    client.post(f"/api/v1/bills/{bill_two['id']}/pay", headers=headers)

    _create_bill(headers, vendor_id, "STMT-3", "2026-01-10")  # left in draft

    statement = client.get(f"/api/v1/reports/vendors/{vendor_id}/statement", headers=headers)
    assert statement.status_code == 200, statement.text
    lines = statement.json()
    assert [line["bill_number"] for line in lines] == ["STMT-1", "STMT-2", "STMT-3"]

    assert lines[0]["status"] == "approved"
    assert lines[0]["running_balance_minor"] == 100_000_00

    assert lines[1]["status"] == "paid"
    # bill_two settled, so it drops back out of the running balance.
    assert lines[1]["running_balance_minor"] == 100_000_00

    assert lines[2]["status"] == "draft"
    # never posted, so it never contributes to the balance.
    assert lines[2]["running_balance_minor"] == 100_000_00
