# Analytics & Insights: architecture

Status: **implemented** (backend `app/services/analytics/`, `app/api/v1/analytics.py`; frontend `/analytics`). This document records the audit the design rests on, the decisions taken, the data flow and how to extend the module. Metric formulas are in [`analytics-metrics.md`](analytics-metrics.md); permissions, isolation and exports are in [`analytics-security.md`](analytics-security.md).

## 1. Audit: what the codebase provides

| Area | What exists | Used for analytics |
|---|---|---|
| Backend | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16. Every request runs in `tenant_session`, which sets `app.current_org`, and row-level security (RLS) policies on every tenant table filter on it. The API connects as a non-superuser role (`REQUIRE_RLS_ENFORCED`). | Every analytics query runs through `get_tenant_db`, so RLS applies. Queries also filter on `org_id` explicitly, as defence in depth. |
| Frontend | Next.js 16 App Router, React 19, Tailwind 4, `lucide-react`. There is no component library and no charting library. The dashboard draws its one chart as hand-written SVG "rather than a new charting dependency". | Charts are reusable hand-written SVG components in the same design system. Recharts was not added (decision A1). |
| Auth / RBAC | JWT claims carry `role`. `require_roles` checks the coarse role; `require_permission` checks a fine-grained `Permission`, using role defaults plus per-membership overrides (`membership_permission_overrides`). | Ten `analytics.*` permissions are added to the existing `Permission` enum (decision A3). |
| Employees | `employees`: `department_id`, `branch_id` (a location), `job_title`, `employment_type`, `lifecycle_state` (active / suspended / terminated), `date_of_joining`, `date_of_birth`, `annual_leave_entitlement_days`. Termination happens only through a final settlement, so `final_settlements.termination_date` is the departure date. | Headcount, hires, departures, turnover, all breakdowns, tenure and age bands. |
| Payroll | `pay_runs` (draft / validated / locked / reversed; `run_type`; `period_end`). `payslips` hold gross, employer and employee pension, NHF, PAYE, net and `rule_version_id`. `overtime_entries` (paid ones carry `pay_run_id`). | Payroll trends and breakdowns. Locked runs only by default, matching `reports.payroll_cost_by_department`. |
| Attendance | `attendance_records` (clock in/out, timestamptz). `shift_roster_entries` (employee, shift, date). `shifts` (start/end time). `public_holidays`. | Attendance rate, lateness and hours, measured against **rostered** shifts. There is no other schedule to measure against. |
| Leave | `leave_requests` (type, status, days, start/end). The balance rule is `services/leave.approved_days_taken`. | Status, type, monthly trend, utilisation, pending queue, balance bands. |
| Recruitment | `job_postings` (open/closed). `candidates` hold only their **current** status and `applied_date`. | Vacancies, applications and a current-stage snapshot. Time to hire, offer acceptance, source and funnel conversion are **unsupported** (no stage history, hire date or source field). |
| Performance | `performance_reviews` (status, `rating` as an integer with no fixed scale, period). `training_enrollments`. | Completion rates, rating distribution as recorded, training completion. |
| Tax & compliance | `statutory_liabilities` (PAYE, pension, NHF, NSITF, ITF, WHT; status; validated `due_date` from the rule version). `bills.vat_minor` is input VAT. The multi-country catalogue (`app/compliance/multicountry.py`). | Obligations by category, outstanding and upcoming deadlines, input VAT. Output VAT is not modelled. The country filter fails closed for countries that aren't enabled. |
| Accounting | `journal_entries` (`entry_date` is the accounting date; `currency`; `source_type`). `ledger_entries` (account code, debit/credit, `department_id`). `chart_accounts` (type). `budgets` and `budget_lines`. | Revenue, operating expenses, payroll share, department spend, budget vs actual and cash movement. |
| Exports | `services/inventory_report_export.py` (`ReportTable`, CSV with formula-injection guard, PDF via reportlab). | Generalised into `services/report_export.py`, with an XLSX writer added that uses only the standard library. |
| Audit log | `services/audit.record_audit_event`. | Every analytics export is audited. |

