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
