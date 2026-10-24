# Analytics & Insights: metric definitions

Every figure on the analytics screens, with its formula, source records and date basis. Each figure's `definition` field in the API response carries the same wording, and the screens show it behind an (i) and in exports.

## Conventions

- **Period:** a validated `date_from` to `date_to` range, inclusive, of at most 36 months. The default is the last 12 calendar months up to today, in Lagos time.
- **Comparison:**
  - *Previous period* compares a whole-month range with the same number of whole months immediately before it (Q2 with Q1). Any other range is compared with the same number of days immediately before it.
  - *Same period last year* moves both dates back 12 months; 29 February becomes 28 February.
- **Change:** absolute change = current − previous. Percentage change = (current − previous) ÷ |previous| × 100. The percentage is shown only when the previous value exists and isn't zero; "from zero" or "from nothing" has no percentage.
- **No data is not zero:**
  - A period with no source records (no payslips, liabilities, ledger lines or rostered shifts) returns no value, so it is never compared as ₦0.
  - On trend charts a month without data is a gap, not a zero.
- **Rates:** numerator ÷ denominator × 100, to two decimal places. A zero denominator gives no value, never 0%.
- **Money:** integer minor units of the period's currency.
  - The currency is the selected country's currency; only Nigeria (NGN) is enabled.
  - Payroll uses only payslips from that country's rule versions (`NG-…`), and the ledger only journals in that currency. Amounts in different currencies are never added together.
- **Months:** a record counts in the calendar month of its date basis (below), using `date_trunc` in SQL.
- **Department, location, employment type:** each employee's *current* value, because employee history doesn't record transfers. The existing payroll-cost report works the same way.
- **Small groups:** a pay or rating breakdown group of 1 or 2 people is hidden for callers who cannot already see individual figures (see [`analytics-security.md`](analytics-security.md)). Its count stays visible; empty groups are shown.

## 1. Workforce

Source records:

- `employees` (joining date, department, branch, job title, employment type, status, date of birth);
- `final_settlements.termination_date`, the only way an employee is terminated.

| Metric | Formula and basis |
|---|---|
| Total employees (headcount) | Employees with `date_of_joining` ≤ D and either no termination date or `termination_date` ≥ D, where D is the period's last day. Someone is counted through their last day. A terminated employee with no settlement row (no known date) is never counted. |
| Active employees | Employees whose `lifecycle_state` is Active **today**. Status history isn't kept, so there is no comparison. |
| New hires | `date_of_joining` within the period. |
| Employees who left | `termination_date` within the period. |
| Turnover rate | Leavers ÷ average headcount × 100, where average headcount = (headcount the day before the period + headcount on its last day) ÷ 2. |
| Average length of service | Mean of (period end − date of joining) in years (÷ 365.25), over employees in headcount at period end. |
| Headcount trend | Headcount on each month's last day; a month cut short by the range uses the range's last day. |
| Hires and departures | The two counts above, by month. |
| Monthly turnover | Each month's leavers ÷ ((headcount the day before the month + headcount at month end) ÷ 2) × 100. |
| By department, location, employment type, job title | Headcount at period end, grouped. Job title shows the ten largest titles, with the rest folded into Other. |
| Employment status | All in-scope employees by today's status. Terminated covers only those who left within the period. |
| Length of service bands | Completed years at period end: under 1, 1–2, 2–5, 5–10, 10 or more. |
| Age distribution | Completed years of age at period end. A band of 1 or 2 people is hidden for everyone; employees with no date of birth are shown as "Not recorded". |

## 2. Payroll

Source records:

- `payslips` joined to `pay_runs`. By default only **locked** runs count, the same rule as the payroll-cost report (`app/services/reports.py`). The *Locked and validated* option adds validated runs that aren't locked yet. Draft runs are never final and reversed runs are void.
- Paid overtime: `overtime_entries` with status Paid on an included run.

Each run belongs to the month its `period_end` falls in.

