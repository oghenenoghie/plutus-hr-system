from app.models import LiabilityScheme, Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "wht-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def test_wht_resolved_by_category_not_a_flat_rate() -> None:
    # Same figures as tests/golden/test_schemes.py's
    # test_wht_resolved_by_category_not_a_flat_rate, exercised end to end
    # through the API: goods 5%, services 10%.
    org_id = create_org()
    headers = _admin_headers(org_id)

    contractor = client.post(
        "/api/v1/contractors",
        headers=headers,
        json={"name": "Acme Supplies Ltd", "tin": "98765432-0001"},
    )
    assert contractor.status_code == 201, contractor.text
    contractor_id = contractor.json()["id"]

    goods = client.post(
        f"/api/v1/contractors/{contractor_id}/payments",
        headers=headers,
        json={
            "category": "goods",
            "gross_amount_minor": 100_000_000,
            "payment_date": "2026-01-15",
        },
    )
    assert goods.status_code == 201, goods.text
    goods_body = goods.json()
    assert goods_body["wht_amount_minor"] == 5_000_000
    assert goods_body["net_amount_minor"] == 95_000_000
    assert goods_body["due_date"] == "2026-02-21"
    assert goods_body["certificate_number"] == f"WHT-{goods_body['id']}"

    services = client.post(
        f"/api/v1/contractors/{contractor_id}/payments",
        headers=headers,
        json={
            "category": "services",
            "gross_amount_minor": 100_000_000,
            "payment_date": "2026-01-15",
        },
    )
    assert services.status_code == 201, services.text
    services_body = services.json()
    assert services_body["wht_amount_minor"] == 10_000_000
    assert services_body["net_amount_minor"] == 90_000_000
    assert services_body["certificate_number"] != goods_body["certificate_number"]

    payments = client.get(f"/api/v1/contractors/{contractor_id}/payments", headers=headers)
    assert payments.status_code == 200
    assert len(payments.json()) == 2


def test_payment_blocked_without_contractor_tin() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="wht-admin2@example.com")

    contractor = client.post(
        "/api/v1/contractors", headers=headers, json={"name": "No TIN Ventures"}
    )
    assert contractor.status_code == 201
    contractor_id = contractor.json()["id"]

    payment = client.post(
        f"/api/v1/contractors/{contractor_id}/payments",
        headers=headers,
        json={
            "category": "services",
            "gross_amount_minor": 100_000_00,
            "payment_date": "2026-01-15",
        },
    )
    assert payment.status_code == 400
    assert "TIN" in payment.json()["detail"]

    # Adding a TIN afterwards unblocks it.
    update = client.patch(
        f"/api/v1/contractors/{contractor_id}", headers=headers, json={"tin": "11122233-0001"}
    )
    assert update.status_code == 200
    retried = client.post(
        f"/api/v1/contractors/{contractor_id}/payments",
        headers=headers,
        json={
            "category": "services",
            "gross_amount_minor": 100_000_00,
            "payment_date": "2026-01-15",
        },
    )
    assert retried.status_code == 201


def test_unknown_wht_category_is_rejected() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="wht-admin3@example.com")

    contractor = client.post(
        "/api/v1/contractors",
        headers=headers,
        json={"name": "Consulting Co", "tin": "55566677-0001"},
    )
    contractor_id = contractor.json()["id"]

    payment = client.post(
        f"/api/v1/contractors/{contractor_id}/payments",
        headers=headers,
        json={
            "category": "rent",
            "gross_amount_minor": 100_000_00,
            "payment_date": "2026-01-15",
        },
    )
    assert payment.status_code == 400


def test_wht_payment_creates_statutory_liability() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="wht-admin4@example.com")

    contractor = client.post(
        "/api/v1/contractors",
        headers=headers,
        json={"name": "Materials Supplier", "tin": "44455566-0001"},
    )
    contractor_id = contractor.json()["id"]

    payment = client.post(
        f"/api/v1/contractors/{contractor_id}/payments",
        headers=headers,
        json={
            "category": "goods",
            "gross_amount_minor": 200_000_00,
            "payment_date": "2026-03-10",
        },
    )
    assert payment.status_code == 201, payment.text

    liabilities = client.get("/api/v1/statutory-liabilities", headers=headers)
    assert liabilities.status_code == 200
    wht_liabilities = [
        liability
        for liability in liabilities.json()
        if liability["scheme"] == LiabilityScheme.WHT.value
    ]
    assert len(wht_liabilities) == 1
    liability = wht_liabilities[0]
    assert liability["amount_minor"] == 1_000_000  # 5% of 200,000.00 naira
    assert liability["due_date"] == "2026-04-21"
    assert liability["status"] == "pending"


def test_employee_role_cannot_manage_contractors() -> None:
    org_id = create_org()
    email = "just-an-employee@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id)
    headers = auth_headers(login(email)["access_token"])

    response = client.post("/api/v1/contractors", headers=headers, json={"name": "Should Not Work"})
    assert response.status_code == 403
