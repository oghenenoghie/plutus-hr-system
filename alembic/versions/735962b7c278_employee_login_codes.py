"""employee login codes

Revision ID: 735962b7c278
Revises: f10533e504a5
Create Date: 2026-09-12 20:23:16.119430

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '735962b7c278'
down_revision: Union[str, Sequence[str], None] = 'f10533e504a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors app/core/security.py's _LOGIN_CODE_ALPHABET/_LOGIN_CODE_LENGTH.
# Duplicated rather than imported: migrations should stay runnable even if
# that function's definition changes later.
_LOGIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_LOGIN_CODE_LENGTH = 8


def _generate_login_code() -> str:
    return "".join(secrets.choice(_LOGIN_CODE_ALPHABET) for _ in range(_LOGIN_CODE_LENGTH))


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    op.add_column("employees", sa.Column("login_code", sa.String(length=8), nullable=True))

    # Backfill every pre-existing employee with a unique code before the
    # index below makes that constraint permanent. One row at a time with a
    # retry-on-collision loop, same discipline as
    # employees.py::_assign_unique_login_code uses at request time.
    employee_ids = [
        row[0] for row in bind.execute(sa.text("SELECT id FROM employees")).fetchall()
    ]
    for employee_id in employee_ids:
        while True:
            candidate = _generate_login_code()
            try:
                with bind.begin_nested():
                    bind.execute(
                        sa.text(
                            "UPDATE employees SET login_code = :code WHERE id = :id"
                        ),
                        {"code": candidate, "id": employee_id},
                    )
                break
            except sa.exc.IntegrityError:
                continue

    op.create_unique_constraint("uq_employees_login_code", "employees", ["login_code"])
    op.create_index("ix_employees_login_code", "employees", ["login_code"])

    # Projection of employees.(login_code, account_id) kept outside RLS —
    # like accounts/memberships — so /auth/login can resolve a code to an
    # account under the untenanted session it runs in, before any org (and
    # so any tenant_session) is known. employees is FORCE RLS'd, so a
    # SECURITY DEFINER lookup against it directly would still see nothing
    # there; this dedicated table sidesteps that instead of touching the
    # tenant-isolation policy.
    op.create_table(
        "employee_login_codes",
        sa.Column("login_code", sa.String(length=8), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("login_code"),
        sa.UniqueConstraint("employee_id"),
    )

    # Backfill for employees that already have portal access linked.
    op.execute(
        """
        INSERT INTO employee_login_codes (login_code, account_id, employee_id)
        SELECT login_code, account_id, id FROM employees WHERE account_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("employee_login_codes")
    op.drop_index("ix_employees_login_code", table_name="employees")
    op.drop_constraint("uq_employees_login_code", "employees", type_="unique")
    op.drop_column("employees", "login_code")