Not present, so not shown: legal entities (one organisation is the legal entity), multiple currencies in payroll (every rule version is NG, so NGN), a lateness or attendance policy, candidate stage history and source, output VAT, and dark mode in the design system.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| A1 | Charts are hand-written SVG components (`src/components/analytics/charts/`). | This follows the existing dashboard convention and the design guidance against new charting dependencies. The SVG charts provide everything required: tooltips, keyboard focus, a table view, and accessible names. |
| A2 | Read-only aggregation over the authoritative tables. No summary tables or materialised views. | Correctness and freshness. Every query aggregates in PostgreSQL with `GROUP BY`, so nothing row-level reaches the browser. The query plans are recorded in §6. |
| A3 | Ten new `analytics.*` permissions in the existing enum, with role defaults. One migration adds the enum values. | Reuses the existing fine-grained RBAC, so an organisation can grant or revoke analytics per membership. |
| A4 | Department managers see only the departments they head (`departments.manager_id`). Any other department filter is rejected with 403. | Mirrors the employees API's scoping. |
| A5 | Pay breakdowns hide any group of fewer than 3 people from callers who cannot already see individual pay. Payslip-level drill-down is limited to the roles that can open the payroll register. | Stops averages and small groups revealing one person's salary. |
| A6 | Each metric has one date basis, given in the metrics doc: pay run `period_end` for payroll, `date_of_joining` and `termination_date` for workforce, and so on. | Totals then reconcile with the existing reports, which use the same bases. |
| A7 | Financial metrics are dated by `journal_entries.entry_date`, the accounting date. | Required by the spec. The existing financial statements still read `ledger_entries.created_at` (audit item P7). Totals match them whenever a journal is not backdated, and the difference is documented. |
| A8 | Amounts are grouped by currency and never added across currencies. Payroll currency comes from each payslip's rule version country; ledger currency from `journal_entries.currency`. | Multi-country readiness. Today every amount is NGN. |
| A9 | Filters are validated on the server (`AnalyticsFilters`). The range may be at most 36 months, the start must not be after the end, IDs must be visible to the caller, and a country must be enabled. | So filters can't be bypassed through direct API calls. |
| A10 | Nothing is cached on the server. Responses send `Cache-Control: private, no-store`. Each analytics transaction gets `SET LOCAL statement_timeout = '15s'`. | No cross-tenant cache to get wrong. The timeout protects the database from a pathological range. |
| A11 | Exports come as CSV, XLSX and PDF from the same tables the screen shows. They need `analytics.reports.export` plus the section's own permission, and each one is written to the audit log. | Spec §11. |
| A12 | Unsupported metrics are listed in each response's `unsupported` block, with the reason. | So a gap is never shown as a zero. |

## 3. Data flow

```
Browser (/analytics/*)
  └─ useAnalyticsFilters()  ── URL query string (shareable, validated again on the server)
  └─ analyticsApi.<section>(filters)  ── apiFetch (token refresh, 401 → /login)
        │
FastAPI  app/api/v1/analytics.py
  ├─ get_current_claims → resolve_access()  (permissions + department scope)
  ├─ parse_filters()  → AnalyticsFilters (422 on invalid)
  ├─ SET LOCAL statement_timeout
  └─ services/analytics/<section>.py  (aggregate SQL only)
        └─ PostgreSQL, RLS on app.current_org
  ← typed response (schemas/analytics.py), Cache-Control: no-store
```

Drill-down (`GET /analytics/records/{dataset}`) returns paginated source rows: a page size of at most 100, with only the fields the dataset defines. Exports (`GET /analytics/export/{dataset}`) build a `ReportTable` from the same service call the screen uses.

## 4. Backend layout

| File | Role |
|---|---|
| `app/services/analytics/filters.py` | `AnalyticsFilters`, period arithmetic (current vs comparison period, month buckets) and validation. |
| `app/services/analytics/access.py` | `AnalyticsAccess`: effective permissions, department scope, individual-pay visibility. |
| `app/services/analytics/common.py` | Shared helpers: change and percent change, safe ratios, small-group suppression, employee scoping clauses, currency resolution. |
| `app/services/analytics/workforce.py` … `financial.py` | One module per section. Each is pure aggregation and returns schema objects. |
| `app/services/analytics/overview.py` | Composes KPIs from the section modules, showing only those the caller may see. |
| `app/services/analytics/records.py` | Paginated drill-down datasets. |
| `app/services/analytics/exports.py` | Lays a section response out as a `ReportTable` with metadata rows. |
| `app/schemas/analytics.py` | Response contracts: `Metric`, `Series`, `Breakdown` and per-section models. |
| `app/api/v1/analytics.py` | Endpoints, permission checks, headers and audit. |

## 5. Frontend layout

