import csv
import io
import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.schemas.employees import EmployeeCreate
from app.services.employee_provisioning import assign_unique_login_code


@dataclass(frozen=True)
class EmployeeImportRowError:
    row: int
    employee_number: str | None
    error: str


@dataclass(frozen=True)
class EmployeeImportResult:
    created: list[Employee]
    row_errors: list[EmployeeImportRowError]


def bulk_import_employees(
    db: Session, *, org_id: uuid.UUID, csv_content: str
) -> EmployeeImportResult:
    """Parses csv_content (a header row plus one row per employee, column
    names matching EmployeeCreate's field names) and creates one Employee
    per valid row.

    Per-row, not all-or-nothing: each row is attempted in its own
    savepoint, so a single bad row (a validation failure, a duplicate
    employee_number, or a login-code collision) is skipped and reported
    without losing the rows already created in the same call. The product
    skill calls bulk import "the single most important adoption feature"
    for onboarding a few hundred staff at once — forcing a full re-upload
    over one typo would defeat that.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    created: list[Employee] = []
    row_errors: list[EmployeeImportRowError] = []

    for index, raw_row in enumerate(reader, start=2):  # header is row 1
        employee_number = (raw_row.get("employee_number") or "").strip() or None
        # An empty cell means "not provided" for every optional column —
        # pydantic would otherwise reject e.g. an empty manager_id as an
        # invalid UUID rather than treating it as absent.
        cleaned = {k: v.strip() for k, v in raw_row.items() if k and v and v.strip()}

        try:
            parsed = EmployeeCreate.model_validate(cleaned)
        except ValidationError as exc:
            row_errors.append(
                EmployeeImportRowError(
                    row=index, employee_number=employee_number, error=exc.errors()[0]["msg"]
                )
            )
            continue

        employee = Employee(org_id=org_id, **parsed.model_dump())
        try:
            with db.begin_nested():
                db.add(employee)
                db.flush()
        except IntegrityError:
            row_errors.append(
                EmployeeImportRowError(
                    row=index,
                    employee_number=employee_number,
                    error="employee_number already exists in this org",
                )
            )
            continue

        if not assign_unique_login_code(db, employee):
            row_errors.append(
                EmployeeImportRowError(
                    row=index,
                    employee_number=employee_number,
                    error="could not assign a unique login code",
                )
            )
            continue

        created.append(employee)

    return EmployeeImportResult(created=created, row_errors=row_errors)
