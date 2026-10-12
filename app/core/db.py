from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker, with_loader_criteria

from app.core.config import get_settings
from app.models.base import Base, OrgScoped

# Session.info key holding the organisation a tenant or system session is
# scoped to.
SESSION_ORG_KEY = "org_id"


@event.listens_for(Session, "do_orm_execute")
def _scope_org_owned_rows(state: ORMExecuteState) -> None:
    """Adds `org_id = <session org>` for every OrgScoped model in a SELECT,
    including joins and subqueries — the multi-tenant pattern from the
    SQLAlchemy docs. A session with no org set (pre-auth lookups) is left
    alone."""
    org_id = state.session.info.get(SESSION_ORG_KEY)
    if org_id is None or not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    state.statement = state.statement.options(
        *(
            with_loader_criteria(model, lambda cls: cls.org_id == org_id, include_aliases=True)
            for model in _org_scoped_models()
        )
    )


def _org_scoped_models() -> list[type]:
    # Per concrete model rather than the mixin itself: the criteria needs
    # the model's own org_id column, which the mixin doesn't declare.
    return [
        mapper.class_ for mapper in Base.registry.mappers if issubclass(mapper.class_, OrgScoped)
    ]


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def tenant_session(org_id: UUID, account_id: UUID, role: str) -> Generator[Session, None, None]:
    """Open a transaction scoped to one tenant via a session-local GUC.

    RLS policies read these settings with current_setting(...). set_config(...,
    true) is the parameterized equivalent of SET LOCAL — SET itself does not
    accept bind parameters over the wire — and is just as transaction-scoped,
    so it cannot leak across pooled connections. A query that runs without
    this context set sees nothing, not everything.
    """
    session = get_session_factory()()
    session.info[SESSION_ORG_KEY] = org_id
    try:
        session.execute(
            text("SELECT set_config('app.current_org', :org_id, true)"), {"org_id": str(org_id)}
        )
        session.execute(
            text("SELECT set_config('app.current_account', :account_id, true)"),
            {"account_id": str(account_id)},
        )
        session.execute(text("SELECT set_config('app.current_role', :role, true)"), {"role": role})
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def system_session(org_id: UUID) -> Generator[Session, None, None]:
    """Like tenant_session, but for a scheduled job with no acting account
    or role — only app.current_org is set, since that's the only GUC any
    RLS policy actually reads (app.current_account/app.current_role are set
    by tenant_session for requests but have no policy consuming them yet).
    """
    session = get_session_factory()()
    session.info[SESSION_ORG_KEY] = org_id
    try:
        session.execute(
            text("SELECT set_config('app.current_org', :org_id, true)"), {"org_id": str(org_id)}
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_untenanted_session() -> Generator[Session, None, None]:
    """A plain session with no tenant GUC set, for pre-auth identity lookups
    (accounts, memberships) that are not tenant business data and carry no RLS.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