| Metric | Formula |
|---|---|
| Total payroll cost | Σ (gross + employer pension). This is the employer cost, the same figure as the payroll-cost report. |
| Gross pay | Σ `gross_minor`. |
| Net pay | Σ `net_minor`. |
| Employer contributions | Σ `pension_employer_minor`. NSITF and ITF are employer obligations recorded as statutory liabilities, so they are reported under Tax & Compliance and not added here. |
| Employee deductions | Gross − net. |
| Deductions by kind | PAYE, employee pension and NHF from their own payslip columns. "Loans, benefits and dues" = gross − PAYE − employee pension − NHF − net. The four add up to gross − net. |
| Average gross pay | Σ gross on **regular** runs ÷ the number of payslips on them. Bonus, 13th-month, arrears and off-cycle runs are excluded so they don't distort it. |
| Employees paid | Distinct employees with an included payslip. |
| Payroll processing status | The status and period end of the latest pay run (any status) ending on or before the period's last day. |
| Overtime paid | Σ `amount_minor` of paid overtime on included runs. It is part of gross pay. |
| By department and employment type | The same sums, grouped by the employee's current department or type. The count is employees paid. |
| Pay runs by status | Every run whose period ends in the range, whatever its status; the payroll-status filter doesn't apply. |

Gross and net are plotted as two separate lines, never stacked. Gross and employer pension are stacked, because together they are the cost.

## 3. Attendance

Source records:

- `shift_roster_entries` (who was expected to work, on which shift, on which day) and `shifts` (start and end time);
- `attendance_records` (clock in and out);
- `public_holidays` and approved `leave_requests`;
- `overtime_entries`.

The roster is the only schedule the application holds, so no single working pattern is assumed for everyone.

| Metric | Formula |
|---|---|
| Counted shift | A rostered shift that isn't on a public holiday and isn't on a day covered by the employee's approved leave. |
| Attendance rate | Counted shifts with a clock-in ÷ counted shifts × 100. With no rostered shifts it has no value ("not measurable"). |
| Absence rate | 100 − the attendance rate, on the same basis. |
| Late arrivals | Attended counted shifts whose clock-in, converted to Lagos time (WAT, `Africa/Lagos`), is after the shift's `start_time`. No grace period is applied, because none is configured. |
| Average hours per shift | Mean of clock-out − clock-in over attended counted shifts that have both. |
| Scheduled and actual hours | Scheduled: the sum of counted shift lengths, with end ≤ start treated as an overnight shift (+24 h). Actual: the sum of clock-out − clock-in on attended counted shifts. |
| Shifts on holidays or leave | Rostered shifts left out of the denominator. |
| Overtime hours | Σ `hours` of approved or paid overtime with a work date in the period. |
| By department, location, weekday | The attendance rate grouped; the count is counted shifts. Weekday uses ISO numbering, 1 = Monday. |

## 4. Leave

Source records:

- `leave_requests`;
- `leave_encashment_requests`, for balances only;
- `employees.annual_leave_entitlement_days`.

A request counts in the month its leave **starts**.

| Metric | Formula |
|---|---|
| Leave requests | Requests starting in the period, in any status. |
| Approved leave days | Σ `days` on approved requests starting in the period, all types. |
| Approval rate | Approved ÷ (approved + rejected) × 100. Pending and cancelled requests are left out. |
| Outstanding leave requests | Requests pending **today**, whatever their dates, with the oldest submission date. |
| By status and by type, monthly trend | The above, grouped. |
| Days used, balance, utilisation | The leave screens' rule (`services/leave.approved_days_taken`), for the leave year of the period's last day. Days used = approved leave of any type starting in that year + approved or paid encashed days requested in it. Balance = max(entitlement − days used, 0). Utilisation = Σ days used ÷ Σ entitlement × 100, over current (not terminated) employees, by department. The integration tests check this against `leave_balance()` for every employee. |
| Leave balance distribution | Current employees by remaining balance: none, 1–5, 6–10, 11–15, 16 days or more. |

## 5. Recruitment

Source records: `job_postings` (open or closed, opened date) and `candidates` (**current** status and applied date only). Only the department filter applies.

