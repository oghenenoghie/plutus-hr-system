# Analytics & Insights: security

Analytics aggregates the most sensitive data in Plutus: pay, ratings, ages and the ledger. This document describes who may see what, how tenants stay isolated, and how exports are controlled. The rules are enforced in the API. The frontend only decides what to offer.

## 1. Permissions

The existing fine-grained RBAC (`app/domain/permissions.py`, `require_permission`, and per-membership overrides in `membership_permission_overrides`) gains ten permissions. Migration `a3c9e1f7b254` adds them to the override enum.

| Permission | Opens |
|---|---|
| `analytics.view` | The Analytics section and the executive overview. Every analytics endpoint requires it. |
| `analytics.workforce.view` | Workforce analytics and the employee drill-downs. |
| `analytics.payroll.view` | Payroll analytics and pay-run drill-down. |
| `analytics.attendance.view` | Attendance analytics and the rostered-shift drill-down. |
| `analytics.leave.view` | Leave analytics and the leave-request drill-down. |
| `analytics.recruitment.view` | Recruitment analytics and the candidate drill-down. |
| `analytics.performance.view` | Performance analytics and the review drill-down. |
| `analytics.compliance.view` | Tax & compliance analytics and the liability drill-down. |
| `analytics.financial.view` | Financial analytics and the ledger drill-down. |
| `analytics.reports.export` | CSV, XLSX and PDF downloads, on top of the section's own permission. |

## 2. Role defaults

Each default mirrors what the role can **already read through the source module's own API**, so analytics never shows a role an aggregate of data it couldn't see otherwise. A job title grants nothing: only the membership's role and explicit overrides count.

| Role | Sections by default | Export | Basis |
|---|---|---|---|
| Admin (Super Admin) | All | Yes | Holds every permission. Access is still limited to its own organisation; there is no cross-organisation analytics. |
| Payroll Manager, Accountant | All | Yes | They read payroll, the ledger, statutory liabilities, recruitment and reviews today. |
| HR Manager | Workforce, attendance, leave | Yes | The HR manager's employee view is always compensation-masked, and the payroll, accounting, recruitment and review APIs don't admit the role. |
| Department Manager | Workforce, leave, for the departments they head | No | Matches the employees and leave APIs' department scoping. |
| Auditor | All except financial | Yes | Read-only everywhere, but the ledger and statements APIs don't admit the role. |
| Manager (line manager) | None | No | Their access elsewhere is limited to their direct reports, which analytics doesn't model. |
| Employee | None | No | No company-wide analytics. |

An administrator can grant or revoke any analytics permission per membership on the Permissions screen. A grant is honoured everywhere, including the section tabs, which read `GET /analytics/access`. The sidebar lists the role defaults.

## 3. Department scope

For a department manager, `access.resolve_access` finds the employee linked to the account and the departments whose `manager_id` is that employee.

- Every query is limited to employees in those departments.
- A request naming any other department is refused (403).
- Filter options list only their departments.
- A department manager who heads no department gets 403 rather than an empty organisation-wide view.

## 4. Individual figures

- **Small groups.** A pay breakdown group (cost or average gross by department or employment type) of 1 or 2 employees loses its value and keeps only its count, for any caller who can't open the payroll register: anyone other than admin, payroll manager, accountant or auditor. Age bands and department rating averages hide groups of 1 or 2 for **everyone**, because no role reads ages or ratings as an aggregate today.
- **Drill-down fields.** Each dataset returns a fixed set of fields (`services/analytics/records.py`):
  - employee rows never include pay;
  - the payslip dataset requires payroll-register access on top of `analytics.payroll.view`;
  - review rows include the rating only for those roles.
- **Aggregates only.** No chart endpoint returns a row per employee. Drill-down is paginated, at most 100 rows a page, and exports are capped at 20,000 rows.

## 5. Tenant isolation

- Every request runs in `tenant_session`, which sets `app.current_org`. Row-level security on every table filters to it, and the API connects as an ordinary (non-superuser) role in production (`REQUIRE_RLS_ENFORCED`). The integration suite runs as such a role.
- Every analytics query **also** filters on `org_id` explicitly.
- The organisation always comes from the signed token, never from a parameter.
- Department and location IDs are checked against the caller's organisation. Another organisation's ID reads as "unknown department" (422) and can't be probed. The test `test_another_organisations_department_reads_as_unknown` covers this.
- Nothing is cached on the server, so one tenant can never be served another's cached result. Responses send `Cache-Control: private, no-store`, so browsers and shared proxies don't store them either.

## 6. Input validation

`services/analytics/filters.parse_filters` runs before any query:

- **Dates:** at most a 36-month range, `date_from` ≤ `date_to`, nothing before 2000, and `date_to` no more than a year ahead.
- **Comparison and enums:** the comparison mode, employment type, status and payroll status must each be a known value.
- **IDs:** at most 50 per filter.
- **Country:**
  - an unknown country is refused;
  - a country whose rules are not approved fails closed, with `require_configured_country`.

Every query is built with SQLAlchemy and bound parameters; no SQL text includes request input. The one literal statement (`SET LOCAL statement_timeout = '15s'`) is a constant.

## 7. Exports

- An export needs `analytics.reports.export` **and** the section's permission. A payslip export also needs payroll-register access.
- It uses the request's validated, scoped filters, so it can't contain more than the screen shows.
- Each file starts with the report's metadata:
  - organisation;
  - period and comparison;
  - every filter, by name;
  - currency;
  - generation time (WAT) and role;
  - scope;
  - notes and unsupported metrics;
  - each figure's definition.
- CSV cells a spreadsheet would run as a formula are neutralised (`report_export._csv_safe`). The XLSX writer writes text as inline strings, never formulas.
- Every export is written to the audit log as `analytics.export`, with the report or dataset, format, row count and period.

## 8. Availability

- Each analytics transaction sets `statement_timeout` to 15 s. A timed-out report answers 503, asking for a shorter range or fewer filters, instead of holding a connection.
- Section endpoints run a fixed number of grouped queries, whatever the data size.

## 9. Tests

`tests/integration/test_api_analytics.py` runs against PostgreSQL as the non-superuser application role, so RLS is enforced. It covers:

- unauthenticated requests;
- the employee role;
- restricted sections and exports through the API;
- each role's defaults;
- a granted, then revoked, override;
- small-group suppression;
- department-manager scope and its refusal;
- cross-tenant IDs and data;
- every invalid filter;
- payslip drill-down refusal;
- the `no-store` header;
- export audit entries.

`e2e/analytics.spec.ts` in the frontend repository checks the same restrictions on screen and through the API, for an HR manager and an auditor.
