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


def _admin_headers(org_id, email: str = "customer-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_create_list_and_update_customer() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    created = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "Zenith Retail Ltd", "contact_email": "ap@zenithretail.example"},
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]

    listed = client.get("/api/v1/customers", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.patch(
        f"/api/v1/customers/{customer_id}", headers=headers, json={"tin": "11122233-0001"}
    )
    assert updated.status_code == 200
    assert updated.json()["tin"] == "11122233-0001"


def test_duplicate_customer_name_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="customer-admin2@example.com")

    client.post("/api/v1/customers", headers=headers, json={"name": "Repeat Customer"})
    duplicate = client.post("/api/v1/customers", headers=headers, json={"name": "Repeat Customer"})
    assert duplicate.status_code == 400


def test_manager_and_employee_cannot_manage_customers() -> None:
    org_id = create_org()

    manager_email = "customer-manager@example.com"
    create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_headers = auth_headers(login(manager_email)["access_token"])
    denied_manager = client.get("/api/v1/customers", headers=manager_headers)
    assert denied_manager.status_code == 403

    employee_email = "customer-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-963")
    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied_employee = client.post(
        "/api/v1/customers", headers=employee_headers, json={"name": "Should not work"}
    )
    assert denied_employee.status_code == 403
