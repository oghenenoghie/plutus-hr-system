"""Analytics & Insights API: access, filters, tenant isolation, and figures
that reconcile with their authoritative sources. One synthetic organisation
(and a second one, to prove isolation) is built once for the module.

Period under test: 1 Jan to 30 Jun 2026, compared with Jul to Dec 2025.

Employees (joined; department; location; type):
  H  2024-03-01  Sales  Lagos  permanent   heads Sales (department manager)
  A  2025-02-01  Sales  Lagos  permanent
  B  2026-02-15  Sales  Abuja  fixed term  hired in the period
  C  2023-01-10  Ops    Abuja  permanent   left 2026-04-30 (final settlement)
  D  2025-11-01  Ops    Lagos  part time   hired in the comparison period
"""

import io
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

import pytest

from app.core.db import tenant_session
from app.domain.payroll.frequency import PayFrequency
from app.models import Employee, EmploymentType, Role
from app.models.attendance_record import AttendanceRecord
from app.models.branch import Branch
from app.models.candidate import Candidate, CandidateStatus
from app.models.job_posting import JobPosting, JobPostingStatus
from app.models.leave import LeaveRequest, LeaveStatus, LeaveType
from app.models.performance_review import PerformanceReview, PerformanceReviewStatus
from app.models.public_holiday import PublicHoliday
from app.models.shift import Shift
from app.models.shift_roster_entry import ShiftRosterEntry
from app.services.leave import leave_balance
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_and_lock_pay_run,
    create_department,
    create_org,
    get_membership_id,
    login,
)

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-06-30"}


@dataclass
class World:
    org_id: uuid.UUID
    admin: dict[str, str]
    hr: dict[str, str]
    hr_membership: uuid.UUID
    auditor: dict[str, str]
    dept_manager: dict[str, str]
    employee: dict[str, str]
    sales: uuid.UUID
    ops: uuid.UUID
    lagos: uuid.UUID
    employees: dict[str, uuid.UUID]
    foreign_department: uuid.UUID
    foreign_admin: dict[str, str]


def _headers(org_id: uuid.UUID, role: Role, tag: str) -> tuple[uuid.UUID, dict[str, str]]:
    email = f"analytics-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    account_id = create_account_with_membership(org_id, role, email=email)
    return account_id, auth_headers(login(email)["access_token"])


def _employee(
    db: Any,
    org_id: uuid.UUID,
    number: str,
    *,
    joined: date,
    department: uuid.UUID | None,
    branch: uuid.UUID | None,
    kind: EmploymentType = EmploymentType.PERMANENT,
    born: date | None = None,
    account_id: uuid.UUID | None = None,
) -> uuid.UUID:
    employee_id = uuid.uuid4()
    db.add(
        Employee(
            id=employee_id,
            org_id=org_id,
            account_id=account_id,
            employee_number=number,
            full_name=f"Employee {number}",
            state_of_residence="Lagos",
            employment_type=kind,
            date_of_joining=joined,
            date_of_birth=born,
            tin=f"1234567{number[-1]}-0001",
            department_id=department,
            branch_id=branch,
            job_title="Analyst" if number != "H" else "Head of Sales",
            basic_minor=300_000_00,
            housing_minor=150_000_00,
            transport_minor=50_000_00,
            pay_frequency=PayFrequency.MONTHLY,
        )
    )
    return employee_id


