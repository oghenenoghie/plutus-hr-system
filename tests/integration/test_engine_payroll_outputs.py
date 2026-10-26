"""What an engine country's payroll shows (docs/architecture/multicountry-tax.md,
Part 3, Stage 2b): the payslip PDF, the payroll reports and tax certificate,
the disbursement file and payroll analytics show the country's own statutory
lines in its currency, and Nigeria's stay as they were.

Kenya is marked active and a rule set of fictional figures is registered for
each test only (tests/integration/engine_helpers.py). None is Kenya's.
"""

from typing import Any
from unittest import mock

import pytest
from reportlab import rl_config

from app.compliance.engine.rules import CountryRuleSet
from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login,
)
from tests.integration.engine_helpers import (
    FICTIONAL_RULES,
    kenya_on_the_engine,
    kenyan_org,
    payslips_of,
)
from tests.unit.tax_engine_fixtures import units

# One employee on 500,000 a month under FICTIONAL_RULES: pension 25,000 from
# the employee and 25,000 from the employer, income tax on 475,000 of
# 10% x 10,000 + 30% x 465,000 = 140,500, net 334,500, and a 5,000 levy.
GROSS, PENSION, INCOME_TAX, NET = units(500_000), units(25_000), units(140_500), units(334_500)


@pytest.fixture
def kenya_with_fictional_rules(monkeypatch: pytest.MonkeyPatch) -> CountryRuleSet:
    kenya_on_the_engine(monkeypatch, FICTIONAL_RULES)
    return FICTIONAL_RULES


def _kenyan_run(email: str) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    org_id, headers = kenyan_org(email)
    create_employee(org_id, employee_number="KE-001")
    run = create_and_lock_pay_run(headers)
    [payslip] = payslips_of(headers, run["id"])
    return headers, run, payslip


