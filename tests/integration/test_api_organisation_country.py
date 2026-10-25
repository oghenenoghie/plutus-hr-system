"""Each organisation runs on its own country's statutory rules
(docs/architecture/multicountry-tax.md, Part 1): chosen at sign-up, changeable
only before any history, and never calculated with unless approved."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.db import tenant_session
from app.models import Role
from app.models.journal_entry import JournalEntry
from app.models.organisation import Organisation
from app.models.payslip import Payslip
from app.services import jurisdiction
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login,
)


def _admin(org_id: uuid.UUID, email: str) -> dict[str, str]:
    create_account_with_membership(org_id, Role.ADMIN, email=email)
    return auth_headers(login(email)["access_token"])


def _org_in(country_code: str) -> uuid.UUID:
    """An organisation placed in a country directly, bypassing sign-up's
    checks, to prove the calculations themselves refuse it."""
    org_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name="Kenya Test Co", country_code=country_code))
    return org_id


def _signup(email: str, **extra: Any) -> Any:
    return client.post(
        "/api/v1/organisation/signup",
        json={
            "org_name": "Signup Country Co",
            "admin_email": email,
            "admin_password": "s3cret-pass-1",
            **extra,
        },
    )


def test_signup_defaults_to_nigeria_and_the_organisation_reports_it() -> None:
    created = _signup("country-default@example.com")
    assert created.status_code == 201, created.text
    headers = auth_headers(login("country-default@example.com", "s3cret-pass-1")["access_token"])

    org = client.get("/api/v1/organisation", headers=headers).json()
    assert (org["country_code"], org["country_name"], org["currency"]) == ("NG", "Nigeria", "NGN")


def test_signup_accepts_a_lowercase_code_for_an_approved_country() -> None:
    created = _signup("country-lower@example.com", country_code="ng")
    assert created.status_code == 201, created.text


def test_signup_refuses_a_country_whose_rules_are_not_approved() -> None:
    refused = _signup("country-kenya@example.com", country_code="KE")
    assert refused.status_code == 422
    assert "Kenya isn't available yet" in refused.json()["detail"]

    unknown = _signup("country-unknown@example.com", country_code="ZZ")
    assert unknown.status_code == 422
    assert "Unknown country code" in unknown.json()["detail"]


def test_the_public_country_list_says_which_can_be_chosen() -> None:
    response = client.get("/api/v1/organisation/countries")
    assert response.status_code == 200, response.text
    by_code = {country["code"]: country for country in response.json()}

    assert set(by_code) == {"NG", "GM", "RW", "KE", "GH", "CI"}
    assert by_code["NG"]["selectable"] is True
    assert all(not by_code[code]["selectable"] for code in ("GM", "RW", "KE", "GH", "CI"))
    assert by_code["RW"]["currency"] == "RWF"


def test_the_compliance_catalogue_reports_selectability() -> None:
    headers = _admin(create_org(), "country-catalogue@example.com")
    countries = client.get("/api/v1/compliance/countries", headers=headers).json()
    assert {c["code"]: c["selectable"] for c in countries}["NG"] is True


def test_an_admin_cannot_switch_to_a_country_without_approved_rules() -> None:
    headers = _admin(create_org(), "country-switch-refused@example.com")

    refused = client.put("/api/v1/organisation", headers=headers, json={"country_code": "GH"})
    assert refused.status_code == 422
    assert "Ghana isn't available yet" in refused.json()["detail"]

    unchanged = client.put("/api/v1/organisation", headers=headers, json={"country_code": "NG"})
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["country_code"] == "NG"


def test_the_country_can_change_before_history_but_not_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pretend Kenya were selectable, to exercise the history rule.
    real = jurisdiction.is_selectable
    monkeypatch.setattr(
        jurisdiction, "is_selectable", lambda profile: profile.code == "KE" or real(profile)
    )

    fresh = _admin(create_org(), "country-switch-fresh@example.com")
    switched = client.put("/api/v1/organisation", headers=fresh, json={"country_code": "KE"})
    assert switched.status_code == 200, switched.text
    assert (switched.json()["country_code"], switched.json()["currency"]) == ("KE", "KES")

    with_history_org = create_org()
    with_history = _admin(with_history_org, "country-switch-history@example.com")
    employee = create_employee(with_history_org)
    create_and_lock_pay_run(with_history, employee_ids=[employee])
    blocked = client.put("/api/v1/organisation", headers=with_history, json={"country_code": "KE"})
    assert blocked.status_code == 409
    assert "pay run" in blocked.json()["detail"]


def test_nothing_calculates_for_a_country_without_approved_rules() -> None:
    org_id = _org_in("KE")
    headers = _admin(org_id, "country-kenya-admin@example.com")
    employee = create_employee(org_id)

    rules = client.get("/api/v1/compliance/current-rules", headers=headers)
    assert rules.status_code == 422
    assert "Kenya" in rules.json()["detail"]

    estimate = client.post(
        "/api/v1/compliance/paye-estimate",
        headers=headers,
        json={"annual_gross_minor": 6_000_000_00, "annual_rent_minor": 0},
    )
    assert estimate.status_code == 422

    created = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "frequency": "monthly",
            "employee_ids": [str(employee)],
        },
    )
    assert created.status_code == 201, created.text  # a draft calculates nothing
    pay_run_id = created.json()["id"]
    validated = client.post(f"/api/v1/pay-runs/{pay_run_id}/validate", headers=headers, json={})
    assert validated.status_code == 422, validated.text
    assert "Kenya" in validated.json()["detail"]
    locked = client.post(f"/api/v1/pay-runs/{pay_run_id}/lock", headers=headers)
    assert locked.status_code in (409, 422), locked.text

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        assert db.scalar(select(func.count()).select_from(Payslip)) == 0
        assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_a_nigerian_organisation_posts_journals_in_naira() -> None:
    org_id = create_org()
    headers = _admin(org_id, "country-journals@example.com")
    employee = create_employee(org_id)
    create_and_lock_pay_run(headers, employee_ids=[employee])

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        currencies = set(db.scalars(select(JournalEntry.currency)))
    assert currencies == {"NGN"}
