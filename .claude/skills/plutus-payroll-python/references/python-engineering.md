# Plutus (Python) — Engineering, Stack & Software Lifecycle

Reference for how the **Python / FastAPI / Railway** build of Plutus is built, tested, shipped, and operated. Read this for any task touching stack choices, repo structure, environments, testing, migrations, the rules engine, CI/CD, hosting, observability, or data protection.

> **This is the Python port.** The domain (statutory rules, entities, guardrails) is identical to the TypeScript/Supabase build described in the `plutus-payroll-platform` skill; only the engineering layer changes. Where a rule, base, threshold, or deadline is needed, it comes from `nigeria-statutory-compliance.md` — never from memory, never hardcoded.
>
> **Sourcing note:** the stack below follows Patrick's established Python conventions (the folad_lms standalone stack: FastAPI + PostgreSQL, app-layer tenant-scoped access + PostgreSQL RLS via session GUC, money as integer minor units in bigint). Confirm anything that may have drifted before relying on it.

## Table of contents
1. Tech stack
2. Repo structure
3. Environments & configuration
4. Database, migrations & RLS (session GUC)
5. The versioned rules engine (implementation contract)
6. Money & the ledger
7. Domain model
8. Testing strategy
9. CI/CD
10. Hosting & deployment (Railway)
11. Observability & operations
12. Security & data protection
13. Release & change management
14. Build roadmap (phased)

---

## 1. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| API framework | **FastAPI** (async) | REST + OpenAPI; routers versioned under `/api/v1` |
| Language | **Python 3.12+**, full type hints, **mypy `--strict`** | Types are the contract; enforced in CI |
| Validation / DTOs | **Pydantic v2** | Request/response schemas; also the shape of loaded rule sets |
| ORM | **SQLAlchemy 2.0** (typed, `Mapped[...]`) | Sync engine for the transactional payroll core; async only where it earns its keep |
| Migrations | **Alembic** | The *only* way schema changes ship (see §4) |
| Database | **PostgreSQL 16** on Railway | Sole system of record. RLS enforced in the DB, not the app |
| Auth | App-managed: **JWT** (short-lived access + refresh), **argon2** password hashing, **TOTP MFA** for Admin & Payroll Manager | Alternative: keep Supabase Auth behind FastAPI — see §12 |
| Object storage | **S3-compatible** (Cloudflare R2 or Supabase Storage) | Payslip PDFs, disbursement files, filing evidence, employee photos — private buckets, signed URLs only |
| Task queue / workers | **Arq** (async, Redis-backed) | Batch pay runs, filings, report/PDF generation. Alternative: Celery |
| Cache / broker | **Redis** on Railway | Arq broker + rate limiting + short-lived cache |
| Money / ledger | in-repo `domain/money.py` + `ledger` module | Integer minor units, double-entry, append-only (see §6) |
| Compliance rules | in-repo `compliance/` package | Versioned statutory rule sets as data (see §5) |
| Email | **Resend** (Python SDK) | Payslip delivery, notifications, deadline alerts |
| Dep manager | **uv** (lockfile committed) | Fast, reproducible. Alternative: Poetry |
| Lint / format | **Ruff** (lint + format) | Replaces black/isort/flake8 |
| CI/CD | **GitHub Actions** | ruff, mypy, pytest (golden + unit + integration), alembic upgrade check, deploy |

**Currency:** NGN has exponent 2 (kobo). Store money as **integer minor units in `BIGINT`** — never `float`, and never persist `Decimal` as the stored type. `Decimal` is acceptable only as an *intermediate* for rate arithmetic; the value that lands in the column is an `int` of minor units. Pan-African: resolve the exponent **per currency** (KWD=3, JPY=0); never assume 2. Rates that need sub-percent precision (e.g. WHT categories) scale as **parts-per-million** integers, consistent with the existing Plutus convention.

## 2. Repo structure

Standalone Python repo (mirrors the folad_lms standalone decision — a Python payroll stack does not belong inside the TypeScript `business-platform` monorepo). If sibling Python apps appear later, promote to a uv workspace with a shared `packages/` layout; until then, keep it flat.

