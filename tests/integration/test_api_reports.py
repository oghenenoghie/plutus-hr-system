from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_employee,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "reports-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def test_payroll_cost_by_department_across_two_locked_runs() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)

    eng = client.post("/api/v1/departments", headers=headers, json={"name": "Engineering"})
    assert eng.status_code == 201, eng.text
    sales = client.post("/api/v1/departments", headers=headers, json={"name": "Sales"})
    assert sales.status_code == 201, sales.text

    eng_employee_id = create_employee(org_id, employee_number="EMP-RPT-1")
    sales_employee_id = create_employee(org_id, employee_number="EMP-RPT-2")
    client.patch(
        f"/api/v1/employees/{eng_employee_id}",
        headers=headers,
        json={"department_id": eng.json()["id"]},
    )
    client.patch(
        f"/api/v1/employees/{sales_employee_id}",
        headers=headers,
        json={"department_id": sales.json()["id"]},
    )

    run1 = create_and_lock_pay_run(headers, employee_ids=[eng_employee_id, sales_employee_id])
    run2 = create_and_lock_pay_run(
        headers,
        period_start="2026-02-01",
        period_end="2026-02-28",
        employee_ids=[eng_employee_id, sales_employee_id],
    )

    report = client.get("/api/v1/reports/payroll-cost", headers=headers)
    assert report.status_code == 200, report.text
    lines = report.json()

    # Two departments x two locked runs = four cells.
    assert len(lines) == 4
    pay_run_ids = {line["pay_run_id"] for line in lines}
    assert pay_run_ids == {run1["id"], run2["id"]}
    department_names = {line["department_name"] for line in lines}
    assert department_names == {"Engineering", "Sales"}
    for line in lines:
        assert line["employee_count"] == 1
        assert line["gross_minor"] > 0
        assert line["employer_cost_minor"] >= line["gross_minor"]


def test_payroll_cost_report_excludes_draft_and_reversed_runs() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="reports-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-RPT-3")

    draft = client.post(
        "/api/v1/pay-runs",
        headers=headers,
        json={"period_start": "2026-03-01", "period_end": "2026-03-31", "frequency": "monthly"},
    )
    assert draft.status_code == 201, draft.text

    locked = create_and_lock_pay_run(
        headers, period_start="2026-01-01", period_end="2026-01-31", employee_ids=[employee_id]
    )
    reverse = client.post(f"/api/v1/pay-runs/{locked['id']}/reverse", headers=headers)
    assert reverse.status_code == 200, reverse.text

    report = client.get("/api/v1/reports/payroll-cost", headers=headers)
    assert report.status_code == 200, report.text
    assert report.json() == []
