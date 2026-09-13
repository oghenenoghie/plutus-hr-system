from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import generate_login_code
from app.models.employee import Employee

_LOGIN_CODE_MAX_ATTEMPTS = 5


def assign_unique_login_code(db: Session, employee: Employee) -> bool:
    """login_code is unique across every org, not just this one, so a
    within-org RLS-scoped SELECT can't reliably check it for collisions —
    the Postgres unique index enforces uniqueness across the whole table
    regardless of RLS, so this attempts the insert and retries on the rare
    collision instead of pre-checking. A savepoint keeps a failed attempt
    from poisoning the outer transaction. Returns False (rather than
    raising) once every attempt has collided, so a caller creating many
    employees in one call (bulk import) can record that as a single row's
    failure instead of aborting the whole batch.
    """
    for _ in range(_LOGIN_CODE_MAX_ATTEMPTS):
        employee.login_code = generate_login_code()
        try:
            with db.begin_nested():
                db.flush()
            return True
        except IntegrityError:
            continue
    return False
