from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "sim-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def test_simulate_payslip_for_a_raise_persists_nothing() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    employee_id = create_employee(org_id, employee_number="EMP-SIM")

    baseline = client.post(
        f"/api/v1/simulation/payslip/{employee_id}",
        headers=headers,
        json={"period_end": "2026-01-31"},
    )
    assert baseline.status_code == 200, baseline.text

    raised = client.post(
        f"/api/v1/simulation/payslip/{employee_id}",
        headers=headers,
        json={"period_end": "2026-01-31", "basic_minor": 900_000_00},
    )
    assert raised.status_code == 200
    assert raised.json()["gross_minor"] > baseline.json()["gross_minor"]

    # Nothing was persisted by the simulation — no pay run exists at all.
    pay_runs = client.get("/api/v1/pay-runs", headers=headers)
    assert pay_runs.status_code == 200
    assert pay_runs.json() == []


def test_simulate_pay_run_totals_across_org() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="sim-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-SIM2")

    response = client.post(
        "/api/v1/simulation/pay-run",
        headers=headers,
        json={
            "period_end": "2026-01-31",
            "overrides": {
                str(employee_id): {"period_end": "2026-01-31", "basic_minor": 700_000_00}
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert str(employee_id) in body["by_employee_id"]
    assert body["total_gross_minor"] == body["by_employee_id"][str(employee_id)]["gross_minor"]


def test_benefit_assign_list_and_end() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="benefit-admin@example.com")
    employee_email = "benefited@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(org_id, account_id=employee_account_id, employee_number="EMP-BEN")

    assign = client.post(
        f"/api/v1/benefits/employees/{employee_id}",
        headers=headers,
        json={
            "name": "Health Insurance",
            "frequency": "monthly",
            "effective_date": "2026-01-01",
            "value_minor": 20000,
        },
    )
    assert assign.status_code == 201, assign.text
    benefit_id = assign.json()["id"]

    listing = client.get(f"/api/v1/benefits/employees/{employee_id}", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    my_headers = auth_headers(login(employee_email)["access_token"])
    my_benefits = client.get("/api/v1/benefits/me", headers=my_headers)
    assert my_benefits.status_code == 200
    assert len(my_benefits.json()) == 1

    ended = client.post(
        f"/api/v1/benefits/{benefit_id}/end", headers=headers, json={"end_date": "2026-06-30"}
    )
    assert ended.status_code == 200
    assert ended.json()["end_date"] == "2026-06-30"


def test_dashboard_summary_and_deadlines_reflect_activity() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="dash-admin@example.com")
    create_employee(org_id, employee_number="EMP-DASH")

    empty_summary = client.get("/api/v1/dashboard/summary", headers=headers)
    assert empty_summary.status_code == 200
    assert empty_summary.json()["active_employee_count"] == 1
    assert empty_summary.json()["last_completed_pay_run"] is None

    run = create_and_lock_pay_run(headers)

    summary = client.get("/api/v1/dashboard/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["last_completed_pay_run"]["id"] == run["id"]
    assert summary.json()["outstanding_liability_minor"] > 0

    deadlines = client.get("/api/v1/dashboard/deadlines", headers=headers)
    assert deadlines.status_code == 200
    assert len(deadlines.json()) > 0
    due_dates = [d["due_date"] for d in deadlines.json()]
    assert due_dates == sorted(due_dates)