```
plutus-py/
├── app/
│   ├── main.py                  # FastAPI app factory, middleware, lifespan
│   ├── api/v1/                  # routers, one module per resource
│   ├── core/                    # config (Pydantic Settings), security, deps,
│   │                            #   db session + RLS GUC context manager
│   ├── domain/                  # PURE domain logic — no I/O, no DB, no framework
│   │   ├── money.py             # Money value object, minor-unit arithmetic
│   │   └── payroll/             # per-scheme calculators (PAYE, pension, NHF, …)
│   ├── compliance/              # ← the moat: versioned rules engine (§5)
│   │   ├── models.py            # frozen Pydantic rule-set models
│   │   ├── resolver.py          # resolve rule version for (country, date)
│   │   └── versions/            # NG-2026.1 seed data (data, not logic)
│   ├── models/                  # SQLAlchemy ORM (persistence)
│   ├── schemas/                 # Pydantic request/response DTOs
│   ├── services/                # orchestration (pay-run, filing, settlement)
│   └── workers/                 # Arq task definitions
├── alembic/                     # migrations — the only way schema ships
├── tests/
│   ├── golden/                  # statutory golden tests (highest priority)
│   ├── unit/                    # calculators, money math, rule resolution
│   ├── integration/             # full pay run vs seeded DB with RLS on
│   └── property/                # hypothesis invariants
├── .env.example                 # every required key + its purpose
├── pyproject.toml               # uv-managed; ruff + mypy + pytest config
├── Dockerfile                   # (or nixpacks/railway.toml)
├── railway.toml / Procfile      # api + worker process definitions
└── .github/workflows/ci.yml
```

**Keep the compliance engine pure.** `app/compliance/` and `app/domain/` import nothing from `app/models/`, `app/api/`, or SQLAlchemy. Calculators take rule sets and pay components in, and return numbers out. This is what makes golden tests fast and the moat portable to a second country.

## 3. Environments & configuration

- Environments: **local → preview (per-PR) → staging → production.** A dedicated Postgres instance (Railway service or a separate project) per environment — **never shared.** A staging job must not be able to reach production payroll data.
- Config via **Pydantic `BaseSettings`** reading env vars; secrets in Railway variables and GitHub Actions secrets — **never committed.** Payroll handles PII and bank data; treat every secret as high-sensitivity.
- Pick one canonical name per secret and document it (a past Plutus bug was two names for the same key). Keep a real `.env.example` listing every required key and its purpose.
- Fail fast: the app should refuse to boot if a required setting is missing, rather than discovering it mid-pay-run.

## 4. Database, migrations & RLS (session GUC)

PostgreSQL is the entire data layer. Lean on Postgres features rather than abstracting them away — RLS, check constraints, triggers, exclusion constraints and `pg_cron` are the intended correctness mechanism, not an application-layer emulation kept "thin in case we migrate."

### Multi-tenancy: RLS via session GUC

This is the folad_lms pattern and the correct one here. There is no Supabase `auth.uid()` on this stack, so tenant scoping is enforced by a **session-local GUC** that RLS policies read:

- On every request, after authenticating, open a transaction and issue `SET LOCAL app.current_org = :org_id` (and `app.current_user`, `app.current_role` as needed). `SET LOCAL` is transaction-scoped, so it cannot leak across pooled connections.
- RLS policies filter with `current_setting('app.current_org')::uuid`. Every tenant table has RLS **enabled and forced**.
- Provide this as a single dependency / context manager (`with tenant_session(org_id, user_id, role) as db:`) so no handler can forget it. A query that runs without the GUC set should see nothing, not everything — deny by default.
- The worker sets the same GUCs per job before touching tenant data.

```python
# core/db.py (illustrative)
@contextmanager
def tenant_session(org_id: UUID, user_id: UUID, role: str):
    with SessionLocal() as db:
        db.execute(text("SET LOCAL app.current_org = :o"), {"o": str(org_id)})
        db.execute(text("SET LOCAL app.current_user = :u"), {"u": str(user_id)})
        db.execute(text("SET LOCAL app.current_role = :r"), {"r": role})
        yield db
        db.commit()
```

- **Role separation is enforced in the database**, not by hiding nav items. Payroll Manager, Admin, Employee, etc. resolve to Postgres RLS predicates.
- **The service role bypasses RLS only where genuinely required** for batch processing. Scope it narrowly, log every use, and never let a service-role session reach a request handler.

### Connection pooling

