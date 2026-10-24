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