@pytest.fixture(scope="module")
def world() -> World:
    org_id = create_org()
    _, admin = _headers(org_id, Role.ADMIN, "admin")
    hr_account, hr = _headers(org_id, Role.HR_MANAGER, "hr")
    _, auditor = _headers(org_id, Role.AUDITOR, "auditor")
    head_account, dept_manager = _headers(org_id, Role.DEPARTMENT_MANAGER, "head")
    _, employee = _headers(org_id, Role.EMPLOYEE, "employee")

    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=admin)
    assert seeded.status_code == 200, seeded.text

    ops = create_department(org_id, name="Ops")
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        lagos, abuja = uuid.uuid4(), uuid.uuid4()
        db.add(Branch(id=lagos, org_id=org_id, name="Lagos HQ"))
        db.add(Branch(id=abuja, org_id=org_id, name="Abuja"))
        db.flush()
        h = _employee(
            db,
            org_id,
            "H",
            joined=date(2024, 3, 1),
            department=None,
            branch=lagos,
            born=date(1985, 5, 5),
            account_id=head_account,
        )
    sales = create_department(org_id, name="Sales", manager_id=h)
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.get(Employee, h).department_id = sales  # type: ignore[union-attr]
        ids = {
            "H": h,
            "A": _employee(
                db,
                org_id,
                "A",
                joined=date(2025, 2, 1),
                department=sales,
                branch=lagos,
                born=date(1990, 1, 1),
            ),
            "B": _employee(
                db,
                org_id,
                "B",
                joined=date(2026, 2, 15),
                department=sales,
                branch=abuja,
                kind=EmploymentType.FIXED_TERM,
                born=date(2000, 6, 1),
            ),
            "C": _employee(
                db,
                org_id,
                "C",
                joined=date(2023, 1, 10),
                department=ops,
                branch=abuja,
                born=date(1975, 3, 3),
            ),
            "D": _employee(
                db,
                org_id,
                "D",
                joined=date(2025, 11, 1),
                department=ops,
                branch=lagos,
                kind=EmploymentType.PART_TIME,
            ),
        }

    create_and_lock_pay_run(
        admin,
        period_start="2026-01-01",
        period_end="2026-01-31",
        employee_ids=[ids["H"], ids["A"], ids["C"], ids["D"]],
    )
    create_and_lock_pay_run(
        admin,
        period_start="2026-02-01",
        period_end="2026-02-28",
        employee_ids=[ids["H"], ids["A"], ids["B"], ids["C"], ids["D"]],
    )
    settled = client.post(
        f"/api/v1/final-settlements/{ids['C']}",
        headers=admin,
        json={
            "termination_date": "2026-04-30",
            "gratuity_minor": 0,
            "leave_days_paid_out": 0,
            "leave_payout_minor": 0,
        },
    )
    assert settled.status_code == 201, settled.text

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        for who, kind, start, end, days, status in (
            ("A", LeaveType.ANNUAL, date(2026, 3, 2), date(2026, 3, 6), 5, LeaveStatus.APPROVED),
            ("B", LeaveType.SICK, date(2026, 4, 1), date(2026, 4, 2), 2, LeaveStatus.APPROVED),
            ("D", LeaveType.ANNUAL, date(2026, 5, 4), date(2026, 5, 5), 2, LeaveStatus.PENDING),
            ("H", LeaveType.ANNUAL, date(2026, 6, 1), date(2026, 6, 3), 3, LeaveStatus.REJECTED),
        ):
            db.add(
                LeaveRequest(
                    org_id=org_id,
                    employee_id=ids[who],
                    leave_type=kind,
                    start_date=start,
                    end_date=end,
                    days=days,
                    status=status,
                )
            )
        shift_id = uuid.uuid4()
        db.add(
            Shift(
                id=shift_id, org_id=org_id, name="Day", start_time=time(8, 0), end_time=time(17, 0)
            )
        )
        db.add(PublicHoliday(org_id=org_id, holiday_date=date(2026, 3, 12), name="Test holiday"))
        db.flush()
        # A is rostered on the 2nd (approved leave), 9th, 10th, 11th and the
        # 12th (a holiday): three shifts count; on time, late, absent.
        for day in (2, 9, 10, 11, 12):
            db.add(
                ShiftRosterEntry(
                    org_id=org_id,
                    employee_id=ids["A"],
                    shift_id=shift_id,
                    work_date=date(2026, 3, day),
                )
            )
        for day, clock_in in ((9, time(6, 55)), (10, time(7, 20))):  # UTC; WAT is +1
            db.add(
                AttendanceRecord(
                    org_id=org_id,
                    employee_id=ids["A"],
                    work_date=date(2026, 3, day),
                    clock_in_at=datetime.combine(date(2026, 3, day), clock_in, tzinfo=UTC),
                    clock_out_at=datetime.combine(date(2026, 3, day), time(16, 0), tzinfo=UTC),
                )
            )
        db.add(
            PerformanceReview(
                org_id=org_id,
                employee_id=ids["A"],
                period_start=date(2026, 1, 1),
                period_end=date(2026, 6, 30),
                status=PerformanceReviewStatus.SUBMITTED,
                rating=4,
                submitted_date=date(2026, 6, 30),
            )
        )
        db.add(
            PerformanceReview(
                org_id=org_id,
                employee_id=ids["B"],
                period_start=date(2026, 1, 1),
                period_end=date(2026, 6, 30),
                status=PerformanceReviewStatus.DRAFT,
            )
        )
        posting = uuid.uuid4()
        db.add(
            JobPosting(
                id=posting,
                org_id=org_id,
                department_id=sales,
                title="Sales associate",
                status=JobPostingStatus.OPEN,
                opened_date=date(2026, 1, 5),
            )
        )
        db.flush()
        for name, status in (
            ("Ada", CandidateStatus.HIRED),
            ("Bayo", CandidateStatus.INTERVIEWING),
        ):
            db.add(
                Candidate(
                    org_id=org_id,
                    job_posting_id=posting,
                    full_name=name,
                    status=status,
                    applied_date=date(2026, 2, 10),
                )
            )

    foreign_org = create_org()
    _, foreign_admin = _headers(foreign_org, Role.ADMIN, "foreign")
    foreign_department = create_department(foreign_org, name="Foreign")
    with tenant_session(foreign_org, uuid.uuid4(), "admin") as db:
        for number in ("X1", "X2"):
            _employee(
                db,
                foreign_org,
                number,
                joined=date(2025, 1, 1),
                department=foreign_department,
                branch=None,
            )

    return World(
        org_id=org_id,
        admin=admin,
        hr=hr,
        hr_membership=get_membership_id(org_id, hr_account),
        auditor=auditor,
        dept_manager=dept_manager,
        employee=employee,
        sales=sales,
        ops=ops,
        lagos=lagos,
        employees=ids,
        foreign_department=foreign_department,
        foreign_admin=foreign_admin,
    )


