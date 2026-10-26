"""Pay runs for a country on the engine (docs/architecture/multicountry-tax.md,
Part 3, Stage 2): the payslip's statutory lines, its postings, the run's
liabilities and levies, and the year to date across runs.

No country beyond Nigeria has approved rules, so each test marks Kenya active
and registers a rule set of fictional figures (tests/unit/tax_engine_fixtures.py)
for its own duration only. None of these figures is Kenya's.
"""

import uuid
from collections import defaultdict
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from sqlalchemy import func, select

from app.compliance.engine.rules import Applicability, CountryRuleSet, TaxBand, TaxMethod
from app.core.db import tenant_session
from app.models.benefit import Benefit, BenefitFrequency
from app.models.journal_entry import JournalEntry
from app.models.ledger import LedgerEntry
from app.models.loan import Loan
from app.models.payslip import Payslip
from app.models.payslip_statutory_line import PayslipStatutoryLine
from app.models.union_membership import UnionMembership, UnionMembershipStatus
from tests.integration.api_helpers import client, create_and_lock_pay_run, create_employee
from tests.integration.engine_helpers import (
    FICTIONAL_RULES,
    kenya_on_the_engine,
    kenyan_org,
    payslips_of,
)
from tests.unit.tax_engine_fixtures import contribution, tax_rule, units


@pytest.fixture
def kenya_with_fictional_rules(monkeypatch: pytest.MonkeyPatch) -> CountryRuleSet:
    kenya_on_the_engine(monkeypatch, FICTIONAL_RULES)
    return FICTIONAL_RULES


def _draft_and_validate(headers: dict[str, str], employee_id: uuid.UUID) -> tuple[str, Any]:
    created = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "frequency": "monthly",
            "employee_ids": [str(employee_id)],
        },
    )
    assert created.status_code == 201, created.text
    pay_run_id: str = created.json()["id"]
    return pay_run_id, client.post(
        f"/api/v1/pay-runs/{pay_run_id}/validate", headers=headers, json={}
    )


def _nothing_calculated(org_id: uuid.UUID) -> None:
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        assert db.scalar(select(func.count()).select_from(Payslip)) == 0
        assert db.scalar(select(func.count()).select_from(PayslipStatutoryLine)) == 0
        assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0


@pytest.mark.usefixtures("kenya_with_fictional_rules")
def test_an_engine_pay_run_records_lines_postings_and_liabilities() -> None:
    org_id, headers = kenyan_org("engine-run@example.com")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert (me["currency"], me["payroll_available"]) == ("KES", True)

    # 300,000 basic + 150,000 housing + 50,000 transport = 500,000 a month.
    employee_id = create_employee(org_id, employee_number="KE-001")
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            Loan(
                org_id=org_id,
                employee_id=employee_id,
                principal_minor=units(100_000),
                total_repayable_minor=units(100_000),
                num_installments=5,
                installment_minor=units(20_000),
                start_date=date(2026, 1, 1),
            )
        )
        db.add(
            Benefit(
                org_id=org_id,
                employee_id=employee_id,
                name="Health cover",
                value_minor=units(5_000),
                frequency=BenefitFrequency.MONTHLY,
                effective_date=date(2026, 1, 1),
            )
        )
        db.add(
            UnionMembership(
                org_id=org_id,
                employee_id=employee_id,
                union_name="Staff union",
                monthly_dues_minor=units(1_000),
                status=UnionMembershipStatus.ACTIVE,
                joined_date=date(2025, 1, 1),
            )
        )

    run = create_and_lock_pay_run(headers, employee_ids=[employee_id])
    [payslip] = payslips_of(headers, run["id"])

    # Pension 5% of 500,000 = 25,000 each. Taxable 500,000 - 25,000 =
    # 475,000: 10% of 10,000 + 30% of 465,000 = 140,500. Statutory net
    # 500,000 - 25,000 - 140,500 = 334,500; less the 20,000 loan
    # installment, 5,000 benefit and 1,000 union dues = 308,500.
    assert payslip["gross_minor"] == units(500_000)
    assert payslip["paye_minor"] == units(140_500)
    assert payslip["net_minor"] == units(308_500)
    assert payslip["rule_version_id"] == "KE-TEST-1"
    # Nigeria's own columns stay empty: the lines carry the figures.
    assert (payslip["pension_employee_minor"], payslip["nhf_minor"]) == (0, 0)
    lines = [
        (line["code"], line["kind"], line["amount_minor"], line["due_date"])
        for line in payslip["statutory_lines"]
    ]
    assert lines == [
        ("PENSION", "employee_contribution", units(25_000), "2026-02-09"),
        ("PENSION-ER", "employer_contribution", units(25_000), "2026-02-09"),
        ("IT", "income_tax", units(140_500), "2026-02-09"),
    ]
    assert {line["rule_set_id"] for line in payslip["statutory_lines"]} == {"KE-TEST-1"}
    outputs = payslip["derivation"]["outputs"]
    assert (
        outputs["loan_deduction_minor"],
        outputs["benefit_deduction_minor"],
        outputs["union_dues_deduction_minor"],
    ) == (units(20_000), units(5_000), units(1_000))
    assert payslip["derivation"]["engine"]["rule_set_id"] == "KE-TEST-1"

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        entries = db.scalars(
            select(LedgerEntry).where(LedgerEntry.pay_run_id == uuid.UUID(run["id"]))
        )
        balances: dict[str, int] = defaultdict(int)
        for entry in entries:
            balances[entry.account] += entry.debit_minor - entry.credit_minor
        currencies = set(db.scalars(select(JournalEntry.currency)))
    assert currencies == {"KES"}
    assert sum(balances.values()) == 0
    assert dict(balances) == {
        "payroll_expense_gross": units(500_000),
        "payroll_expense_pension": units(25_000),
        "payroll_expense_training_levy": units(5_000),
        "pension_payable": -units(50_000),
        "income_tax_payable": -units(140_500),
        "training_levy_payable": -units(5_000),
        "employee_loan_receivable": -units(20_000),
        "benefit_deductions_recovered": -units(5_000),
        "union_dues_payable": -units(1_000),
        "net_pay_payable": -units(308_500),
    }

    liabilities = client.get("/api/v1/statutory-liabilities", headers=headers).json()
    owed = {
        (lty["scheme"], lty["line_code"], lty["liability_account"], lty["authority"]): (
            lty["base_minor"],
            lty["amount_minor"],
            lty["due_date"],
        )
        for lty in liabilities
    }
    assert owed == {
        ("country", "PENSION+PENSION-ER", "pension_payable", "Fund"): (
            units(500_000),
            units(50_000),
            "2026-02-09",
        ),
        ("country", "IT", "income_tax_payable", "Revenue authority"): (
            units(475_000),
            units(140_500),
            "2026-02-09",
        ),
        ("country", "LEVY", "training_levy_payable", "Levy board"): (
            units(500_000),
            units(5_000),
            "2026-02-09",
        ),
    }


