"""One-off account creation for environments with no signup endpoint yet.

Reads SEED_EMAIL / SEED_PASSWORD / SEED_ROLE (one of Role's values) / an
optional SEED_ORG_NAME from the environment, creates an Organisation +
Account + Membership, and prints the resulting ids. Intended to be run with
DATABASE_URL already pointed at the target database (e.g. via
`railway run --service plutus-api -- uv run python scripts/seed_login.py`).
"""

import os
import uuid

from app.core.db import get_session_factory, tenant_session
from app.core.security import hash_password
from app.models import Account, Membership, Organisation, Role
from app.services.chart_accounts import seed_default_chart_of_accounts


def main() -> None:
    email = os.environ["SEED_EMAIL"]
    password = os.environ["SEED_PASSWORD"]
    role = Role(os.environ.get("SEED_ROLE", "manager"))
    org_name = os.environ.get("SEED_ORG_NAME", "Demo Co")

    org_id, account_id = uuid.uuid4(), uuid.uuid4()

    with tenant_session(org_id, account_id, role.value) as db:
        db.add(Organisation(id=org_id, name=org_name))
        db.flush()
        seed_default_chart_of_accounts(db, org_id=org_id)

    session = get_session_factory()()
    try:
        session.add(Account(id=account_id, email=email, password_hash=hash_password(password)))
        session.add(Membership(account_id=account_id, org_id=org_id, role=role))
        session.commit()
    finally:
        session.close()

    print(f"created account_id={account_id} org_id={org_id} email={email} role={role.value}")


if __name__ == "__main__":
    main()
