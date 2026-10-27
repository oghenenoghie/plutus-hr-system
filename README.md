# Plutus Backend — FastAPI, Payroll, Accounting & Compliance

## Backend stack

- Python 3.12+
- FastAPI and Pydantic 2
- SQLAlchemy 2 and Alembic
- PostgreSQL
- Pytest, Ruff and mypy for quality checks

## Local setup

```bash
cp .env.example .env
uv sync --group dev
# Set the required environment variables, including the database URL.
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Do not commit `.env` or secrets. `.env.example` is a template only.

## Checks

These are the checks CI runs (`.github/workflows/ci.yml`). The integration tests need a PostgreSQL database named `plutus_test` (see `tests/integration/conftest.py`).

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run alembic upgrade head
uv run pytest
```

## Documentation

- [`docs/analytics-architecture.md`](docs/analytics-architecture.md): Analytics & Insights audit, decisions, data flow and performance.
- [`docs/analytics-metrics.md`](docs/analytics-metrics.md): the formula, source records and date basis of every analytics figure.
- [`docs/analytics-security.md`](docs/analytics-security.md): analytics permissions, role defaults, department scope, tenant isolation and exports.
- [`docs/architecture/inventory-integration.md`](docs/architecture/inventory-integration.md): inventory and stock-control design.
- [`docs/architecture/multicountry-tax.md`](docs/architecture/multicountry-tax.md): multi-country tax architecture, rule lifecycle and release gates.
- [`docs/operations/runbook.md`](docs/operations/runbook.md): operations runbook.

## Multi-country compliance

Each organisation has a country, and all six run payroll. Nigeria runs on its own approved rule versions. The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire run on the country-neutral engine, with payroll rules approved by Plutus Technologies from the drafts in [`docs/countries/`](docs/countries/README.md), without a local tax adviser's review. Where those drafts found a figure conflicting or unknown, each organisation enters it under Tax Settings, and its payroll is refused until it has. Their VAT, withholding tax and corporate tax rates aren't approved and still fail closed.

- **Country catalogue.** `app/compliance/multicountry.py` holds the catalogue and the fail-closed `require_configured_country`. `app/services/jurisdiction.py` resolves an organisation's country and its rules.
- **The country-neutral engine.** `app/compliance/engine/` holds:
  - typed, effective-dated country rule sets (`rules.py`), each with an approval record and a cited source on every rule;
  - the pure payroll calculation (`calculate.py`), with Nigeria parity proven to the kobo;
  - postings (`postings.py`);
  - VAT and other transaction taxes (`indirect_tax.py`);
  - `countries/`, the five countries' approved rule sets, each a template built from the organisation's Tax Settings (`settings.py`);
  - `registry.py`, the only way to get a country's rules.
- **Tax Settings.** `org_tax_settings` holds each organisation's own figures, effective-dated, append-only and audited; `app/services/tax_settings.py` and `GET`/`POST /api/v1/compliance/tax-settings` (admins enter them).
- **Pay runs.** Every country but Nigeria runs payroll on the engine (`app/services/engine_payroll.py`). Each payslip's statutory lines are stored in `payslip_statutory_lines`, and liabilities use the `country` scheme. The payslip PDF, payroll reports, tax certificate, disbursement file and payroll analytics show those lines in the organisation's currency. Nigeria keeps its own path, unchanged.
- **Design, rule lifecycle and release gates:** [`docs/architecture/multicountry-tax.md`](docs/architecture/multicountry-tax.md).
- **Requirements:** `.claude/skills/plutus-multicountry-tax/SKILL.md` sets the implementation and statutory-validation requirements.

Focused tests:

```bash
uv run pytest tests/unit/test_multicountry_tax_engine.py tests/unit/test_tax_engine_calculation.py \
  tests/unit/test_tax_engine_rules.py tests/unit/test_indirect_tax.py tests/golden/test_tax_engine_nigeria_parity.py \
  tests/integration/test_engine_pay_runs.py tests/integration/test_engine_payroll_outputs.py
```

## Analytics & Insights

Read-only dashboards aggregated in SQL from the existing payroll, HR, attendance, leave, recruitment, performance, compliance and ledger tables. Nothing is recalculated or written: the figures are the records the rest of the application already holds.

- `app/services/analytics/` holds one module per section, plus:
  - `filters.py`: filter validation;
  - `access.py`: permissions and department scope;
  - `records.py`: drill-down datasets;
  - `exports.py`: CSV, XLSX and PDF tables with metadata.
- `app/api/v1/analytics.py` exposes, under `/api/v1/analytics`:
  - `GET /access` and `GET /filter-options`;
  - `GET /overview`, `/workforce`, `/payroll`, `/attendance`, `/leave`, `/recruitment`, `/performance`, `/compliance` and `/financial`;
  - `GET /records/{dataset}`, the paginated drill-down;
  - `GET /sections/{report}/export` and `GET /records/{dataset}/export`, with `format=csv|xlsx|pdf`.
- Every endpoint takes the same filters: `date_from`, `date_to`, `compare`, `department_id`, `location_id`, `employment_type`, `status`, `payroll_status` and `country`. They are validated before any query runs.
- Ten permissions, from `analytics.view` to `analytics.reports.export`, are added by migration `a3c9e1f7b254`. Their role defaults are in `docs/analytics-security.md`.
- Responses are `Cache-Control: private, no-store`, and every export is audited as `analytics.export`.

Focused tests:

```bash
uv run pytest tests/unit/test_analytics.py tests/integration/test_api_analytics.py
```

The integration tests reconcile analytics with the payroll-cost report, the statutory-liabilities report, the income statement and each employee's leave balance.
