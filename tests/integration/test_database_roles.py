"""Tenant isolation at the database (Phase 5 hardening): every
organisation-owned table has a row-level security policy, the application
connects as a role those policies bind, and the provisioning helpers that
make that true in production behave as documented (app/core/db_roles.py)."""

import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from alembic import command
from app.core import db_roles
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.db_roles import (
    RlsBypassError,
    bypasses_rls,
    check_app_connection,
    ensure_app_role,
    grant_app_role,
)
from tests.integration.conftest import ADMIN_DATABASE_URL, APP_DATABASE_URL
from tests.integration.inventory_helpers import Shop

REPO_ROOT = Path(__file__).resolve().parents[2]

# Organisation-owned tables deliberately left without a policy, and why.
UNPOLICED = {
    # Read before sign-in, to find which organisations an account belongs
    # to (app.core.db.get_untenanted_session); every write is org-checked
    # by the service layer.
    "memberships",
}


@pytest.fixture
def admin() -> Iterator[Engine]:
    engine = create_engine(ADMIN_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def probe_role(admin: Engine) -> Iterator[str]:
    """A throwaway role, dropped with everything granted to it afterwards."""
    role = f"probe_{uuid.uuid4().hex[:12]}"
    yield role
    with admin.begin() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        if exists:
            conn.execute(text(f"DROP OWNED BY {role}"))
            conn.execute(text(f"DROP ROLE {role}"))


def _engine_as(role: str, password: str) -> Engine:
    return create_engine(make_url(ADMIN_DATABASE_URL).set(username=role, password=password))


def test_every_org_owned_table_has_a_tenant_policy(admin: Engine) -> None:
    with admin.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity,"
                " ARRAY(SELECT pg_get_expr(p.polqual, p.polrelid) FROM pg_policy p"
                "       WHERE p.polrelid = c.oid)"
                " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = 'public' AND c.relkind = 'r' AND EXISTS ("
                "   SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid"
                "   AND a.attname = 'org_id' AND NOT a.attisdropped)"
            )
        ).all()
    assert len(rows) > 50  # the check is looking at the real schema
    unpoliced = {name for name, enabled, policies in rows if not enabled or not policies}
    assert unpoliced == UNPOLICED
    for name, _, policies in rows:
        if name in UNPOLICED:
            continue
        assert any("app.current_org" in policy for policy in policies), (name, policies)


def test_the_application_role_is_bound_by_the_policies(admin: Engine) -> None:
    with get_engine().connect() as conn:
        assert make_url(str(conn.engine.url)).username == make_url(APP_DATABASE_URL).username
        assert bypasses_rls(conn) is False
        assert check_app_connection(conn, enforce=True) is True
    with admin.connect() as conn:
        assert bypasses_rls(conn) is True  # the postgres superuser


def test_startup_check_warns_or_refuses_on_a_bypassing_role(admin: Engine) -> None:
    # The app's logging setup replaces the root handlers pytest captures
    # through, so the warning is observed on the module's logger directly.
    with admin.connect() as conn:
        with patch.object(db_roles.logger, "warning") as warning:
            assert check_app_connection(conn, enforce=False) is False
        warning.assert_called_once()
        assert "row-level security is not enforced" in warning.call_args.args[0]
        with pytest.raises(RlsBypassError):
            check_app_connection(conn, enforce=True)


def test_without_a_tenant_the_application_role_sees_no_rows(admin: Engine) -> None:
    first, second = Shop(), Shop()
    with get_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM inventory_items")) == 0
        conn.execute(
            text("SELECT set_config('app.current_org', :org, false)"), {"org": str(first.org_id)}
        )
        owners = set(conn.scalars(text("SELECT DISTINCT org_id FROM inventory_items")))
        assert owners == {first.org_id}
        # Another organisation's rows can't be changed (the policy hides
        # them) or created (the policy rejects them).
        updated = conn.execute(
            text("UPDATE inventory_items SET name = 'x' WHERE id = :id"), {"id": second.item}
        )
        assert updated.rowcount == 0
        with pytest.raises(ProgrammingError, match="row-level security"):
            conn.execute(
                text(
                    "INSERT INTO inventory_categories (id, org_id, name)"
                    " VALUES (gen_random_uuid(), :org, 'smuggled')"
                ),
                {"org": second.org_id},
            )
        conn.rollback()
    with admin.connect() as conn:
        # The rows exist; only the role's view of them is limited.
        total = conn.scalar(
            text("SELECT count(*) FROM inventory_items WHERE org_id IN (:a, :b)"),
            {"a": first.org_id, "b": second.org_id},
        )
        assert total == 2


def test_provisioning_creates_a_restricted_role_and_is_idempotent(
    admin: Engine, probe_role: str
) -> None:
    with admin.begin() as conn:
        # A role that starts out over-privileged is reset, not trusted.
        conn.execute(text(f"CREATE ROLE {probe_role} LOGIN BYPASSRLS PASSWORD 'old'"))
    for _ in range(2):
        with admin.begin() as conn:
            ensure_app_role(conn, role=probe_role, password="it's-a-secret")
            grant_app_role(conn, role=probe_role)

    probe = _engine_as(probe_role, "it's-a-secret")
    try:
        with probe.connect() as conn:
            assert bypasses_rls(conn) is False
            assert conn.scalar(text("SELECT count(*) FROM inventory_items")) == 0
            with pytest.raises(ProgrammingError):
                conn.execute(text("SELECT * FROM alembic_version"))
            conn.rollback()
            with pytest.raises(ProgrammingError):
                conn.execute(text("CREATE TABLE probe_made_this (id int)"))
    finally:
        probe.dispose()


def test_provisioning_rejects_unsafe_input(admin: Engine) -> None:
    with admin.begin() as conn:
        with pytest.raises(ValueError):
            ensure_app_role(conn, role="app; DROP TABLE accounts", password="x")
        with pytest.raises(ValueError):
            ensure_app_role(conn, role="plutus_app", password="")
        with pytest.raises(ValueError):
            grant_app_role(conn, role="Robert'); --")


def test_every_migration_run_grants_the_application_role(
    admin: Engine, probe_role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin.begin() as conn:
        ensure_app_role(conn, role=probe_role, password="secret")
    with admin.connect() as conn:
        assert not conn.scalar(
            text("SELECT has_table_privilege(:r, 'inventory_items', 'SELECT')"),
            {"r": probe_role},
        )

    monkeypatch.setenv("DATABASE_URL", APP_DATABASE_URL)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", ADMIN_DATABASE_URL)
    monkeypatch.setenv("APP_DATABASE_ROLE", probe_role)
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(REPO_ROOT / "alembic.ini")), "head")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()

    with admin.connect() as conn:
        assert conn.scalar(
            text("SELECT has_table_privilege(:r, 'inventory_items', 'SELECT, INSERT')"),
            {"r": probe_role},
        )
        assert not conn.scalar(
            text("SELECT has_table_privilege(:r, 'alembic_version', 'SELECT')"),
            {"r": probe_role},
        )