@pytest.mark.usefixtures("kenya_with_fictional_rules")
def test_remitting_a_country_liability_clears_its_payable_account() -> None:
    org_id, headers = kenyan_org("engine-remit@example.com")
    enabled = client.patch(
        "/api/v1/accounting-settings", headers=headers, json={"post_statutory_remittances": True}
    )
    assert enabled.status_code == 200, enabled.text
    employee_id = create_employee(org_id, employee_number="KE-001")
    create_and_lock_pay_run(headers, employee_ids=[employee_id])

    [pension] = [
        lty
        for lty in client.get("/api/v1/statutory-liabilities", headers=headers).json()
        if lty["liability_account"] == "pension_payable"
    ]
    remitted = client.post(
        f"/api/v1/statutory-liabilities/{pension['id']}/remit",
        headers=headers,
        json={"reference": "FUND-0001"},
    )
    assert remitted.status_code == 200, remitted.text
    assert remitted.json()["status"] == "remitted"

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        rows = db.execute(
            select(LedgerEntry.account, LedgerEntry.debit_minor, LedgerEntry.credit_minor).where(
                LedgerEntry.journal_entry_id == uuid.UUID(remitted.json()["remittance_journal_id"])
            )
        ).all()
    assert {(row.account, row.debit_minor, row.credit_minor) for row in rows} == {
        ("pension_payable", units(50_000), 0),
        ("cash", 0, units(50_000)),
    }


