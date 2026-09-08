import uuid

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


def test_admin_can_create_an_employee() -> None:
    org_id = create_org()
    admin_email = "employees-admin1@example.com"
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=admin_email)
    tokens = login_with_mfa(account_id, admin_email, Role.ADMIN)

    response = client.post(
        "/api/v1/employees",
        headers=auth_headers(tokens["access_token"]),
        json={
            "employee_number": "EMP-100",
            "full_name": "Ada Okafor",
            "state_of_residence": "Lagos",
            "employment_type": "permanent",
            "date_of_joining": "2025-01-01",
            "basic_minor": 30000000,
            "housing_minor": 15000000,
            "transport_minor": 5000000,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["employee_number"] == "EMP-100"


def test_employee_role_cannot_create_an_employee() -> None:
    org_id = create_org()
    employee_account_email = "worker@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=employee_account_email)
    create_employee(org_id, account_id=account_id)
    tokens = login(employee_account_email)

    response = client.post(
        "/api/v1/employees",
        headers=auth_headers(tokens["access_token"]),
        json={
            "employee_number": "EMP-999",
            "full_name": "Someone Else",
            "state_of_residence": "Lagos",
            "employment_type": "permanent",
            "date_of_joining": "2025-01-01",
            "basic_minor": 1,
            "housing_minor": 1,
            "transport_minor": 1,
        },
    )
    assert response.status_code == 403


def test_employee_sees_own_record_via_me_but_not_via_list() -> None:
    org_id = create_org()
    email = "self-service@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    employee_id = create_employee(org_id, account_id=account_id, employee_number="EMP-200")
    tokens = login(email)
    headers = auth_headers(tokens["access_token"])

    me = client.get("/api/v1/employees/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == str(employee_id)

    listing = client.get("/api/v1/employees", headers=headers)
    assert listing.status_code == 403


def test_employee_with_no_linked_record_gets_403_on_me() -> None:
    org_id = create_org()
    email = "no-link@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    tokens = login(email)

    response = client.get("/api/v1/employees/me", headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 403


def test_manager_sees_only_direct_reports() -> None:
    org_id = create_org()
    manager_email = "manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-001")
    report_id = create_employee(org_id, employee_number="EMP-300", manager_id=manager_id)
    create_employee(org_id, employee_number="EMP-301")  # not a report

    tokens = login(manager_email)
    response = client.get("/api/v1/employees", headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 200
    ids = {e["id"] for e in response.json()}
    assert ids == {str(report_id)}


def test_admin_can_link_account_and_update_employee() -> None:
    org_id = create_org()
    admin_email = "employees-admin@example.com"
    admin_account_id = create_account_with_membership(org_id, Role.ADMIN, email=admin_email)
    tokens = login_with_mfa(admin_account_id, admin_email, Role.ADMIN)
    headers = auth_headers(tokens["access_token"])

    employee_id = create_employee(org_id, employee_number="EMP-400")
    worker_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email="worker2@example.com"
    )

    link = client.post(
        f"/api/v1/employees/{employee_id}/link-account",
        headers=headers,
        json={"account_id": str(worker_account_id)},
    )
    assert link.status_code == 200
    assert link.json()["account_id"] == str(worker_account_id)

    update = client.patch(
        f"/api/v1/employees/{employee_id}", headers=headers, json={"basic_minor": 500_000_00}
    )
    assert update.status_code == 200
    assert update.json()["basic_minor"] == 500_000_00


def _admin_headers(org_id: uuid.UUID, email: str) -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_get_bank_account_returns_null_when_none_set() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "bank-admin1@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-500")

    response = client.get(f"/api/v1/employees/{employee_id}/bank-account", headers=headers)
    assert response.status_code == 200
    assert response.json() is None


def test_admin_can_set_a_valid_bank_account_for_a_known_bank() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "bank-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-501")

    # First Bank (011), CBN's own published worked example.
    response = client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=headers,
        json={
            "bank_name": "First Bank of Nigeria",
            "account_number": "0000014579",
            "account_name": "Ada Okafor",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified"] is True

    get_response = client.get(f"/api/v1/employees/{employee_id}/bank-account", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["account_number"] == "0000014579"


def test_invalid_check_digit_for_a_known_bank_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "bank-admin3@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-502")

    response = client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=headers,
        json={
            "bank_name": "First Bank of Nigeria",
            "account_number": "0000014570",  # last digit mistyped
            "account_name": "Ada Okafor",
        },
    )
    assert response.status_code == 422


def test_unlisted_bank_skips_checksum_but_enforces_format() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "bank-admin4@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-503")

    ok = client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=headers,
        json={
            "bank_name": "Some Small Fintech Bank",
            "account_number": "1234567890",
            "account_name": "Ada Okafor",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["verified"] is False

    bad_format = client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=headers,
        json={
            "bank_name": "Some Small Fintech Bank",
            "account_number": "12345",
            "account_name": "Ada Okafor",
        },
    )
    assert bad_format.status_code == 422


