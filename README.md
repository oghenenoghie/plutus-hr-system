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

- `app/compliance/multicountry.py` defines the supported-country catalogue, the effective-dated rate primitive, the percentage-tax calculation and the fail-closed readiness guard.
- `app/api/v1/compliance.py` exposes the authenticated `GET /api/v1/compliance/countries`.
- `tests/unit/test_multicountry_tax_engine.py` covers:
  - catalogue values;
  - rejection of unconfigured and unknown countries;
  - inclusive and exclusive calculations, including half-up rounding;
  - effective-date boundaries;
  - jurisdiction mismatch.
- `.claude/skills/plutus-multicountry-tax/SKILL.md` sets the implementation and statutory-validation requirements.

Nigeria is the only active jurisdiction. The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire stay `configuration_required`. This code does not provide approved local statutory rules and does not authorise tax filing or posting for them.

Before a jurisdiction can be enabled, the following must be in place:

- persisted rule administration with an approval step;
- organisation and legal-entity resolution;
- immutable calculation snapshots;
- validation against official sources;
- country-specific tests;
- the release gates in the architecture document.

Focused tests:

```bash
uv run pytest tests/unit/test_multicountry_tax_engine.py
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