def test_the_year_to_date_counts_locked_runs_only(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cumulative: tax on the year's taxable pay to date against an annual
    # table (10% on the first 120,000, 30% above), less tax already withheld.
    cumulative = replace(
        FICTIONAL_RULES,
        income_tax=tax_rule(
            method=TaxMethod.CUMULATIVE_ANNUAL,
            bands=(TaxBand(units(120_000), 100_000), TaxBand(None, 300_000)),
        ),
        contributions=(),
        payroll_levies=(),
    )
    kenya_on_the_engine(monkeypatch, cumulative)
    org_id, headers = kenyan_org("engine-ytd@example.com")
    employee_id = create_employee(
        org_id,
        employee_number="KE-001",
        basic_minor=units(100_000),
        housing_minor=0,
        transport_minor=0,
    )

    january = create_and_lock_pay_run(headers, employee_ids=[employee_id])
    february = create_and_lock_pay_run(
        headers,
        period_start="2026-02-01",
        period_end="2026-02-28",
        employee_ids=[employee_id],
    )
    # January: 100,000 taxed at 10% = 10,000. February: 200,000 to date is
    # 12,000 + 24,000 = 36,000, less 10,000 already withheld = 26,000.
    assert payslips_of(headers, january["id"])[0]["paye_minor"] == units(10_000)
    assert payslips_of(headers, february["id"])[0]["paye_minor"] == units(26_000)

    reversed_run = client.post(
        f"/api/v1/pay-runs/{february['id']}/reverse", headers=headers, json={}
    )
    assert reversed_run.status_code == 200, reversed_run.text

    # With February reversed, March is the second period on the books: the
    # year to date is January's alone, so March's tax is February's again.
    march = create_and_lock_pay_run(
        headers,
        period_start="2026-03-01",
        period_end="2026-03-31",
        employee_ids=[employee_id],
    )
    [payslip] = payslips_of(headers, march["id"])
    assert payslip["paye_minor"] == units(26_000)
    year_to_date = payslip["derivation"]["engine"]["inputs"]["year_to_date"]
    assert year_to_date["taxable_earnings_minor"] == units(100_000)
    assert year_to_date["income_tax_withheld_minor"] == units(10_000)


def test_a_rule_needing_an_unrecorded_employee_fact_refuses_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_staff_only = replace(
        FICTIONAL_RULES,
        contributions=(contribution("PENSION", applies_to=Applicability.LOCAL_STAFF),),
        payroll_levies=(),
    )
    kenya_on_the_engine(monkeypatch, local_staff_only)
    org_id, headers = kenyan_org("engine-missing-fact@example.com")
    employee_id = create_employee(org_id, employee_number="KE-007")

    pay_run_id, validated = _draft_and_validate(headers, employee_id)
    assert validated.status_code == 200, validated.text
    locked = client.post(f"/api/v1/pay-runs/{pay_run_id}/lock", headers=headers)
    assert locked.status_code == 422, locked.text
    assert "KE-007" in locked.json()["detail"]
    assert "expatriate" in locked.json()["detail"]
    _nothing_calculated(org_id)

    # Once the employee's record says, the run goes through.
    updated = client.patch(
        f"/api/v1/employees/{employee_id}", headers=headers, json={"is_expatriate": False}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_expatriate"] is False
    locked = client.post(f"/api/v1/pay-runs/{pay_run_id}/lock", headers=headers)
    assert locked.status_code == 200, locked.text
    [payslip] = payslips_of(headers, pay_run_id)
    assert [line["code"] for line in payslip["statutory_lines"]] == ["PENSION", "IT"]


def test_a_country_marked_active_without_a_registered_rule_set_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kenya_on_the_engine(monkeypatch)
    org_id, headers = kenyan_org("engine-no-rules@example.com")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["payroll_available"] is False

    employee_id = create_employee(org_id, employee_number="KE-001")
    _, validated = _draft_and_validate(headers, employee_id)
    assert validated.status_code == 422, validated.text
    assert "No approved Kenya payroll rules" in validated.json()["detail"]
    _nothing_calculated(org_id)


def test_a_rule_set_that_starts_after_the_period_is_refused_at_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kenya_on_the_engine(monkeypatch, replace(FICTIONAL_RULES, effective_from=date(2026, 2, 1)))
    org_id, headers = kenyan_org("engine-later-rules@example.com")
    employee_id = create_employee(org_id, employee_number="KE-001")

    _, validated = _draft_and_validate(headers, employee_id)
    assert validated.status_code == 422, validated.text
    assert "2026-01-31" in validated.json()["detail"]
    _nothing_calculated(org_id)


@pytest.mark.usefixtures("kenya_with_fictional_rules")
def test_another_organisations_engine_payslips_and_liabilities_stay_hidden() -> None:
    org_id, headers = kenyan_org("engine-tenant-a@example.com")
    employee_id = create_employee(org_id, employee_number="KE-001")
    run = create_and_lock_pay_run(headers, employee_ids=[employee_id])

    _, other_headers = kenyan_org("engine-tenant-b@example.com")
    payslips = client.get(f"/api/v1/pay-runs/{run['id']}/payslips", headers=other_headers)
    assert payslips.status_code in (200, 404)
    if payslips.status_code == 200:
        assert payslips.json() == []
    assert client.get("/api/v1/statutory-liabilities", headers=other_headers).json() == []

    with tenant_session(uuid.uuid4(), uuid.uuid4(), "admin") as db:
        assert db.scalar(select(func.count()).select_from(PayslipStatutoryLine)) == 0