| Path | Role |
|---|---|
| `src/lib/analytics/types.ts` | TypeScript mirror of `schemas/analytics.py`. |
| `src/lib/analytics/api.ts` | `analyticsApi` (via `apiFetch`) and export downloads. |
| `src/lib/analytics/filters.ts` | URL ⇄ filter state, presets (this month / quarter / year, last 12 months), and comparison options. |
| `src/lib/analytics/format.ts` | Locale formatting (`en-NG`) for counts, percentages, currency (`Intl.NumberFormat` with each amount's own currency), days and hours. |
| `src/components/analytics/` | `AnalyticsShell` (section tabs and filter bar), `KpiCard`, `ChartCard` (chart ⇄ table toggle, loading/empty/error states, definitions), `DataTable`, `RecordsDrawer` (drill-down) and `ExportMenu`. |
| `src/components/analytics/charts/` | `LineChart`, `BarChart` (horizontal/vertical, grouped/stacked), `DonutChart`, shared axis, legend and tooltip. |
| `src/app/(app)/analytics/**/page.tsx` | Ten pages: overview, workforce, payroll, attendance, leave, recruitment, performance, compliance, financial, reports. |

## 6. Performance

### Query shape

- Every section endpoint runs a fixed, small number of grouped queries, independent of the number of rows. No query is issued per employee, pay run or month.
- Months are bucketed in SQL with `to_char(…, 'YYYY-MM')`. Headcount on each month end is one query: a `VALUES` list of dates joined to the employee roster.
- Attendance computes its totals and its month, department, location and weekday groups in **one pass** over the rostered shifts (`GROUP BY GROUPING SETS`), plus one pass for the comparison period. Holidays and approved-leave days are pre-filtered sets joined on the date, not a correlated `EXISTS` per shift. The correlated form took minutes on the dataset below.
- The range is capped at 36 months, drill-down pages at 100 rows and exports at 20,000 rows. Statements time out after 15 s.
- On the frontend, each page makes one request per section. A refetch keeps the previous render at reduced opacity rather than flashing a skeleton.

### Measurements and indexes

Measured on a synthetic local database (`plutus_perf`), not production data:

- 40 organisations of 150 employees each, 6,000 employees in all;
- 786,000 rostered shifts and 707,526 attendance records (24 months);
- 480 pay runs and 72,000 payslips;
- 24,000 leave requests and 1,920 statutory liabilities.

Each section was timed for one organisation over 12 months with the previous-period comparison. The connection was the non-superuser application role, so row-level security was applied. Figures are the median of three runs, warm cache, PostgreSQL 16:

| Section | Median |
|---|---|
| Overview | 250 ms |
| Attendance | 140 ms |
| Payroll | 110 ms |
| Workforce | 95 ms |
| Leave | 50 ms |
| Compliance, financial, recruitment, performance | under 35 ms each |

**No index was added.** Five candidate indexes were built and timed:

- `shift_roster_entries (org_id, work_date)`;
- `payslips (pay_run_id)`;
- `pay_runs (org_id, period_end)`;
- `leave_requests (org_id, start_date)`;
- `statutory_liabilities (org_id, period_end)`.

None made a section meaningfully faster. Attendance was slower with them (270 ms against 140 ms), because the planner preferred the new roster index over the existing `(employee_id, work_date)` unique indexes. The existing indexes the plans use are:

- `uq_roster_employee_date` and `uq_attendance_employee_date` for the roster-to-attendance join;
- `ix_journal_entries_org_entry_date` and `ix_ledger_entries_journal_entry_id` for the ledger;
- `uq_employee_org_number`, whose leading `org_id` serves the employee filters.

Revisit this with `EXPLAIN (ANALYZE, BUFFERS)` if a single organisation's roster passes a few million rows, or if production timings exceed these figures.

## 7. Adding a chart

1. Add the aggregate to the section's service module. Write the SQL with `GROUP BY` and scope employees through `common.employee_scope(...)`, and return a `Series` or `Breakdown` with a `definition`.
2. Add the field to the section's response model in `schemas/analytics.py` and to `src/lib/analytics/types.ts`.
3. Add a unit test for the arithmetic and an integration test that reconciles the figure with its source.
4. Render it on the page with `<ChartCard>` and the matching chart component. Pick the form by its job: a line for trends, a bar for categories, a donut only for parts of a whole with at most 6 parts. Single-series charts use `--primary`; multi-series charts use the validated categorical order in `charts/palette.ts`.
5. Document the formula in `analytics-metrics.md`.

## 8. Known limitations

- Department, location and employment type are each employee's **current** values. Employee history records only status and compensation changes, so a transfer moves all of that person's history to the new department. The existing payroll-cost report behaves the same way.
- The age and tenure snapshots, and leave balances, describe employees as they are now, not at the period end.
- Attendance rate needs rostered shifts. An organisation that only clocks in and out, without a roster, gets "not measurable" rather than a rate.
- There is no recruitment funnel history (see §1).
- Financial figures use the accounting date, while the existing statements use the posting timestamp (A7).
- One organisation is one legal entity. A legal-entity filter will be added when legal entities exist (see `docs/architecture/multicountry-tax.md`).
- The design system has no dark mode, so the charts are light-mode only.
