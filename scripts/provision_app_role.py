"""Creates (or resets) the ordinary database role the API connects as, so
row-level security applies to it (see app/core/db_roles.py and
docs/operations/runbook.md, "Database roles").

Reads from the environment:
- MIGRATION_DATABASE_URL, else DATABASE_URL: a connection as the role that
  owns the tables (the one migrations run as);
- APP_DATABASE_ROLE (default plutus_app): the role to create;
- APP_DATABASE_PASSWORD: its password (required; never printed).

Idempotent: run it again to reset the password or re-grant. Example:
`railway run --service plutus-api -- uv run python -m scripts.provision_app_role`
"""

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.db_roles import bypasses_rls, ensure_app_role, grant_app_role


def main() -> int:
    settings = get_settings()
    owner_url = settings.migration_database_url or settings.database_url
    role = os.environ.get("APP_DATABASE_ROLE") or "plutus_app"
    password = os.environ.get("APP_DATABASE_PASSWORD", "")
    if not password:
        print("APP_DATABASE_PASSWORD is required", file=sys.stderr)
        return 2

    owner = create_engine(owner_url)
    with owner.begin() as conn:
        ensure_app_role(conn, role=role, password=password)
        grant_app_role(conn, role=role)
    owner.dispose()

    app = create_engine(make_url(owner_url).set(username=role, password=password))
    with app.connect() as conn:
        bypassed = bypasses_rls(conn)
    app.dispose()
    if bypassed:
        print(f"role {role} still bypasses row-level security", file=sys.stderr)
        return 1

    shown = make_url(owner_url).set(username=role).render_as_string(hide_password=True)
    print(f"role {role} is ready and subject to row-level security.")
    print("Set DATABASE_URL to the same server and database as this role, e.g.")
    print(f"  {shown}   (with APP_DATABASE_PASSWORD in place of ***)")
    print(f"and MIGRATION_DATABASE_URL to the owner URL, APP_DATABASE_ROLE={role},")
    print("then REQUIRE_RLS_ENFORCED=true once the API has restarted on the new role.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
