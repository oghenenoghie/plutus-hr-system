"""The database role the application connects as.

Row-level security is the database's own tenant boundary: every
organisation-owned table carries a policy limiting rows to the organisation
named by the `app.current_org` setting (see app.core.db.tenant_session).
PostgreSQL skips those policies entirely for a superuser, or a role with
BYPASSRLS, so the application must connect as an ordinary role. Migrations,
which create and alter tables, still run as the owning role.

These helpers create that ordinary role and keep its grants current. The
same functions serve the cloud provisioning script
(scripts/provision_app_role.py), the desktop build's startup, and the test
suite, so all three prove the same thing.
"""

import logging
import re

from sqlalchemy import Connection, text

logger = logging.getLogger("app.db")

# Lower-case identifiers only, so a role name is never interpolated into
# SQL in a form that needs quoting rules to stay safe.
_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Bookkeeping that only migrations touch.
_MIGRATION_ONLY_TABLES = ("alembic_version",)

_DML = "SELECT, INSERT, UPDATE, DELETE"


class RlsBypassError(RuntimeError):
    """The application is connected as a role that ignores row-level security."""


def _checked(role: str) -> str:
    if not _ROLE_NAME.match(role):
        raise ValueError(f"invalid role name {role!r}: use lower-case letters, digits and _")
    return role


def _literal(value: str) -> str:
    """A SQL string literal. CREATE/ALTER ROLE can't take a bound parameter
    for the password, so it is quoted here (standard_conforming_strings is
    on in every supported PostgreSQL, so doubling quotes is sufficient)."""
    if "\x00" in value:
        raise ValueError("a password can't contain a NUL character")
    return "'" + value.replace("'", "''") + "'"


def ensure_app_role(conn: Connection, *, role: str, password: str) -> None:
    """Creates the application role, or resets an existing one to a plain
    login role: never a superuser, never able to bypass row-level security,
    create databases or create roles. Idempotent. Needs a connection with
    the CREATEROLE privilege (the migration owner, or a superuser)."""
    name = _checked(role)
    if not password:
        raise ValueError("the application role needs a password")
    attributes = (
        f"LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {_literal(password)}"
    )
    exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": name})
    verb = "ALTER" if exists else "CREATE"
    conn.execute(text(f"{verb} ROLE {name} WITH {attributes}"))


def grant_app_role(conn: Connection, *, role: str, schema: str = "public") -> None:
    """Gives the application role read and write access to every table in
    the schema (but not the migration bookkeeping), now and for tables the
    connected role creates later. Run as the role that owns the tables,
    after every migration; idempotent."""
    name = _checked(role)
    schema_name = _checked(schema)
    conn.execute(text(f"GRANT USAGE ON SCHEMA {schema_name} TO {name}"))
    conn.execute(text(f"GRANT {_DML} ON ALL TABLES IN SCHEMA {schema_name} TO {name}"))
    conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema_name} TO {name}"))
    conn.execute(
        text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema_name} GRANT {_DML} ON TABLES TO {name}")
    )
    conn.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema_name} "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {name}"
        )
    )
    for table in _MIGRATION_ONLY_TABLES:
        present = conn.scalar(text("SELECT to_regclass(:table)"), {"table": f"{schema}.{table}"})
        if present is not None:
            conn.execute(text(f"REVOKE ALL ON {schema_name}.{table} FROM {name}"))


def bypasses_rls(conn: Connection) -> bool:
    """Whether the connected role ignores row-level security policies: a
    superuser, a BYPASSRLS role, or the owner (or a member inheriting from
    the owner) of a table whose policies aren't FORCEd on its owner."""
    row = conn.execute(
        text(
            "SELECT r.rolsuper OR r.rolbypassrls OR EXISTS ("
            "  SELECT 1 FROM pg_class c"
            "  JOIN pg_namespace n ON n.oid = c.relnamespace"
            "  WHERE n.nspname = current_schema() AND c.relkind = 'r'"
            "    AND c.relrowsecurity AND NOT c.relforcerowsecurity"
            "    AND pg_has_role(current_user, c.relowner, 'USAGE'))"
            " FROM pg_roles r WHERE r.rolname = current_user"
        )
    ).scalar()
    return bool(row)


def check_app_connection(conn: Connection, *, enforce: bool) -> bool:
    """Run at startup. Returns True when tenant isolation is enforced by the
    database. When it isn't, logs a warning, or with `enforce` refuses to
    start, so a misconfigured deployment can't quietly serve every
    organisation's rows to any query that forgets its own filter."""
    if not bypasses_rls(conn):
        return True
    user = conn.scalar(text("SELECT current_user"))
    message = (
        f"the database role {user!r} is a superuser, has BYPASSRLS or owns the tables, "
        "so row-level security is not enforced; connect the application as an ordinary role "
        "(see docs/operations/runbook.md, 'Database roles')"
    )
    if enforce:
        raise RlsBypassError(message)
    logger.warning(message)
    return False
