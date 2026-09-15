from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
)


def test_current_rules_exposes_schemes_and_bands() -> None:
    org_id = create_org()
    email = "compliance-viewer@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/compliance/current-rules", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["country"] == "NG"
    assert len(body["paye"]["bands"]) >= 2
    assert body["paye"]["bands"][-1]["up_to_minor"] is None
    assert body["pension"]["authority"] == "PFA"
    assert body["nhf"]["authority"] == "FMBN"
    assert body["nsitf"]["borne_by"] == "employer"
    assert body["itf"]["borne_by"] == "employer"
    assert {c["category"] for c in body["wht"]["categories"]} >= {"goods", "services"}


def test_current_rules_requires_authentication() -> None:
    response = client.get("/api/v1/compliance/current-rules")
    assert response.status_code in (401, 403)


def test_paye_estimate_uses_assumed_split_and_full_year_relief() -> None:
    org_id = create_org()
    email = "paye-estimator@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    headers = auth_headers(login(email)["access_token"])

    response = client.post(
        "/api/v1/compliance/paye-estimate",
        headers=headers,
        json={"annual_gross_minor": 6_000_000_00, "annual_rent_minor": 1_200_000_00},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["basic_minor"] == 3_000_000_00
    assert body["housing_minor"] == 1_800_000_00
    assert body["transport_minor"] == 1_200_000_00
    assert body["gross_annual_minor"] == 6_000_000_00
    assert body["paye_annual_minor"] > 0
    assert body["paye_monthly_minor"] == body["paye_annual_minor"] // 12
    assert body["net_annual_minor"] == (
        body["gross_annual_minor"]
        - body["pension_employee_annual_minor"]
        - body["nhf_annual_minor"]
        - body["paye_annual_minor"]
    )


def test_paye_estimate_rejects_non_positive_gross() -> None:
    org_id = create_org()
    email = "paye-estimator2@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    headers = auth_headers(login(email)["access_token"])

    response = client.post(
        "/api/v1/compliance/paye-estimate",
        headers=headers,
        json={"annual_gross_minor": 0, "annual_rent_minor": 0},
    )
    assert response.status_code == 400