| Metric | Formula |
|---|---|
| Open vacancies | Postings open today. |
| Vacancies opened | Postings with `opened_date` in the period. |
| Applications received | Candidates with `applied_date` in the period. |
| Applicants now hired | Of those applicants, the ones whose status is Hired today. This is **not** hires made in the period, because there is no hire date. |
| Candidates in the pipeline | Candidates Applied, Interviewing or Offered today. |
| Candidates by current stage | Applicants in the period, by status today. |

**Unsupported, and listed as such in the response:**

- **Time to hire:** there is no hire date.
- **Offer acceptance rate:** offer and decline events aren't stored.
- **Hiring source performance:** there is no source field.
- **Funnel conversion:** there is no stage history, so a rejected candidate's furthest stage is unknown.

## 6. Performance and learning

Source records: `performance_reviews`, by `period_end`, and `training_enrollments`, by `enrolled_date`.

| Metric | Formula |
|---|---|
| Review completion rate | Submitted or acknowledged reviews ÷ all reviews whose period ends in the range × 100. |
| Rating distribution | Completed reviews by the rating given. Ratings are integers with **no scale fixed by the application**, so they are shown as recorded and never rescaled. Reviews without a rating are left out, not counted as zero. |
| Average rating by department | The mean of completed, rated reviews, by current department. A group of 1 or 2 is hidden for everyone. |
| Training completion rate | Completed ÷ all enrolments made in the period × 100. |

## 7. Tax and compliance

Source records:

- `statutory_liabilities`, raised by the payroll and contractor flows with due dates from the rule version;
- `bills.vat_minor` on approved or paid bills.

Nothing is recalculated here; the liabilities are the record.

- **Organisation-wide figures:** only the country filter applies.
- **Fail closed:** a country without approved rules is refused (422, "not production-enabled").
- **Date basis:** each liability counts in the month its **period ends**. Deadlines use `due_date`.

| Category | Schemes |
|---|---|
| Payroll tax | PAYE |
| Pension (employee and employer) | Pension. The liability holds both halves; the payroll section splits them. |
| Employee contributions | NHF |
| Employer contributions | NSITF, ITF |
| Withholding tax | WHT, withheld from suppliers and not a payroll tax |
| VAT | Reported separately: input VAT on approved and paid bills, by bill date. Output VAT isn't tracked. |

| Metric | Formula |
|---|---|
| PAYE liability, employer contributions, all statutory obligations | Σ `amount_minor` of the matching schemes, for periods ending in the range. |
| Outstanding today | Σ of every liability not yet remitted, whatever its period. |
| Overdue obligations | Unremitted liabilities with `due_date` before today. |
| Due in the next 30 days | Unremitted liabilities due from today to 30 days ahead. |
| Obligations completed | Liabilities **due** in the period that have been remitted; the note shows how many are still outstanding. |

## 8. Financial

Source records: `ledger_entries` joined to `journal_entries` and `chart_accounts`.

- **Date basis:** the journal's `entry_date`, the accounting date. The existing income statement and budget screens date lines by `created_at`, so a backdated journal can fall in a different month there (architecture A7). The integration tests reconcile totals with the income statement over a range that covers every journal.
- **Currency:** only journals in the selected currency.
- **Unclassified lines:** lines on account codes missing from the chart of accounts are left out, as the income statement leaves them out, and a note counts them.

| Metric | Formula |
|---|---|
| Revenue | Σ (credit − debit) on revenue accounts. |
| Expenses | Σ (debit − credit) on expense accounts. The chart doesn't separate operating from other expenses, so this is all of them. |
| Payroll expense | Expenses on `payroll_expense_gross`, `payroll_expense_employer_pension` and `payroll_expense_nsitf`, accrued at pay-run lock. This is not the net pay employees received. |
| Payroll share of expenses | Payroll expense ÷ expenses × 100. |
| Net income | Revenue − expenses. |
| Net cash movement | Σ (debit − credit) on `cash` and every account linked to a company bank account. |
| Expenses by department and by account | Expense lines grouped by the department tagged when posted, or by account (seven largest, the rest together). |
| Budget vs actual | For each budget overlapping the period (at most 20): Σ its lines against ledger activity on those accounts within the **budget's own dates**, revenue credit − debit and expense debit − credit, as the budgets screen compares them but by accounting date. Variance = actual − budgeted. |