def _get(path: str, headers: dict[str, str], **params: Any) -> Any:
    return client.get(f"/api/v1/analytics{path}", headers=headers, params={**PERIOD, **params})


def _kpi(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(m for m in body["kpis"] if m["key"] == key)


def _rows(breakdown: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["label"]: r for r in breakdown["rows"]}


# --- access -----------------------------------------------------------------


def test_access_mirrors_role_defaults(world: World) -> None:
    def allowed(headers: dict[str, str]) -> set[str]:
        body = client.get("/api/v1/analytics/access", headers=headers).json()
        return {s["section"] for s in body["sections"] if s["allowed"]}

    assert allowed(world.admin) == {
        "workforce",
        "payroll",
        "attendance",
        "leave",
        "recruitment",
        "performance",
        "compliance",
        "financial",
    }
    assert allowed(world.hr) == {"workforce", "attendance", "leave"}
    assert allowed(world.auditor) == {
        "workforce",
        "payroll",
        "attendance",
        "leave",
        "recruitment",
        "performance",
        "compliance",
    }
    assert allowed(world.dept_manager) == {"workforce", "leave"}
    body = client.get("/api/v1/analytics/access", headers=world.employee).json()
    assert body["can_view"] is False
    assert body["can_export"] is False


def test_requests_without_a_token_are_rejected() -> None:
    response = client.get("/api/v1/analytics/workforce")
    assert response.status_code in (401, 403)


def test_employee_role_cannot_reach_any_analytics(world: World) -> None:
    for path in ("/overview", "/workforce", "/filter-options", "/records/employees"):
        assert _get(path, world.employee).status_code == 403, path


def test_restricted_sections_are_refused_through_the_api(world: World) -> None:
    assert _get("/payroll", world.hr).status_code == 403
    assert _get("/financial", world.auditor).status_code == 403
    assert _get("/records/payslips", world.hr).status_code == 403
    assert _get("/sections/payroll/export", world.hr).status_code == 403
    assert _get("/compliance", world.dept_manager).status_code == 403


def test_responses_are_never_cached(world: World) -> None:
    response = _get("/workforce", world.admin)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"


# --- filter validation ------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"date_from": "2026-07-01", "date_to": "2026-06-30"}, "after"),
        ({"date_from": "2022-01-01", "date_to": "2026-06-30"}, "36 months"),
        ({"compare": "last_decade"}, "compare"),
        ({"employment_type": "astronaut"}, "employment type"),
        ({"status": "on_holiday"}, "employment status"),
        ({"payroll_status": "draft"}, "payroll_status"),
        ({"country": "KE"}, "not production-enabled"),
        ({"country": "ZZ"}, "unknown country"),
        ({"department_id": str(uuid.uuid4())}, "unknown department"),
    ],
)
def test_invalid_filters_are_rejected(world: World, params: dict[str, str], message: str) -> None:
    response = _get("/workforce", world.admin, **params)
    assert response.status_code == 422, response.text
    assert message in response.json()["detail"]