def test_upsert_replaces_the_prior_bank_account_not_a_second_row() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "bank-admin5@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-504")

    client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=headers,
        json={
            "bank_name": "First Bank of Nigeria",
            "account_number": "0000014579",
            "account_name": "Ada Okafor",
        },
    )
    second = client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=headers,
        json={
            "bank_name": "Guaranty Trust Bank",
            "account_number": "0000014579",
            "account_name": "Ada Okafor",
        },
    )
    assert second.status_code == 422  # not a valid GTBank (058) checksum

    replaced = client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=headers,
        json={
            "bank_name": "Some Small Fintech Bank",
            "account_number": "1234567890",
            "account_name": "New Name",
        },
    )
    assert replaced.status_code == 200

    fetched = client.get(f"/api/v1/employees/{employee_id}/bank-account", headers=headers)
    assert fetched.json()["bank_name"] == "Some Small Fintech Bank"


def test_manager_sees_nulled_compensation_for_a_masked_report() -> None:
    org_id = create_org()
    admin_email = "mask-admin1@example.com"
    admin_account_id = create_account_with_membership(org_id, Role.ADMIN, email=admin_email)
    admin_headers = auth_headers(
        login_with_mfa(admin_account_id, admin_email, Role.ADMIN)["access_token"]
    )

    manager_email = "mask-manager1@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-500")
    report_id = create_employee(org_id, employee_number="EMP-600", manager_id=manager_id)

    masked = client.patch(
        f"/api/v1/employees/{report_id}", headers=admin_headers, json={"salary_masked": True}
    )
    assert masked.status_code == 200
    assert masked.json()["salary_masked"] is True
    # Admin's own view is never masked, regardless of the flag.
    assert masked.json()["basic_minor"] is not None

    manager_headers = auth_headers(login(manager_email)["access_token"])

    listing = client.get("/api/v1/employees", headers=manager_headers)
    assert listing.status_code == 200
    [report] = [e for e in listing.json() if e["id"] == str(report_id)]
    assert report["basic_minor"] is None
    assert report["housing_minor"] is None
    assert report["transport_minor"] is None
    assert report["other_earnings_minor"] is None
    assert report["annual_rent_paid_minor"] is None

    get_response = client.get(f"/api/v1/employees/{report_id}", headers=manager_headers)
    assert get_response.status_code == 200
    assert get_response.json()["basic_minor"] is None


def test_manager_sees_real_compensation_for_an_unmasked_report() -> None:
    org_id = create_org()
    manager_email = "mask-manager2@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-501")
    create_employee(org_id, employee_number="EMP-601", manager_id=manager_id)

    manager_headers = auth_headers(login(manager_email)["access_token"])
    listing = client.get("/api/v1/employees", headers=manager_headers)
    assert listing.status_code == 200
    assert listing.json()[0]["basic_minor"] is not None


def test_admin_and_payroll_manager_never_see_masked_compensation() -> None:
    org_id = create_org()
    admin_email = "mask-admin2@example.com"
    admin_account_id = create_account_with_membership(org_id, Role.ADMIN, email=admin_email)
    admin_headers = auth_headers(
        login_with_mfa(admin_account_id, admin_email, Role.ADMIN)["access_token"]
    )
    employee_id = create_employee(org_id, employee_number="EMP-602")

    client.patch(
        f"/api/v1/employees/{employee_id}", headers=admin_headers, json={"salary_masked": True}
    )

    get_response = client.get(f"/api/v1/employees/{employee_id}", headers=admin_headers)
    assert get_response.json()["basic_minor"] is not None

    listing = client.get("/api/v1/employees", headers=admin_headers)
    [record] = [e for e in listing.json() if e["id"] == str(employee_id)]
    assert record["basic_minor"] is not None


def test_employee_own_me_view_is_never_masked() -> None:
    org_id = create_org()
    admin_email = "mask-admin3@example.com"
    admin_account_id = create_account_with_membership(org_id, Role.ADMIN, email=admin_email)
    admin_headers = auth_headers(
        login_with_mfa(admin_account_id, admin_email, Role.ADMIN)["access_token"]
    )

    email = "mask-employee1@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    employee_id = create_employee(org_id, account_id=account_id, employee_number="EMP-603")
    client.patch(
        f"/api/v1/employees/{employee_id}", headers=admin_headers, json={"salary_masked": True}
    )

    tokens = login(email)
    me = client.get("/api/v1/employees/me", headers=auth_headers(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["basic_minor"] is not None


def test_manager_cannot_set_salary_masked_flag() -> None:
    org_id = create_org()
    manager_email = "mask-manager3@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-502")
    report_id = create_employee(org_id, employee_number="EMP-604", manager_id=manager_id)

    manager_headers = auth_headers(login(manager_email)["access_token"])
    response = client.patch(
        f"/api/v1/employees/{report_id}", headers=manager_headers, json={"salary_masked": True}
    )
    assert response.status_code == 403


def test_non_manage_role_cannot_set_bank_account() -> None:
    org_id = create_org()
    email = "bank-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    employee_id = create_employee(org_id, account_id=account_id, employee_number="EMP-505")
    tokens = login(email)

    response = client.put(
        f"/api/v1/employees/{employee_id}/bank-account",
        headers=auth_headers(tokens["access_token"]),
        json={
            "bank_name": "First Bank of Nigeria",
            "account_number": "0000014579",
            "account_name": "Ada Okafor",
        },
    )
    assert response.status_code == 403
