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


def _admin_headers(org_id, email: str = "docs-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_admin_uploads_document_and_employee_sees_it_via_me() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    employee_email = "docs-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-900")

    created = client.post(
        f"/api/v1/employees/{employee_id}/documents",
        headers=headers,
        json={
            "category": "contract",
            "title": "Employment Contract",
            "storage_url": "https://files.example.com/contracts/emp-900.pdf",
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]

    listed = client.get(f"/api/v1/employees/{employee_id}/documents", headers=headers)
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()] == [document_id]

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/employees/documents/me", headers=employee_headers)
    assert mine.status_code == 200
    assert [d["id"] for d in mine.json()] == [document_id]


def test_admin_updates_document_metadata() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docs-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-901")

    document_id = client.post(
        f"/api/v1/employees/{employee_id}/documents",
        headers=headers,
        json={
            "category": "identification",
            "title": "National ID",
            "storage_url": "https://files.example.com/ids/emp-901.pdf",
        },
    ).json()["id"]

    updated = client.patch(
        f"/api/v1/employees/documents/{document_id}",
        headers=headers,
        json={"expiry_date": "2030-01-01"},
    )
    assert updated.status_code == 200
    assert updated.json()["expiry_date"] == "2030-01-01"
    assert updated.json()["title"] == "National ID"


def test_employee_cannot_manage_documents() -> None:
    org_id = create_org()
    email = "docs-worker@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    employee_id = create_employee(org_id, account_id=account_id, employee_number="EMP-902")
    headers = auth_headers(login(email)["access_token"])

    denied_create = client.post(
        f"/api/v1/employees/{employee_id}/documents",
        headers=headers,
        json={
            "category": "other",
            "title": "Random",
            "storage_url": "https://files.example.com/x.pdf",
        },
    )
    assert denied_create.status_code == 403

    denied_list = client.get(f"/api/v1/employees/{employee_id}/documents", headers=headers)
    assert denied_list.status_code == 403