def test_another_organisations_department_reads_as_unknown(world: World) -> None:
    response = _get("/workforce", world.admin, department_id=str(world.foreign_department))
    assert response.status_code == 422
    assert response.json()["detail"] == "unknown department"


# --- workforce --------------------------------------------------------------


def test_workforce_counts_reconcile(world: World) -> None:
    body = _get("/workforce", world.admin).json()
    assert _kpi(body, "headcount")["value"] == 4  # H, A, B, D
    assert _kpi(body, "headcount")["previous_value"] == 4  # H, A, C, D on 31 Dec 2025
    assert _kpi(body, "hires")["value"] == 1
    assert _kpi(body, "hires")["previous_value"] == 1
    assert _kpi(body, "departures")["value"] == 1
    assert _kpi(body, "departures")["previous_value"] == 0
    assert _kpi(body, "departures")["change_pct"] is None  # from zero
    assert _kpi(body, "turnover")["value"] == 25.0  # 1 / ((4 + 4) / 2)
    assert _kpi(body, "active")["value"] == 4

    trend = {p["period"]: p["value"] for p in body["headcount_trend"]["series"][0]["points"]}
    assert trend["2026-01"] == 4 and trend["2026-02"] == 5 and trend["2026-04"] == 5
    assert trend["2026-05"] == 4  # C counted through their last day, 30 April

    departments = _rows(body["by_department"])
    assert departments["Sales"]["value"] == 3 and departments["Ops"]["value"] == 1
    assert _rows(body["by_employment_type"])["Fixed term"]["value"] == 1
    ages = _rows(body["age_bands"])
    assert ages["Not recorded"]["value"] == 1  # D
    assert ages["25–34"]["suppressed"] is True  # A alone; fewer than 3


def test_other_organisations_are_never_counted(world: World) -> None:
    body = _get("/workforce", world.foreign_admin).json()
    assert _kpi(body, "headcount")["value"] == 2
    assert "Sales" not in _rows(body["by_department"])


def test_department_manager_sees_only_their_department(world: World) -> None:
    body = _get("/workforce", world.dept_manager).json()
    assert body["meta"]["department_scope"] == [str(world.sales)]
    assert _kpi(body, "headcount")["value"] == 3  # H, A, B
    assert set(_rows(body["by_department"])) == {"Sales"}
    assert _get("/workforce", world.dept_manager, department_id=str(world.ops)).status_code == 403
    options = client.get("/api/v1/analytics/filter-options", headers=world.dept_manager).json()
    assert [d["label"] for d in options["departments"]] == ["Sales"]


def test_location_and_type_filters_narrow_the_figures(world: World) -> None:
    body = _get("/workforce", world.admin, location_id=str(world.lagos)).json()
    assert _kpi(body, "headcount")["value"] == 3  # H, A, D
    body = _get("/workforce", world.admin, employment_type="part_time").json()
    assert _kpi(body, "headcount")["value"] == 1


# --- payroll ----------------------------------------------------------------


def test_payroll_matches_the_payroll_cost_report(world: World) -> None:
    body = _get("/payroll", world.admin).json()
    report = client.get(
        "/api/v1/reports/payroll-cost",
        headers=world.admin,
        params={"from_date": "2026-01-01", "to_date": "2026-06-30"},
    ).json()
    assert _kpi(body, "cost")["value"] == sum(line["employer_cost_minor"] for line in report)
    assert _kpi(body, "gross")["value"] == sum(line["gross_minor"] for line in report)
    assert _kpi(body, "net")["value"] == sum(line["net_minor"] for line in report)
    assert _kpi(body, "cost")["currency"] == "NGN"
    per_department: dict[str, int] = {}
    for line in report:
        per_department[line["department_name"]] = (
            per_department.get(line["department_name"], 0) + line["employer_cost_minor"]
        )
    assert {r["label"]: r["value"] for r in body["cost_by_department"]["rows"]} == per_department
    assert _kpi(body, "employees")["value"] == 5
    statuses = _rows(body["runs_by_status"])
    # January and February, plus the exit payslip C's final settlement locked.
    assert statuses["Locked"]["value"] == 3
    gross = {p["period"]: p["value"] for p in body["cost_trend"]["series"][0]["points"]}
    assert gross["2026-03"] is None  # no pay run: a gap, not a zero


