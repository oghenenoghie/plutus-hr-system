"""Tax Settings (app/api/v1/tax_settings.py): an organisation in an engine
country enters the figures its country's approved rules leave to it, and its
pay runs use them. These tests run Kenya's real rule set (KE-2026.1)."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.models import AuditLog, OrgTaxSetting, Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login,
)
from tests.integration.engine_helpers import kenyan_org, payslips_of

KENYA_SETTINGS = {"nssf_tax_deductible": "yes", "nita_applies": "yes", "nita_due_day": "5"}
MARCH = {"period_start": "2026-03-01", "period_end": "2026-03-31"}


def _settings(headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/api/v1/compliance/tax-settings", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _enter(
    headers: dict[str, str], values: dict[str, str], effective_from: str = "2026-02-01"
) -> Any:
    return client.post(
        "/api/v1/compliance/tax-settings",
        headers=headers,
        json={"effective_from": effective_from, "values": values, "note": "From our adviser"},
    )


def _member(org_id: uuid.UUID, role: Role, email: str) -> dict[str, str]:
    create_account_with_membership(org_id, role, email=email)
    return auth_headers(login(email)["access_token"])


def test_a_new_kenyan_organisation_sees_what_it_must_enter() -> None:
    _, headers = kenyan_org("tax-settings-new@example.com")
    body = _settings(headers)
    assert (body["country_code"], body["currency"], body["applies"]) == ("KE", "KES", True)
    assert (body["rule_set_id"], body["approved_by"]) == ("KE-2026.1", "Plutus Technologies")
    assert body["approval_basis"] == "owner_approved"
    assert body["missing"] == ["nssf_tax_deductible", "nita_applies"]
    by_key = {setting["key"]: setting for setting in body["settings"]}
    # The NITA due day is asked for only once the levy applies.
    assert by_key["nita_due_day"]["required"] is False
    assert by_key["nita_due_day"]["required_when_key"] == "nita_applies"
    assert [option["display"] for option in by_key["nita_due_day"]["options"]] == ["5", "10"]
    assert all(option["source"] for option in by_key["nita_applies"]["options"])
    assert body["rules"] is None
    assert body["summary"][0].startswith("Kenya, from February 2026")
    assert any(source["official"] for source in body["sources"])


def test_payroll_is_refused_until_the_settings_are_entered() -> None:
    org_id, headers = kenyan_org("tax-settings-refused@example.com")
    employee_id = create_employee(org_id, employee_number="KE-001")
    created = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={**MARCH, "frequency": "monthly", "employee_ids": [str(employee_id)]},
    )
    assert created.status_code == 201, created.text
    validated = client.post(
        f"/api/v1/pay-runs/{created.json()['id']}/validate", headers=headers, json={}
    )
    assert validated.status_code == 422, validated.text
    detail = validated.json()["detail"]
    assert "Tax Settings" in detail
    assert "Is the employee's NSSF contribution deducted before PAYE?" in detail


def test_only_an_admin_enters_settings_and_every_entry_is_audited() -> None:
    org_id, admin = kenyan_org("tax-settings-admin@example.com")
    payroll = _member(org_id, Role.PAYROLL_MANAGER, "tax-settings-payroll@example.com")
    employee = _member(org_id, Role.EMPLOYEE, "tax-settings-employee@example.com")

    assert _settings(payroll)["missing"]
    assert client.get("/api/v1/compliance/tax-settings", headers=employee).status_code == 403
    assert _enter(payroll, KENYA_SETTINGS).status_code == 403

    entered = _enter(admin, KENYA_SETTINGS)
    assert entered.status_code == 200, entered.text
    body = entered.json()
    assert body["missing"] == []
    by_key = {setting["key"]: setting for setting in body["settings"]}
    assert by_key["nita_due_day"]["display"] == "5"
    assert by_key["nita_due_day"]["entered_by"] == "tax-settings-admin@example.com"
    assert by_key["nssf_tax_deductible"]["effective_from"] == "2026-02-01"
    assert {entry["key"] for entry in body["history"]} == set(KENYA_SETTINGS)
    assert {entry["note"] for entry in body["history"]} == {"From our adviser"}

    rules = body["rules"]
    assert rules["rule_set_id"] == "KE-2026.1"
    assert [band["rate_ppm"] for band in rules["income_tax"]["bands"]] == [
        100_000,
        250_000,
        300_000,
        325_000,
        350_000,
    ]
    lines = {line["code"]: line for line in rules["lines"]}
    assert lines["NSSF"]["tax_deductible"] is True
    assert lines["NITA"]["amount_minor"] == 5_000
    assert lines["NITA"]["due"] == "Day 5 of the following month"
    assert lines["PERSONAL-RELIEF"]["kind"] == "tax_credit"

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        [audit] = db.scalars(select(AuditLog).where(AuditLog.action == "tax_settings.update")).all()
        assert audit.event_metadata["values"] == {
            "nssf_tax_deductible": "yes",
            "nita_applies": "yes",
            "nita_due_day": "5",
        }
        assert audit.event_metadata["effective_from"] == "2026-02-01"


@pytest.mark.parametrize(
    ("values", "effective_from", "message"),
    [
        ({"nita_due_day": "31"}, "2026-02-01", "between 1 and 28"),
        ({"nita_applies": "sometimes"}, "2026-02-01", "choose one of"),
        ({"vat_rate": "16"}, "2026-02-01", "don't ask for 'vat_rate'"),
        ({"nita_applies": "yes"}, "2026-01-31", "No Kenya payroll rules"),
    ],
)
def test_settings_that_dont_fit_are_refused(
    values: dict[str, str], effective_from: str, message: str
) -> None:
    _, headers = kenyan_org(f"tax-settings-bad-{uuid.uuid4().hex[:8]}@example.com")
    refused = _enter(headers, values, effective_from)
    assert refused.status_code == 400, refused.text
    assert message in refused.json()["detail"]
    assert _settings(headers)["history"] == []


def test_a_pay_run_uses_the_settings_and_keeps_them_after_they_change() -> None:
    org_id, headers = kenyan_org("tax-settings-run@example.com")
    assert _enter(headers, KENYA_SETTINGS).status_code == 200
    create_employee(org_id, employee_number="KE-001")
    run = create_and_lock_pay_run(headers, **MARCH)
    [payslip] = payslips_of(headers, run["id"])

    # Gross 500,000 KES. NSSF 6% of the 108,000 limit = 6,480; SHIF 13,750;
    # Housing Levy 7,500, all deductible, so taxable 472,270. PAYE: 2,400 +
    # 2,083.25 + 30% x 439,937 = 136,464.35, less 2,400 relief = 134,064.35.
    lines = {line["code"]: line["amount_minor"] for line in payslip["statutory_lines"]}
    assert lines == {
        "NSSF": 648_000,
        "NSSF-ER": 648_000,
        "SHIF": 1_375_000,
        "HOUSING-LEVY": 750_000,
        "HOUSING-LEVY-ER": 750_000,
        "NITA": 5_000,
        "PAYE": 13_406_435,
    }
    assert payslip["rule_version_id"] == "KE-2026.1"
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        derivation = db.execute(
            text("SELECT derivation FROM payslips WHERE id = :id"), {"id": payslip["id"]}
        ).scalar_one()
    assert derivation["inputs"]["tax_settings"] == {
        "nssf_tax_deductible": "yes",
        "nita_applies": "yes",
        "nita_due_day": "5",
    }

    # March is locked: a change can only take effect after it.
    refused = _enter(headers, {"nssf_tax_deductible": "no"}, "2026-03-31")
    assert refused.status_code == 400
    assert "Choose a date from 2026-04-01" in refused.json()["detail"]
    changed = _enter(headers, {"nssf_tax_deductible": "no"}, "2026-04-01")
    assert changed.status_code == 200, changed.text

    # March's payslip keeps the figures it was worked out with.
    [unchanged] = payslips_of(headers, run["id"])
    assert unchanged["statutory_lines"] == payslip["statutory_lines"]

    april = create_and_lock_pay_run(headers, period_start="2026-04-01", period_end="2026-04-30")
    [april_payslip] = payslips_of(headers, april["id"])
    april_lines = {line["code"]: line["amount_minor"] for line in april_payslip["statutory_lines"]}
    # NSSF no longer comes off first: taxable 478,750, so PAYE is 30% of
    # 6,480 more, 136,008.35.
    assert april_lines["PAYE"] == 13_600_835


def test_each_organisation_sees_only_its_own_settings() -> None:
    first_id, first = kenyan_org("tax-settings-first@example.com")
    _, second = kenyan_org("tax-settings-second@example.com")
    assert _enter(first, KENYA_SETTINGS).status_code == 200

    other = _settings(second)
    assert other["history"] == []
    assert other["missing"] == ["nssf_tax_deductible", "nita_applies"]

    with tenant_session(uuid.uuid4(), uuid.uuid4(), "admin") as db:
        assert db.scalars(select(OrgTaxSetting)).all() == []
    with tenant_session(first_id, uuid.uuid4(), "admin") as db:
        assert len(db.scalars(select(OrgTaxSetting)).all()) == 3


def test_entered_settings_cant_be_edited_or_deleted() -> None:
    org_id, headers = kenyan_org("tax-settings-append-only@example.com")
    assert _enter(headers, KENYA_SETTINGS).status_code == 200
    for statement in (
        "UPDATE org_tax_settings SET value = 'no'",
        "DELETE FROM org_tax_settings",
    ):
        with (
            pytest.raises(DBAPIError, match="append-only"),
            tenant_session(org_id, uuid.uuid4(), "admin") as db,
        ):
            db.execute(text(statement))


def test_nigeria_takes_no_tax_settings() -> None:
    org_id = create_org()
    headers = _member(org_id, Role.ADMIN, "tax-settings-nigeria@example.com")
    body = _settings(headers)
    assert (body["country_code"], body["applies"], body["settings"]) == ("NG", False, [])
    refused = _enter(headers, {"nita_applies": "yes"})
    assert refused.status_code == 400
    assert "No Nigeria payroll rules that take Tax Settings" in refused.json()["detail"]
