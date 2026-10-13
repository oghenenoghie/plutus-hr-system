import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine

from alembic import command
from app.core import db as db_module
from app.core.config import get_settings
from app.core.db_roles import ensure_app_role, grant_app_role
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
    # The test database's own URL, whatever the developer's shell exports.
    os.environ.pop("MIGRATION_DATABASE_URL", None)
    os.environ.pop("APP_DATABASE_ROLE", None)
    get_settings.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database() -> None:
    _run_migrations(ADMIN_DATABASE_URL)

    # Querying as the postgres superuser would bypass every RLS policy, so
    # the suite runs as a plain, unprivileged role to prove enforcement is
    # real. It is provisioned with the same helpers a production deployment
    # uses (app/core/db_roles.py), so the grants can't drift from the schema.
    admin = create_engine(ADMIN_DATABASE_URL)
    with admin.begin() as conn:
        ensure_app_role(conn, role=APP_ROLE, password=APP_ROLE_PASSWORD)
        grant_app_role(conn, role=APP_ROLE)
    admin.dispose()

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
