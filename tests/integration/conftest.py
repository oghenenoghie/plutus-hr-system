import os
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql

from alembic import command
from app.core import db as db_module
from app.core.config import get_settings
from app.core.rate_limit import limiter

REPO_ROOT = Path(__file__).resolve().parents[2]

ADMIN_DATABASE_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/plutus_test",
)
APP_ROLE = "plutus_app_test"
APP_ROLE_PASSWORD = "plutus_app_test"
APP_DATABASE_URL = os.environ.get(
    "TEST_APP_DATABASE_URL",
    f"postgresql+psycopg://{APP_ROLE}:{APP_ROLE_PASSWORD}@127.0.0.1:5432/plutus_test",
)


def _run_migrations(url: str) -> None:
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database() -> None:
    _run_migrations(ADMIN_DATABASE_URL)

    # Querying as the postgres superuser would bypass every RLS policy, so
    # provision a plain, unprivileged role to prove enforcement is real —
    # this mirrors a production app connecting as a non-superuser role.
    admin_dsn = ADMIN_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(APP_ROLE), sql.Literal(APP_ROLE_PASSWORD)
                )
            )
        cur.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON organisations, accounts, memberships, "
                "employees, bank_accounts, pay_runs, payslips, ledger_entries, loans, "
                "loan_repayments, leave_requests, final_settlements, statutory_liabilities, "
                "expenses, benefits, contractors, wht_payments, audit_logs, departments, "
                "branches, job_grades, policies, shifts, job_postings, candidates, "
                "performance_reviews, training_courses, training_enrollments, "
                "disciplinary_cases, notifications, union_memberships, "
                "company_assets, asset_assignments, api_keys, chart_accounts, "
                "vendors, bills, customers, invoices, fixed_assets, budgets, budget_lines, "
                "company_bank_accounts, bank_statement_lines TO {}"
            ).format(sql.Identifier(APP_ROLE))
        )

    os.environ["DATABASE_URL"] = APP_DATABASE_URL
    get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_session_factory.cache_clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """The rate limiter (app.core.rate_limit.limiter) is a process-wide
    singleton with in-memory storage — every test in this session shares
    it. TestClient has no real per-test client IP, so every /auth/login
    call across the whole suite would otherwise count against the same
    bucket, and unrelated tests would start getting 429s once enough of
    them had logged in. Reset before every test so each one starts clean;
    a test that wants to exercise the limit itself still can, in isolation.
    """
    limiter.reset()
