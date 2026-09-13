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


def _admin_headers(org_id, email: str = "docgen-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_generate_send_and_sign_an_offer_letter() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    employee_email = "docgen-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-3000"
    )

    template = client.post(
        "/api/v1/document-templates",
        headers=headers,
        json={
            "document_type": "offer_letter",
            "name": "Standard Offer Letter",
            "body_template": (
                "Dear {{full_name}},\n\n"
                "We are pleased to offer you the position of {{job_title}} at "
                "{{org_name}}, starting {{start_date}}."
            ),
        },
    )
    assert template.status_code == 201, template.text
    template_id = template.json()["id"]

    generated = client.post(
        f"/api/v1/employees/{employee_id}/generated-documents",
        headers=headers,
        json={"template_id": template_id, "extra_context": {"start_date": "2026-03-01"}},
    )
    assert generated.status_code == 201, generated.text
    document = generated.json()
    assert document["status"] == "draft"
    assert "starting 2026-03-01" in document["rendered_content"]
    document_id = document["id"]

    sent = client.post(f"/api/v1/generated-documents/{document_id}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent_for_signature"

    employee_headers = auth_headers(login(employee_email)["access_token"])

    my_documents = client.get("/api/v1/generated-documents/me", headers=employee_headers)
    assert my_documents.status_code == 200
    assert len(my_documents.json()) == 1

    signed = client.post(
        f"/api/v1/generated-documents/{document_id}/sign",
        headers=employee_headers,
        json={"signed_by_name": "Ada Okafor"},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed"
    assert signed.json()["signed_by_name"] == "Ada Okafor"

    pdf = client.get(f"/api/v1/generated-documents/{document_id}/pdf", headers=employee_headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_cannot_sign_before_being_sent_for_signature() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docgen-admin2@example.com")

    employee_email = "docgen-employee2@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-3001"
    )

    template_id = client.post(
        "/api/v1/document-templates",
        headers=headers,
        json={
            "document_type": "salary_certificate",
            "name": "Salary Certificate",
            "body_template": "{{full_name}} earns a salary.",
        },
    ).json()["id"]

    document_id = client.post(
        f"/api/v1/employees/{employee_id}/generated-documents",
        headers=headers,
        json={"template_id": template_id},
    ).json()["id"]

    employee_headers = auth_headers(login(employee_email)["access_token"])
    denied = client.post(
        f"/api/v1/generated-documents/{document_id}/sign",
        headers=employee_headers,
        json={"signed_by_name": "Someone"},
    )
    assert denied.status_code == 400


def test_employee_cannot_sign_another_employees_document() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="docgen-admin3@example.com")

    owner_email = "docgen-owner@example.com"
    owner_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=owner_email)
    owner_id = create_employee(org_id, account_id=owner_account_id, employee_number="EMP-3002")

    other_email = "docgen-other@example.com"
    other_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=other_email)
    create_employee(org_id, account_id=other_account_id, employee_number="EMP-3003")

    template_id = client.post(
        "/api/v1/document-templates",
        headers=headers,
        json={
            "document_type": "confirmation_letter",
            "name": "Confirmation Letter",
            "body_template": "Congratulations {{full_name}}.",
        },
    ).json()["id"]

    document_id = client.post(
        f"/api/v1/employees/{owner_id}/generated-documents",
        headers=headers,
        json={"template_id": template_id},
    ).json()["id"]
    client.post(f"/api/v1/generated-documents/{document_id}/send", headers=headers)

    other_headers = auth_headers(login(other_email)["access_token"])
    denied = client.post(
        f"/api/v1/generated-documents/{document_id}/sign",
        headers=other_headers,
        json={"signed_by_name": "Impostor"},
    )
    assert denied.status_code == 403
