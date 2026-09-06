import uuid

from sqlalchemy import text

from app.core.db import get_session_factory, tenant_session
from app.models import Organisation


def _create_org(name: str) -> uuid.UUID:
    """Org creation has no tenant context yet, so the id is generated first
    and the insert runs inside a tenant_session scoped to that same id —
    satisfying the RLS policy's WITH CHECK without needing a bypass role.
    """
    org_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name=name))
    return org_id


def test_tenant_session_only_sees_its_own_organisation() -> None:
    org_a = _create_org("Org A")
    org_b = _create_org("Org B")

    with tenant_session(org_a, uuid.uuid4(), "admin") as db:
        visible = {org.id for org in db.execute(text("SELECT id FROM organisations")).mappings()}
        assert visible == {org_a}
        assert org_b not in visible


def test_no_tenant_context_sees_nothing() -> None:
    """A query that runs without the GUC set sees nothing, not everything —
    deny by default, per the tenant_session contract."""
    _create_org("Org C")
    session = get_session_factory()()
    try:
        rows = session.execute(text("SELECT id FROM organisations")).fetchall()
        assert rows == []
    finally:
        session.close()