def test_payroll_deductions_add_up(world: World) -> None:
    body = _get("/payroll", world.admin).json()
    gross = _kpi(body, "gross")["value"]
    net = _kpi(body, "net")["value"]
    assert _kpi(body, "deductions")["value"] == gross - net
    stacked = body["deduction_trend"]["series"]
    total = sum(p["value"] or 0 for s in stacked for p in s["points"])
    assert total == gross - net


def test_small_pay_groups_are_hidden_from_callers_without_payroll_register_access(
    world: World,
) -> None:
    granted = client.put(
        f"/api/v1/memberships/{world.hr_membership}/permissions/override",
        headers=world.admin,
        json={"permission": "analytics.payroll.view", "granted": True},
    )
    assert granted.status_code == 200, granted.text
    body = _get("/payroll", world.hr).json()
    rows = _rows(body["cost_by_department"])
    assert rows["Ops"]["suppressed"] is True and rows["Ops"]["value"] is None  # C, D
    assert rows["Sales"]["suppressed"] is False  # H, A, B
    assert _get("/records/payslips", world.hr).status_code == 403
    admin_rows = _rows(_get("/payroll", world.admin).json()["cost_by_department"])
    assert admin_rows["Ops"]["suppressed"] is False

    revoked = client.delete(
        f"/api/v1/memberships/{world.hr_membership}/permissions/override/analytics.payroll.view",
        headers=world.admin,
    )
    assert revoked.status_code == 200, revoked.text
    assert _get("/payroll", world.hr).status_code == 403


# --- attendance, leave, recruitment, performance ----------------------------


def test_attendance_is_measured_against_rostered_shifts(world: World) -> None:
    body = _get("/attendance", world.admin).json()
    assert _kpi(body, "attendance_rate")["value"] == 66.67  # 2 of 3 counted shifts
    assert _kpi(body, "absence_rate")["value"] == 33.33
    assert _kpi(body, "late_arrivals")["value"] == 1  # 08:20 WAT against an 08:00 start
    assert _kpi(body, "excluded_shifts")["value"] == 2  # leave on the 2nd, holiday on the 12th
    assert _kpi(body, "average_hours")["value"] == 8.88  # (9h05 + 8h40) / 2


def test_leave_figures_and_balances_match_the_leave_service(world: World) -> None:
    body = _get("/leave", world.admin).json()
    assert _kpi(body, "requests")["value"] == 4
    assert _kpi(body, "approved_days")["value"] == 7
    assert _kpi(body, "approval_rate")["value"] == 66.67
    assert _kpi(body, "pending_requests")["value"] == 1
    with tenant_session(world.org_id, uuid.uuid4(), "admin") as db:
        current = [db.get(Employee, world.employees[k]) for k in ("H", "A", "B", "D")]
        expected = [leave_balance(db, e, date(2026, 6, 30)) for e in current if e is not None]
    assert _kpi(body, "average_balance")["value"] == round(sum(expected) / len(expected), 2)
    assert _rows(body["days_by_type"])["Annual"]["value"] == 5


def test_recruitment_lists_what_it_cannot_measure(world: World) -> None:
    body = _get("/recruitment", world.admin).json()
    assert _kpi(body, "applications")["value"] == 2
    assert _kpi(body, "open_vacancies")["value"] == 1
    assert {u["key"] for u in body["meta"]["unsupported"]} == {
        "time_to_hire",
        "offer_acceptance",
        "source",
        "funnel",
    }


def test_performance_ratings_are_shown_as_recorded(world: World) -> None:
    body = _get("/performance", world.admin).json()
    assert _kpi(body, "review_completion")["value"] == 50.0
    assert [r["label"] for r in body["rating_distribution"]["rows"]] == ["4"]
    assert _rows(body["rating_by_department"])["Sales"]["suppressed"] is True


# --- compliance and financial -----------------------------------------------