def _uncompressed(path: str, headers: dict[str, str], **params: Any) -> bytes:
    with mock.patch.object(rl_config, "pageCompression", 0):
        response = client.get(path, headers=headers, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    content: bytes = response.content
    return content


@pytest.mark.usefixtures("kenya_with_fictional_rules")
def test_the_payslip_pdf_shows_the_countrys_lines_in_its_currency() -> None:
    headers, run, payslip = _kenyan_run("engine-out-pdf@example.com")

    pdf = _uncompressed(f"/api/v1/pay-runs/{run['id']}/payslips/{payslip['id']}/pdf", headers)
    for expected in (
        b"500000.00 KES",
        b"-25000.00 KES",  # the employee's pension
        b"Income tax",
        b"-140500.00 KES",
        b"334500.00 KES",
        b"Employer contributions",
        b"Country rule set: KE-TEST-1",
    ):
        assert expected in pdf, expected
    for nigerian in (b"NGN", b"NHF", b"National Housing Fund", b"PAYE", b"State of residence"):
        assert nigerian not in pdf, nigerian


@pytest.mark.usefixtures("kenya_with_fictional_rules")
def test_the_payroll_reports_show_the_countrys_lines() -> None:
    headers, run, payslip = _kenyan_run("engine-out-reports@example.com")

    [register] = client.get(f"/api/v1/reports/payroll-register/{run['id']}", headers=headers).json()
    assert [(line["code"], line["amount_minor"]) for line in register["statutory_lines"]] == [
        ("PENSION", PENSION),
        ("PENSION-ER", PENSION),
        ("IT", INCOME_TAX),
    ]
    assert (register["paye_minor"], register["net_minor"]) == (INCOME_TAX, NET)

    summary = client.get(
        "/api/v1/reports/statutory-summary",
        headers=headers,
        params={"from_date": "2026-01-01", "to_date": "2026-12-31"},
    )
    assert summary.status_code == 200, summary.text
    assert [
        (line["code"], line["kind"], line["employee_count"], line["amount_minor"])
        for line in summary.json()
    ] == [
        ("PENSION", "employee_contribution", 1, PENSION),
        ("PENSION-ER", "employer_contribution", 1, PENSION),
        ("IT", "income_tax", 1, INCOME_TAX),
    ]

    # Nigerian PAYE is owed to the employee's state; Kenya's income tax isn't.
    by_state = client.get("/api/v1/reports/paye-by-state", headers=headers)
    assert by_state.status_code == 422
    assert "statutory summary" in by_state.json()["detail"]

    [annual] = client.get(
        "/api/v1/reports/annual-tax-reconciliation", headers=headers, params={"tax_year": 2026}
    ).json()
    assert annual["total_gross_minor"] == GROSS
    assert [(total["code"], total["amount_minor"]) for total in annual["statutory_totals"]] == [
        ("PENSION", PENSION),
        ("PENSION-ER", PENSION),
        ("IT", INCOME_TAX),
    ]

    certificate = _uncompressed(
        f"/api/v1/reports/annual-tax-reconciliation/{payslip['employee_id']}/certificate",
        headers,
        tax_year=2026,
    )
    for expected in (b"500000.00 KES", b"Total PENSION withheld", b"Total Income tax withheld"):
        assert expected in certificate, expected
    assert b"140500.00 KES" in certificate
    # The employer's contribution wasn't withheld from the employee.
    assert b"Pension (employer)" not in certificate.replace(b"\\(", b"(").replace(b"\\)", b")")
    for nigerian in (b"NGN", b"NHF", b"PAYE"):
        assert nigerian not in certificate, nigerian


@pytest.mark.usefixtures("kenya_with_fictional_rules")
def test_the_disbursement_file_is_in_the_countrys_currency() -> None:
    headers, run, _ = _kenyan_run("engine-out-disbursement@example.com")
    disbursement = client.get(f"/api/v1/pay-runs/{run['id']}/disbursement", headers=headers)
    assert disbursement.status_code == 200, disbursement.text
    header = disbursement.json()["csv_content"].splitlines()[0]
    assert header.split(",")[4] == "amount_kes"


@pytest.mark.usefixtures("kenya_with_fictional_rules")
def test_payroll_analytics_count_the_countrys_contributions() -> None:
    headers, _, _ = _kenyan_run("engine-out-analytics@example.com")
    period = {"date_from": "2026-01-01", "date_to": "2026-06-30"}

    body = client.get("/api/v1/analytics/payroll", headers=headers, params=period).json()
    kpis = {metric["key"]: metric for metric in body["kpis"]}
    assert kpis["cost"]["currency"] == "KES"
    # Payroll cost is gross pay plus the employer's contributions.
    assert kpis["cost"]["value"] == GROSS + PENSION
    assert kpis["employer_pension"]["value"] == PENSION
    assert kpis["deductions"]["value"] == GROSS - NET

    january = {
        series["key"]: (series["label"], series["points"][0]["value"])
        for series in body["deduction_trend"]["series"]
    }
    assert january == {
        "paye": ("Income tax", INCOME_TAX),
        "employee_contributions": ("Employee contributions", PENSION),
        "other_deductions": ("Loans, benefits and dues", 0),
    }
    [employer_series] = body["employer_contribution_trend"]["series"]
    assert employer_series["label"] == "Employer contributions"

    lines = client.get(
        "/api/v1/analytics/records/statutory_lines", headers=headers, params=period
    ).json()
    assert [(row["code"], row["amount"]) for row in lines["rows"]] == [
        ("PENSION", PENSION),
        ("PENSION-ER", PENSION),
        ("IT", INCOME_TAX),
    ]
    liabilities = client.get(
        "/api/v1/analytics/records/liabilities", headers=headers, params=period
    ).json()
    assert {row["scheme"] for row in liabilities["rows"]} == {"PENSION+PENSION-ER", "IT", "LEVY"}


def test_nigerias_payslip_pdf_certificate_and_disbursement_are_unchanged() -> None:
    org_id = create_org()
    email = "engine-out-nigeria@example.com"
    create_account_with_membership(org_id, Role.ADMIN, email=email)
    headers = auth_headers(login(email)["access_token"])
    employee_id = create_employee(org_id, employee_number="NG-001")
    run = create_and_lock_pay_run(headers, employee_ids=[employee_id])
    [payslip] = payslips_of(headers, run["id"])
    assert payslip["statutory_lines"] == []

    pdf = _uncompressed(f"/api/v1/pay-runs/{run['id']}/payslips/{payslip['id']}/pdf", headers)
    for expected in (
        b"NGN",
        b"Pensionable pay",
        b"National Housing Fund",
        b"PAYE tax",
        b"State of residence",
        b"Compliance rule version: NG-",
    ):
        assert expected in pdf, expected

    certificate = _uncompressed(
        f"/api/v1/reports/annual-tax-reconciliation/{employee_id}/certificate",
        headers,
        tax_year=2026,
    )
    for expected in (b"Total NHF withheld", b"Total PAYE tax withheld", b"NGN"):
        assert expected in certificate, expected

    [register] = client.get(f"/api/v1/reports/payroll-register/{run['id']}", headers=headers).json()
    assert register["statutory_lines"] == []
    assert client.get("/api/v1/reports/paye-by-state", headers=headers).status_code == 200
    assert client.get("/api/v1/reports/statutory-summary", headers=headers).json() == []

    disbursement = client.get(f"/api/v1/pay-runs/{run['id']}/disbursement", headers=headers)
    assert disbursement.json()["csv_content"].splitlines()[0].split(",")[4] == "amount_naira"
