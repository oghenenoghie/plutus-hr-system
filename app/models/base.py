from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OrgScoped:
    """Marks a model whose rows the ORM only ever loads for the session's
    own organisation (app.core.db adds `org_id = <session org>` to every
    SELECT that touches it). RLS already gives that isolation on a normal
    connection; repeating it in the query keeps it on a role that bypasses
    RLS — a superuser, which is what the desktop's embedded database runs
    as. Opt-in per model: every subclass must have an `org_id` column."""