def test_compliance_reads_the_statutory_liabilities(world: World) -> None:
    body = _get("/compliance", world.admin).json()
    liabilities = client.get("/api/v1/statutory-liabilities", headers=world.admin).json()
    in_period = [line for line in liabilities if "2026-01-01" <= line["period_end"] <= "2026-06-30"]
    assert _kpi(body, "total")["value"] == sum(line["amount_minor"] for line in in_period)
    assert _kpi(body, "paye")["value"] == sum(
        line["amount_minor"] for line in in_period if line["scheme"] == "paye"
    )
    categories = {r["key"] for r in body["obligations_by_category"]["rows"]}
    assert "payroll_tax" in categories and "vat" not in categories
    dues = [d["due_date"] for d in body["deadlines"]]
    assert dues == sorted(dues)


def test_financial_reconciles_with_the_income_statement(world: World) -> None:
    body = _get("/financial", world.admin, date_from="2026-01-01", date_to="2026-12-31").json()
    statement = client.get(
        "/api/v1/financial-statements/income-statement", headers=world.admin
    ).json()
    assert _kpi(body, "expenses")["value"] == statement["total_expenses_minor"]
    assert _kpi(body, "revenue")["value"] == statement["total_revenue_minor"]
    assert _kpi(body, "payroll")["value"] > 0
    assert _kpi(body, "payroll_share")["value"] == 100.0  # payroll is the only expense here


def test_country_that_is_not_enabled_fails_closed(world: World) -> None:
    response = _get("/compliance", world.admin, country="GH")
    assert response.status_code == 422
    assert "not production-enabled" in response.json()["detail"]


# --- overview, drill-down and export ----------------------------------------


def test_overview_shows_only_permitted_sections(world: World) -> None:
    admin = _get("/overview", world.admin).json()
    assert {m["key"] for m in admin["kpis"]} >= {
        "headcount",
        "cost",
        "attendance_rate",
        "pending_requests",
        "processing_status",
    }
    auditor = _get("/overview", world.auditor).json()
    assert "financial" in auditor["restricted_sections"]
    assert "payroll" not in auditor["restricted_sections"]
    head = _get("/overview", world.dept_manager).json()
    assert head["payroll_cost_trend"] is None
    assert "payroll" in head["restricted_sections"]
    assert head["deadlines"] is None


def test_drill_down_pages_and_returns_no_pay_on_employee_rows(world: World) -> None:
    page = _get("/records/employees", world.admin, page_size=2).json()
    assert page["total"] == 4 and len(page["rows"]) == 2
    assert not {"basic_minor", "gross", "net"} & set(page["rows"][0])
    second = _get("/records/employees", world.admin, page_size=2, page=2).json()
    assert {r["employee_number"] for r in page["rows"]}.isdisjoint(
        {r["employee_number"] for r in second["rows"]}
    )
    assert _get("/records/employees", world.admin, page_size=101).status_code == 422
    assert _get("/records/nothing", world.admin).status_code == 422
    departures = _get("/records/departures", world.admin).json()
    assert [r["employee_number"] for r in departures["rows"]] == ["C"]


def test_exports_carry_metadata_and_are_audited(world: World) -> None:
    csv_response = _get("/sections/workforce/export", world.admin, format="csv")
    assert csv_response.status_code == 200, csv_response.text
    text = csv_response.content.decode("utf-8-sig")
    assert text.startswith("Workforce analytics")
    assert "Organisation: Test Co" in text and "Period: 2026-01-01 to 2026-06-30" in text
    assert "Currency: NGN" in text and "Definition" in text
    assert csv_response.headers["cache-control"] == "private, no-store"

    xlsx = _get("/records/employees/export", world.admin, format="xlsx")
    assert xlsx.status_code == 200
    with zipfile.ZipFile(io.BytesIO(xlsx.content)) as archive:
        assert "Employee H" in archive.read("xl/worksheets/sheet1.xml").decode()

    pdf = _get("/sections/payroll/export", world.auditor, format="pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    log = client.get("/api/v1/audit-log", headers=world.admin).json()
    exported = [e for e in log if e["action"] == "analytics.export"]
    assert {
        e["event_metadata"].get("report") or e["event_metadata"].get("dataset") for e in exported
    } >= {
        "workforce",
        "employees",
        "payroll",
    }


def test_exports_need_the_export_permission(world: World) -> None:
    response = _get("/sections/workforce/export", world.dept_manager)
    assert response.status_code == 403
    assert "analytics.reports.export" in response.json()["detail"]
