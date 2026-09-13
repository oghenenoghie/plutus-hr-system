import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.aging import AgingBucket, bucket_for
from app.models.bill import Bill, BillStatus
from app.models.customer import Customer
from app.models.department import Department
from app.models.employee import Employee
from app.models.invoice import Invoice, InvoiceStatus
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip
from app.models.vendor import Vendor


@dataclass(frozen=True)
class PayrollCostLine:
    """One (locked pay run, department) cell of the cross-run cost report.
    department_id/department_name are None for employees not assigned to
    any department — grouped together rather than dropped, since that
    headcount is still real payroll cost."""

    pay_run_id: uuid.UUID
    period_start: date
    period_end: date
    department_id: uuid.UUID | None
    department_name: str | None
    employee_count: int
    gross_minor: int
    employer_cost_minor: int
    net_minor: int


def payroll_cost_by_department(
    db: Session,
    org_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[PayrollCostLine]:
    """Payroll cost trended across every locked pay run, broken down by
    department — hr-payroll's cross-run department cost-centre report.
    Only LOCKED runs count: a draft/validated run's figures aren't final
    yet, and a reversed run's are void (same reasoning as
    cumulative_totals_before excluding both).
    """
    query = (
        select(
            PayRun.id,
            PayRun.period_start,
            PayRun.period_end,
            Employee.department_id,
            Department.name,
            func.count(Payslip.id),
            func.coalesce(func.sum(Payslip.gross_minor), 0),
            func.coalesce(func.sum(Payslip.gross_minor + Payslip.pension_employer_minor), 0),
            func.coalesce(func.sum(Payslip.net_minor), 0),
        )
        .select_from(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .join(Employee, Payslip.employee_id == Employee.id)
        .outerjoin(Department, Employee.department_id == Department.id)
        .where(PayRun.org_id == org_id, PayRun.status == PayRunStatus.LOCKED)
        .group_by(
            PayRun.id,
            PayRun.period_start,
            PayRun.period_end,
            Employee.department_id,
            Department.name,
        )
        .order_by(PayRun.period_end, Department.name)
    )
    if from_date is not None:
        query = query.where(PayRun.period_end >= from_date)
    if to_date is not None:
        query = query.where(PayRun.period_end <= to_date)

    return [
        PayrollCostLine(
            pay_run_id=pay_run_id,
            period_start=period_start,
            period_end=period_end,
            department_id=department_id,
            department_name=department_name,
            employee_count=employee_count,
            gross_minor=int(gross_minor),
            employer_cost_minor=int(employer_cost_minor),
            net_minor=int(net_minor),
        )
        for (
            pay_run_id,
            period_start,
            period_end,
            department_id,
            department_name,
            employee_count,
            gross_minor,
            employer_cost_minor,
            net_minor,
        ) in db.execute(query).all()
    ]


@dataclass(frozen=True)
class AgingLine:
    """One open bill or invoice as of the report date, with the aging
    bucket it falls into. Only APPROVED bills / SENT invoices count as
    "open" — a DRAFT hasn't posted a payable/receivable yet, and PAID/VOID
    are closed, so there's nothing left to age."""

    entity_id: uuid.UUID
    counterparty_name: str
    reference_number: str
    due_date: date
    amount_minor: int
    bucket: AgingBucket


def ap_aging_report(db: Session, org_id: uuid.UUID, *, as_of: date) -> list[AgingLine]:
    rows = db.execute(
        select(Bill.id, Vendor.name, Bill.bill_number, Bill.due_date, Bill.amount_minor)
        .join(Vendor, Bill.vendor_id == Vendor.id)
        .where(Bill.org_id == org_id, Bill.status == BillStatus.APPROVED)
        .order_by(Bill.due_date)
    ).all()
    return [
        AgingLine(
            entity_id=bill_id,
            counterparty_name=vendor_name,
            reference_number=bill_number,
            due_date=due_date,
            amount_minor=amount_minor,
            bucket=bucket_for(due_date, as_of),
        )
        for bill_id, vendor_name, bill_number, due_date, amount_minor in rows
    ]


def ar_aging_report(db: Session, org_id: uuid.UUID, *, as_of: date) -> list[AgingLine]:
    rows = db.execute(
        select(
            Invoice.id,
            Customer.name,
            Invoice.invoice_number,
            Invoice.due_date,
            Invoice.amount_minor,
        )
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.org_id == org_id, Invoice.status == InvoiceStatus.SENT)
        .order_by(Invoice.due_date)
    ).all()
    return [
        AgingLine(
            entity_id=invoice_id,
            counterparty_name=customer_name,
            reference_number=invoice_number,
            due_date=due_date,
            amount_minor=amount_minor,
            bucket=bucket_for(due_date, as_of),
        )
        for invoice_id, customer_name, invoice_number, due_date, amount_minor in rows
    ]


@dataclass(frozen=True)
class VendorStatementLine:
    """One bill on a vendor's statement, in bill_date order, with the
    running balance still owed to them after this bill. Since Bill has no
    separate partial-payment records — approval posts the full amount as
    payable, payment clears the full amount at once — "still owed" per
    line is simply the cumulative amount_minor of every bill up to and
    including this one that is currently APPROVED (posted, not yet paid);
    a PAID bill contributes nothing to the running balance and a DRAFT/
    VOID bill never posted a payable to begin with.
    """

    bill_id: uuid.UUID
    bill_number: str
    bill_date: date
    amount_minor: int
    status: BillStatus
    running_balance_minor: int


def vendor_statement(
    db: Session,
    org_id: uuid.UUID,
    vendor_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[VendorStatementLine]:
    query = (
        select(Bill.id, Bill.bill_number, Bill.bill_date, Bill.amount_minor, Bill.status)
        .where(Bill.org_id == org_id, Bill.vendor_id == vendor_id)
        .order_by(Bill.bill_date, Bill.bill_number)
    )
    if from_date is not None:
        query = query.where(Bill.bill_date >= from_date)
    if to_date is not None:
        query = query.where(Bill.bill_date <= to_date)

    lines = []
    running_balance = 0
    for bill_id, bill_number, bill_date, amount_minor, bill_status in db.execute(query).all():
        if bill_status == BillStatus.APPROVED:
            running_balance += amount_minor
        lines.append(
            VendorStatementLine(
                bill_id=bill_id,
                bill_number=bill_number,
                bill_date=bill_date,
                amount_minor=amount_minor,
                status=bill_status,
                running_balance_minor=running_balance,
            )
        )
    return lines