Batch payroll runs are long-lived and transactional. Use a pooler (PgBouncer / Railway's Postgres pooling) deliberately:
- **Transaction-mode** pooling for short API queries.
- **Session-mode** for anything needing prepared statements, advisory locks, or `SET LOCAL` semantics across multiple statements in a run.
- **Never open one connection per employee in a run.** Pool exhaustion during a large pay run is the predictable failure. Batch in bounded chunks, one transaction per chunk (or per run, if it fits).
- Note: PgBouncer transaction mode disables server-side prepared statements — configure SQLAlchemy accordingly (`prepare_threshold=None` on psycopg, or the async equivalent).

### Migrations

- **Alembic migrations are the only way schema changes ship.** Every change is a checked-in, ordered, reviewed migration — no manual edits against the live DB. (Prior Plutus incident: migrations were never pushed to the live project, so the app queried tables that didn't exist. CI enforces "migrate before deploy.")
- Postgres-native invariants where possible: **check constraints** for statutory bounds, **deferred-constraint triggers** for the ledger's double-entry balance, **exclusion constraints** (`EXCLUDE USING gist`) where overlap prevention is needed (e.g. leave/attendance date ranges).
- **Append-only tables** (payslips, audit events, ledger entries, statutory liabilities) are enforced at the DB level: `REVOKE UPDATE, DELETE` from the application role, or a trigger that raises on `UPDATE`/`DELETE`. Corrections are new rows, never edits.
- Historical reproducibility: pay-run records store the **rule version** in force at run time, so any old payslip can be recomputed exactly.

## 5. The versioned rules engine (implementation contract)

This is the product's core and its moat. Non-negotiable design, unchanged from the TS build — only the language differs.

- **Rules are data, effective-dated, centrally versioned.** A `rule_version` (e.g. `NG-2026.1`) carries the full band table, reliefs, thresholds, and per-scheme rates, bases and deadlines for a validity window `[effective_from, effective_to)`.
- Rule versions live as **rows in the database**, seeded from `app/compliance/versions/`, and are loaded into **frozen Pydantic models** for use by the pure calculators. Storing them as data (not Python literals scattered through code) is what lets the law change with a migration instead of a code edit.
- A payroll run **pins** the rule version it used; results are immutable and reproducible.
- **No magic numbers in code.** Every rate/threshold/band/deadline resolves through the rule set. `grep -rn` for statutory figures in `app/domain/` and `app/services/` should return nothing.
- Changing the law = a new rule-version row + an Alembic migration + updated golden tests. **Never** editing calculation logic in place.
- Source every figure from `nigeria-statutory-compliance.md`, including the §11 errata (do not port the prototype's wrong NSITF/pension/NHF deadlines).

Illustrative shape (Pydantic v2, frozen):

```python
from enum import Enum
from pydantic import BaseModel, ConfigDict

class BorneBy(str, Enum):
    EMPLOYEE = "employee"
    EMPLOYER = "employer"
    BOTH = "both"

class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)

class Band(Frozen):
    up_to_minor: int | None      # None = top open band; minor units
    rate_ppm: int                # parts-per-million (15% -> 150_000)

class PAYE(Frozen):
    bands: tuple[Band, ...]
    tax_free_threshold_minor: int
    rent_relief_rate_ppm: int
    rent_relief_cap_minor: int
    authority: str = "STATE_IRS"
    due_day_of_following_month: int = 10

class Pension(Frozen):
    base: tuple[str, ...]        # ("basic", "housing", "transport")
    employee_rate_ppm: int
    employer_rate_ppm: int
    borne_by: BorneBy = BorneBy.BOTH
    authority: str = "PFA"
    due_working_days_after_payment: int = 7

class RuleVersion(Frozen):
    id: str                      # "NG-2026.1"
    country: str                 # "NG"
    effective_from: date
    effective_to: date | None
    paye: PAYE
    pension: Pension
    # nhf, nhis, nsitf, itf, wht … each with its own base, rate, borne_by,
    # authority and deadline — modelled explicitly, one per scheme.
```

`borne_by` is modelled explicitly and typed. **Employer-side costs (NSITF, ITF, employer pension) must never be able to land in an employee's deduction total** — encode it in the type, not in convention. A calculator that sums employee deductions filters on `borne_by in (EMPLOYEE, BOTH)` and takes only the employee slice.

## 6. Money & the ledger

- `domain/money.py` provides a `Money` value object: `(amount_minor: int, currency: str)`. All arithmetic is integer; formatting resolves the exponent per currency. Reject cross-currency operations.
- Percentages and rates apply as `amount_minor * rate_ppm // 1_000_000` with an explicit, tested rounding rule (round-half-up or banker's — pick one, document it, golden-test the boundaries). Never `float`.
- The `ledger` module is **double-entry and append-only**: every payroll posting balances (debits = credits), enforced by a deferred-constraint trigger. Reversals are compensating entries, not deletes.
- This is a statutory/financial ledger, so the append-only + effective-dated discipline from Patrick's standing conventions applies without exception.

## 7. Domain model

Core entities (same domain as the TS build; persisted as SQLAlchemy models). Money columns are `BIGINT` minor units.

- **Organisation** — name, RC number, company TIN, default pay frequency, default PFA, states of operation.
- **Department / CostCentre** — pay-run scoping + payroll accounting allocation.
- **Branch / Location** — statutory filing is state-scoped; locations are first-class, not free text.
- **JobPosition / Grade / Level** — anchors salary bands and later compensation review.
- **Employee** — the record everything hangs off. Group fields by dependency:
  - *Identity:* employee number, full name, DOB (drives pension retirement eligibility), gender, nationality (affects expatriate tax treatment), marital status.
  - *Contact:* email, phone, residential address, next of kin.
  - *Statutory:* TIN + validity, PFA + RSA PIN, NHF number, NHIS scheme, **state of residence** (PAYE routing — distinct from state of origin and work location).
  - *Employment:* department, branch, position/grade, manager, employment type, date of joining (first-period proration), lifecycle state.
  - *Pay:* pay components (basic / housing / transport stored **separately**, never a derived split), pay frequency, bank account, payroll group.
  - *Other:* leave balance, access role, photo (object path + version + consent timestamp, nullable).
- **BankAccount** — bank, NUBAN, account name, verification status. Without it, no disbursement file.
- **EmploymentContract** — type (permanent / fixed-term / part-time / intern / consultant), dates, probation, confirmation, notice period. Drives proration and type-varying statutory treatment.
- **PayRun** — period, frequency (regular / bonus-13th / arrears-off-cycle), scope (all / department / contractors), status, **pinned rule version**, employee count, gross, net.
- **Payslip** — per employee per run: gross, each statutory deduction, net, plus the stored derivation trail powering the "how?" expander. **Append-only.**
- **StatutoryLiability** — per scheme per period per state: amount, authority, deadline, filing status, remittance evidence.
- **Loan / Advance**, **ExpenseClaim**, **BenefitEnrollment**, **LeaveRequest / AttendanceRecord**, **FinalSettlement** (leave payout + gratuity − outstanding loans).
- **AuditEvent** — append-only; who did what, when, under which rule version.

Payslips, ledger entries and audit events are append-only; corrections are new records.

### Employee photos (don't take the convenient default)

Captured at enrollment. Own private bucket, org-scoped path `employee-photos/{org_id}/{employee_id}/{version}.webp`, access via signed URLs mediated by the same tenant checks — **never a public bucket** (a public bucket of workforce headshots keyed by sequential ID is a straightforward leak). On upload, before storing: **strip EXIF** (phone GPS + timestamps), re-encode to WebP square-cropped at one canonical size plus a thumbnail, cap file size, and **validate the decoded image, not the declared MIME type** (content-type is attacker-controlled). Version the path rather than overwriting. Photos are personal data under NDPR: record consent at capture; the Final Settlement exit flow triggers deletion on the retention schedule rather than leaving orphans.

## 8. Testing strategy

Payroll is a domain where a wrong number is real financial and legal harm, so testing is weighted toward calculation correctness.

- **Golden tests for the compliance engine (highest priority).** Fixed input → expected statutory output, as `pytest.mark.parametrize` cases. The full required list is in `nigeria-statutory-compliance.md` §12: every PAYE band boundary, rent-relief cap edges, zero-rent, sub-threshold income, mid-year pay change (cumulative recompute), TIN-missing gate, per-scheme base correctness, employer-vs-employee split, multi-state reconciliation.
- **Unit** (pytest) — rule resolution, `Money` math, per-scheme calculators. Pure, fast, no DB.
- **Integration** (pytest + a real Postgres, e.g. testcontainers) — full pay run against a seeded DB **with RLS enforced**; verify per-tenant isolation and per-role access by asserting a wrong-org session sees nothing.
- **Property tests** (**Hypothesis**) — Σ per-band tax ≤ chargeable income; net ≤ gross; no negative deduction; employer costs absent from employee totals; monthly × 12 reconciles to annual within rounding tolerance.
- **API contract** — schemathesis against the OpenAPI schema; assert disbursement file formats explicitly.

**CI fails if golden tests fail.** Never ship a green build with a broken calculation.

## 9. CI/CD

GitHub Actions, per PR and on merge:

1. `uv sync` (cached)
2. **Ruff** lint + format check
3. **mypy `--strict`**
4. **pytest** — unit + golden + integration (fail-closed; golden failures block)
5. **Migration check** — spin up a fresh Postgres, run `alembic upgrade head`, assert it applies cleanly; optionally assert models match migrations (no drift)
6. Build image
7. Deploy: Railway preview per PR; promote to staging/prod on merge with a **manual approval gate for production**

## 10. Hosting & deployment (Railway)

- **API:** FastAPI under uvicorn/gunicorn (uvicorn workers) as a Railway service.
- **Worker:** the Arq worker as a **separate Railway service** sharing the codebase — batch pay runs, filings, disbursement-file and PDF generation, deadline alerting. **Never run batch payroll or file generation in a request handler.**
- **Database:** PostgreSQL on Railway (with pooling per §4). Point-in-time recovery configured (§12).
- **Redis:** Railway Redis for the Arq broker + rate limiting.
- **Scheduler:** Arq cron (or `pg_cron`) for deadline alerts and recurring filings.
- Define processes explicitly (`railway.toml`/`Procfile`) so api and worker scale independently.

## 11. Observability & operations

- Structured, **audit-grade** logs (JSON) on the worker for every pay run and every remittance/filing attempt. Include `run_id`, `org_id`, `rule_version`, per-scheme liability, filing/remittance status, retries, failures.
- **Deadline alerting is a product requirement, not just ops** — monthly PAYE (10th), pension (7 working days from payment), NHF (1 month), NSITF (16th), WHT (21st), ITF (1 April annually). A missed NSITF month carries a 10% penalty. Schedule these as worker cron jobs.
- Dashboards / reports surface statutory liabilities and filing status by entity, state, and country.
- Health checks and readiness endpoints for Railway; alert on worker queue depth and failed jobs.

## 12. Security & data protection

Payroll means employee PII, salary, bank details and tax IDs — high-sensitivity throughout.

- **RLS + org-scoping on every tenant table** (§4); least-privilege DB roles; the application role has no broad admin and no `UPDATE`/`DELETE` on append-only tables.
- **Auth:** app-managed JWT (short-lived access + rotating refresh), **argon2id** password hashing, **TOTP MFA required for Admin and Payroll Manager**. Super-admin bootstrapped via a one-time invite/`generate_link` pattern, never plaintext credentials — consistent with the existing Plutus super-admin approach. *Alternative:* keep **Supabase Auth** and verify its JWTs in a FastAPI dependency; if so, map the Supabase user id into the `app.current_user` GUC. Pick one and document it.
- Encrypt sensitive columns at rest where warranted (e.g. bank account numbers); TLS everywhere; secrets never in the repo.
- Full **audit trail** per pay cycle — who ran what, which rule version, what changed. Compliance control and product feature at once.
- **NDPR** awareness for personal data; documented retention and data-residency posture; consent recorded for employee photos.
- **Backups + *tested* restore.** Losing a payroll DB is existential. Point-in-time recovery on Postgres. Accept single-provider concentration explicitly and mitigate with a rehearsed restore, not a hedge database that never gets exercised.
- Access to production payroll data is logged and restricted.

## 13. Release & change management

- **Statutory change = new versioned rule set (row + seed) + Alembic migration + golden-test update**, shipped as a discrete, reviewable release. Never a hotfix number-edit.
- Tag releases; keep a changelog noting any `rule_version` change and its effective date.
- Commit the `.claude/skills/` pause/resume protocol in-repo so sessions can hand off state — keep it current.

## 14. Build roadmap (phased)

1. **Foundation** — FastAPI app shell, Pydantic Settings, auth (JWT + argon2 + TOTP), org/tenant model, RLS via session GUC, `.env.example`, Alembic baseline, CI skeleton with migration check.
2. **Compliance engine** — `app/compliance/` with `NG-2026.1` as data; PAYE + all seven schemes as pure calculators; **golden suite green before any endpoint depends on it.**
3. **Payroll core** — employees, real pay components, multi-frequency runs, payslips with the stored derivation trail, ledger-backed postings, cumulative PAYE, TIN gating.
4. **People ops + self-service** — leave, attendance, loans, expenses, benefits; employee and manager access.
5. **Filing & remittance** — state-of-residence routing, filing schedules, remittance tracking, disbursement files, deadline alerting, dashboards.
6. **Final settlement + simulation** — exit payroll, what-if analysis.
7. **Pan-African** — the rule layer already isolates country; add Ghana, then Kenya, as new rule sets, not rewrites. Don't hardcode Nigeria assumptions (currency exponent, scheme count, single-tax-authority, "states" as the only sub-national unit) into the shared core.
