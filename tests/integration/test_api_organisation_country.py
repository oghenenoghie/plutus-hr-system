"""Each organisation runs in its own country (docs/architecture/multicountry-tax.md,
Part 1): any catalogued country can be chosen at sign-up and applies at once,
it can change only before any history, and payroll and statutory tax never
calculate for a country whose rules aren't approved."""

import uuid
from typing import Any
from unittest import mock

from reportlab import rl_config
from sqlalchemy import func, select

from app.core.db import tenant_session
from app.models import Role
from app.models.journal_entry import JournalEntry
from app.models.organisation import Organisation
from app.models.payslip import Payslip
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
        db.add(Organisation(id=org_id, name=f"{country_code} Test Co", country_code=country_code))
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


def test_signup_accepts_any_catalogued_country_and_it_applies_at_once() -> None:
    created = _signup("country-kenya@example.com", country_code="KE")
    assert created.status_code == 201, created.text
    headers = auth_headers(login("country-kenya@example.com", "s3cret-pass-1")["access_token"])

    org = client.get("/api/v1/organisation", headers=headers).json()
    assert (org["country_code"], org["country_name"], org["currency"]) == ("KE", "Kenya", "KES")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    # Kenya's rules are approved: payroll runs once Tax Settings are entered.
    assert (me["country_code"], me["currency"], me["payroll_available"]) == ("KE", "KES", True)


def test_signup_refuses_a_country_plutus_does_not_list() -> None:
    unknown = _signup("country-unknown@example.com", country_code="ZZ")
    assert unknown.status_code == 422
    assert "Unknown country code" in unknown.json()["detail"]


def test_every_role_learns_the_country_and_currency_from_auth_me() -> None:
    org_id = _org_in("RW")
    email = "country-rw-employee@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    me = client.get("/api/v1/auth/me", headers=auth_headers(login(email)["access_token"])).json()
    assert (me["country_name"], me["currency"], me["payroll_available"]) == ("Rwanda", "RWF", True)

    nigeria = _admin(create_org(), "country-ng-me@example.com")
    me = client.get("/api/v1/auth/me", headers=nigeria).json()
    assert (me["country_code"], me["currency"], me["payroll_available"]) == ("NG", "NGN", True)


def test_the_public_country_list_offers_every_country_and_says_where_payroll_runs() -> None:
    response = client.get("/api/v1/organisation/countries")
    assert response.status_code == 200, response.text
    by_code = {country["code"]: country for country in response.json()}

    assert set(by_code) == {"NG", "GM", "RW", "KE", "GH", "CI"}
    assert all(country["selectable"] for country in by_code.values())
    assert all(country["payroll_available"] for country in by_code.values())
    assert by_code["RW"]["currency"] == "RWF"


def test_the_compliance_catalogue_reports_payroll_availability() -> None:
    headers = _admin(create_org(), "country-catalogue@example.com")
    countries = {
        c["code"]: c for c in client.get("/api/v1/compliance/countries", headers=headers).json()
    }
    assert countries["NG"]["payroll_available"] is True
    assert countries["GH"]["payroll_available"] is True
    assert countries["GH"]["selectable"] is True


def test_the_country_can_change_before_history_but_not_after() -> None:
    fresh = _admin(create_org(), "country-switch-fresh@example.com")
    switched = client.put("/api/v1/organisation", headers=fresh, json={"country_code": "gh"})
    assert switched.status_code == 200, switched.text
    assert (switched.json()["country_code"], switched.json()["currency"]) == ("GH", "GHS")

    unknown = client.put("/api/v1/organisation", headers=fresh, json={"country_code": "ZZ"})
    assert unknown.status_code == 422

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


def test_a_kenyan_organisation_keeps_its_books_in_shillings() -> None:
    org_id = _org_in("KE")
    headers = _admin(org_id, "country-kenya-books@example.com")

    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    codes = {account["code"] for account in seeded.json()}
    assert {"accounts_payable", "paye_payable", "wht_payable"} <= codes
    assert not codes & {"nhf_payable", "nsitf_payable", "payroll_expense_nsitf"}

    vendor = client.post("/api/v1/vendors", headers=headers, json={"name": "Nairobi Supplies"})
    bill_body = {
        "vendor_id": vendor.json()["id"],
        "bill_date": "2026-09-01",
        "due_date": "2026-09-30",
        "expense_account_code": "contractor_expense",
        "amount_minor": 1_500_00,
    }
    plain = client.post("/api/v1/bills", headers=headers, json={**bill_body, "bill_number": "KE-1"})
    assert plain.status_code == 201, plain.text
    approved = client.post(f"/api/v1/bills/{plain.json()['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    entries = client.get("/api/v1/general-ledger/entries", headers=headers).json()
    journal_ids = {entry["journal_entry_id"] for entry in entries}
    assert journal_ids
    for journal_id in journal_ids:
        journal = client.get(f"/api/v1/general-ledger/journals/{journal_id}", headers=headers)
        assert journal.json()["currency"] == "KES"

    # A posted bill is history in shillings, so the country is now fixed.
    moved = client.put("/api/v1/organisation", headers=headers, json={"country_code": "GH"})
    assert moved.status_code == 409

    with mock.patch.object(rl_config, "pageCompression", 0):
        pdf = client.get(f"/api/v1/bills/{plain.json()['id']}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert b"1500.00 KES" in pdf.content

    # Withholding needs Kenya's approved rates, so a bill that withholds is refused.
    withholding = client.post(
        "/api/v1/bills",
        headers=headers,
        json={**bill_body, "bill_number": "KE-2", "wht_category": "services"},
    )
    assert withholding.status_code == 201, withholding.text
    refused = client.post(f"/api/v1/bills/{withholding.json()['id']}/approve", headers=headers)
    assert refused.status_code == 422
    assert "Kenya" in refused.json()["detail"]


def test_only_a_nigerian_organisation_gets_default_public_holidays() -> None:
    kenya = _admin(_org_in("KE"), "country-kenya-holidays@example.com")
    refused = client.post("/api/v1/public-holidays/seed-defaults?year=2026", headers=kenya)
    assert refused.status_code == 422
    assert "Kenya's public holidays" in refused.json()["detail"]

    nigeria = _admin(create_org(), "country-nigeria-holidays@example.com")
    seeded = client.post("/api/v1/public-holidays/seed-defaults?year=2026", headers=nigeria)
    assert seeded.status_code == 200, seeded.text
    assert "Democracy Day" in {holiday["name"] for holiday in seeded.json()}
