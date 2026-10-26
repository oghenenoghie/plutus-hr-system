"""A rule set of fictional figures for an engine country, and the setup that
makes it usable for one test: Kenya marked active in the catalogue and the
rule set registered, through pytest's monkeypatch, so both revert when the
test ends. None of these figures is Kenya's (tests/unit/tax_engine_fixtures.py).
"""

import uuid
from dataclasses import replace
from typing import Any

import pytest

from app.compliance import multicountry
from app.compliance.engine import registry
from app.compliance.engine.rules import CountryRuleSet, DeductionCap, PayrollLevyRule
from app.compliance.multicountry import TaxStatus
from app.core.db import tenant_session
from app.models import Role
from app.models.organisation import Organisation
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    login,
)
from tests.unit.tax_engine_fixtures import (
    ALL_CASH,
    DUE,
    HALF_UP,
    contribution,
    employer,
    rule_set,
    tax_rule,
)

# 5% from the employee and 5% from the employer into one fund, the
# employee's share deductible before income tax; income tax at 10% on the
# first 10,000 a month and 30% above; a 1% employer levy on the whole run.
FICTIONAL_RULES = rule_set(
    contribution("PENSION", liability_account="pension_payable", tax_deduction_group="pension"),
    employer(
        "PENSION-ER",
        name="Pension (employer)",
        liability_account="pension_payable",
        expense_account="payroll_expense_pension",
    ),
    income_tax=tax_rule(deduction_caps=(DeductionCap("pension", None),)),
    payroll_levies=(
        PayrollLevyRule(
            code="LEVY",
            name="Training levy",
            authority="Levy board",
            base_categories=ALL_CASH,
            rate_ppm=10_000,
            rounding=HALF_UP,
            due=DUE,
            source="fixture",
            liability_account="training_levy_payable",
            expense_account="payroll_expense_training_levy",
        ),
    ),
)


def kenya_on_the_engine(monkeypatch: pytest.MonkeyPatch, *rule_sets: CountryRuleSet) -> None:
    profiles = tuple(
        replace(profile, status=TaxStatus.ACTIVE) if profile.code == "KE" else profile
        for profile in multicountry.COUNTRY_PROFILES
    )
    monkeypatch.setattr(multicountry, "COUNTRY_PROFILES", profiles)
    monkeypatch.setattr(registry, "REGISTERED_RULE_SETS", rule_sets)


def kenyan_org(email: str) -> tuple[uuid.UUID, dict[str, str]]:
    org_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name="Engine Test Co", country_code="KE"))
    create_account_with_membership(org_id, Role.ADMIN, email=email)
    return org_id, auth_headers(login(email)["access_token"])


def payslips_of(headers: dict[str, str], pay_run_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/v1/pay-runs/{pay_run_id}/payslips", headers=headers)
    assert response.status_code == 200, response.text
    payslips: list[dict[str, Any]] = response.json()
    return payslips
