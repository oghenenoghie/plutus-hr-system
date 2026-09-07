import csv
import io
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.money import minor_units_exponent
from app.models.bank_account import BankAccount
from app.models.employee import Employee
from app.models.payslip import Payslip

# Single-currency assumption, same as the single-country assumption
# elsewhere — NGN is the only currency this codebase handles today.
_CURRENCY = "NGN"


@dataclass(frozen=True)
class DisbursementResult:
    csv_content: str
    total_minor: int
    skipped_employee_numbers: tuple[str, ...]


def generate_disbursement_file(db: Session, *, pay_run_id: uuid.UUID) -> DisbursementResult:
    """A generic CSV for bulk bank transfer of net pay. This is not any
    specific bank's upload template — column names and layout will need
    mapping to whatever your disbursing bank actually requires before use.

    Employees with no bank account on file, or one not yet verified, are
    skipped and returned separately rather than included with an
    unreliable account number.
    """
    rows = db.execute(
        select(Payslip, Employee, BankAccount)
        .join(Employee, Employee.id == Payslip.employee_id)
        .outerjoin(BankAccount, BankAccount.employee_id == Employee.id)
        .where(Payslip.pay_run_id == pay_run_id)
        .order_by(Employee.employee_number)
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "employee_number",
            "account_name",
            "bank_name",
            "account_number",
            "amount_naira",
            "narration",
        ]
    )

    exponent = minor_units_exponent(_CURRENCY)
    total_minor = 0
    skipped: list[str] = []
    for payslip, employee, bank_account in rows:
        if bank_account is None or not bank_account.verified:
            skipped.append(employee.employee_number)
            continue
        writer.writerow(
            [
                employee.employee_number,
                bank_account.account_name,
                bank_account.bank_name,
                bank_account.account_number,
                f"{payslip.net_minor / (10**exponent):.{exponent}f}",
                f"Salary {payslip.period_start:%Y-%m}",
            ]
        )
        total_minor += payslip.net_minor

    return DisbursementResult(
        csv_content=buffer.getvalue(),
        total_minor=total_minor,
        skipped_employee_numbers=tuple(skipped),
    )
