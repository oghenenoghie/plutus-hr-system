from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "ops-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def test_final_settlement_processes_exit_payroll() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_id = create_employee(org_id, employee_number="EMP-EXIT")

    response = client.post(
        f"/api/v1/final-settlements/{employee_id}",
        headers=headers,
        json={
            "termination_date": "2026-06-30",
            "gratuity_minor": 100000,
            "leave_days_paid_out": 5,
            "leave_payout_minor": 50000,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["employee_id"] == str(employee_id)
    assert body["gratuity_minor"] == 100000

    listing = client.get(f"/api/v1/final-settlements/{employee_id}", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_statutory_liability_file_then_remit_flow() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="statutory-admin@example.com")
    create_employee(org_id, employee_number="EMP-STAT")

    create_and_lock_pay_run(headers)

    liabilities = client.get("/api/v1/statutory-liabilities", headers=headers)
    assert liabilities.status_code == 200
    assert liabilities.json(), "expected at least one statutory liability (e.g. pension/NHF)"
    liability = liabilities.json()[0]
    assert liability["status"] == "pending"

    filed = client.post(f"/api/v1/statutory-liabilities/{liability['id']}/file", headers=headers)
    assert filed.status_code == 200
    assert filed.json()["status"] == "filed"

    remitted = client.post(
        f"/api/v1/statutory-liabilities/{liability['id']}/remit",
        headers=headers,
        json={"reference": "REF-001"},
    )
    assert remitted.status_code == 200
    assert remitted.json()["status"] == "remitted"
    assert remitted.json()["remittance_reference"] == "REF-001"

    # Remitting an already-remitted liability is rejected, not silently a no-op.
    again = client.post(
        f"/api/v1/statutory-liabilities/{liability['id']}/remit", headers=headers, json={}
    )
    assert again.status_code == 400
