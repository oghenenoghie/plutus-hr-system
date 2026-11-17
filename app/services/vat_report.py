"""The monthly VAT report: output VAT charged to customers, input VAT charged
by vendors, and the net the organisation owes the tax authority (or can
carry forward).

Built from the documents rather than the ledger, so it can show each VAT
rate's net and VAT, exempt and zero-rated supplies included, as a VAT return
asks for them. Only documents that have posted count: invoices once sent,
bills once approved, credit notes when issued. Each is reported in the month
of its own date (an invoice's issue date, a bill's date, a credit note's
issue date).
"""

import calendar
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bill import Bill, BillStatus
from app.models.credit_note import CreditNote
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.models.vendor import Vendor
from app.schemas.vat_report import VatReportDocument, VatReportGroup, VatReportOut
from app.services.credit_notes import credit_note_vat_parts

NO_VAT_RECORDED = "No VAT recorded"
VAT_ENTERED = "VAT (amount entered)"

_POSTED_INVOICE = (InvoiceStatus.SENT, InvoiceStatus.PAID)
_POSTED_BILL = (BillStatus.APPROVED, BillStatus.PAID)


@dataclass
class _Group:
    label: str
    treatment: str | None
    rate_ppm: int
    count: int = 0
    net_minor: int = 0
    vat_minor: int = 0


@dataclass
class _Groups:
    by_key: dict[tuple[str | None, str, int], _Group] = field(default_factory=dict)

    def add(self, treatment: str | None, label: str, rate_ppm: int, net: int, vat: int) -> None:
        key = (treatment, label, rate_ppm)
        group = self.by_key.setdefault(key, _Group(label, treatment, rate_ppm))
        group.count += 1
        group.net_minor += net
        group.vat_minor += vat

    def out(self) -> list[VatReportGroup]:
        order = {"standard": 0, "other": 1, "zero_rated": 2, "exempt": 3, None: 4}
        groups = sorted(
            self.by_key.values(), key=lambda g: (order.get(g.treatment, 5), -g.rate_ppm, g.label)
        )
        return [
            VatReportGroup(
                label=g.label,
                treatment=g.treatment,
                rate_ppm=g.rate_ppm,
                document_count=g.count,
                net_minor=g.net_minor,
                vat_minor=g.vat_minor,
            )
            for g in groups
        ]


def month_bounds(year: int, month: int) -> tuple[date, date]:
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    if not 2000 <= year <= 2100:
        raise ValueError("year is out of range")
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _names[M](db: Session, model: type[M], ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = db.execute(
        select(model.id, model.name).where(model.id.in_(wanted))  # type: ignore[attr-defined]
    )
    return {row_id: name for row_id, name in rows}


def _invoice_label(invoice: Invoice) -> str:
    return invoice.vat_rate_name or NO_VAT_RECORDED


def _bill_label(bill: Bill) -> str:
    if bill.vat_rate_name:
        return bill.vat_rate_name
    return VAT_ENTERED if bill.vat_minor else NO_VAT_RECORDED


def vat_report(db: Session, *, org_id: uuid.UUID, year: int, month: int) -> VatReportOut:
    start, end = month_bounds(year, month)
    organisation = db.get(Organisation, org_id)
    if organisation is None:
        raise LookupError("organisation not found")

    invoices = list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.org_id == org_id,
                Invoice.status.in_(_POSTED_INVOICE),
                Invoice.issue_date.between(start, end),
            )
            .order_by(Invoice.issue_date, Invoice.invoice_number)
        )
    )
    credit_notes = list(
        db.scalars(
            select(CreditNote)
            .where(CreditNote.org_id == org_id, CreditNote.issue_date.between(start, end))
            .order_by(CreditNote.issue_date, CreditNote.credit_note_number)
        )
    )
    bills = list(
        db.scalars(
            select(Bill)
            .where(
                Bill.org_id == org_id,
                Bill.status.in_(_POSTED_BILL),
                Bill.bill_date.between(start, end),
            )
            .order_by(Bill.bill_date, Bill.bill_number)
        )
    )

    # A credit note's VAT depends on the credits before it on the same
    # invoice, wherever they fall, so replay each invoice's credits in order.
    credited_invoices = {
        invoice.id: invoice
        for invoice in db.scalars(
            select(Invoice).where(Invoice.id.in_({note.invoice_id for note in credit_notes}))
        )
    }
    note_vat: dict[uuid.UUID, int] = {}
    if credited_invoices:
        history: dict[uuid.UUID, list[CreditNote]] = defaultdict(list)
        for note in db.scalars(
            select(CreditNote)
            .where(CreditNote.invoice_id.in_(credited_invoices))
            .order_by(CreditNote.created_at, CreditNote.id)
        ):
            history[note.invoice_id].append(note)
        for invoice_id, notes in history.items():
            parts = credit_note_vat_parts(
                credited_invoices[invoice_id], [note.amount_minor for note in notes]
            )
            note_vat.update({note.id: part for note, part in zip(notes, parts, strict=True)})

    customers = _names(
        db,
        Customer,
        [i.customer_id for i in invoices] + [i.customer_id for i in credited_invoices.values()],
    )
    vendors = _names(db, Vendor, [b.vendor_id for b in bills])

    documents: list[VatReportDocument] = []
    output = _Groups()
    for invoice in invoices:
        label = _invoice_label(invoice)
        output.add(
            invoice.vat_treatment,
            label,
            invoice.vat_rate_ppm,
            invoice.amount_minor,
            invoice.vat_minor,
        )
        documents.append(
            VatReportDocument(
                kind="invoice",
                id=invoice.id,
                number=invoice.invoice_number,
                date=invoice.issue_date,
                party_name=customers.get(invoice.customer_id, ""),
                rate_label=label,
                net_minor=invoice.amount_minor,
                vat_minor=invoice.vat_minor,
            )
        )
    credit_net = credit_vat = 0
    for note in credit_notes:
        invoice = credited_invoices[note.invoice_id]
        vat = note_vat.get(note.id, 0)
        credit_net += note.amount_minor - vat
        credit_vat += vat
        documents.append(
            VatReportDocument(
                kind="credit_note",
                id=note.id,
                number=note.credit_note_number,
                date=note.issue_date,
                party_name=customers.get(invoice.customer_id, ""),
                rate_label=_invoice_label(invoice),
                net_minor=-(note.amount_minor - vat),
                vat_minor=-vat,
            )
        )

    purchases = _Groups()
    for bill in bills:
        label = _bill_label(bill)
        purchases.add(
            bill.vat_treatment, label, bill.vat_rate_ppm, bill.amount_minor, bill.vat_minor
        )
        documents.append(
            VatReportDocument(
                kind="bill",
                id=bill.id,
                number=bill.bill_number,
                date=bill.bill_date,
                party_name=vendors.get(bill.vendor_id, ""),
                rate_label=label,
                net_minor=bill.amount_minor,
                vat_minor=bill.vat_minor,
            )
        )

    vat_charged = sum(invoice.vat_minor for invoice in invoices)
    output_vat = vat_charged - credit_vat
    input_vat = sum(bill.vat_minor for bill in bills)
    net = output_vat - input_vat
    draft_invoices = db.scalar(
        select(func.count())
        .select_from(Invoice)
        .where(
            Invoice.org_id == org_id,
            Invoice.status == InvoiceStatus.DRAFT,
            Invoice.issue_date.between(start, end),
        )
    )
    draft_bills = db.scalar(
        select(func.count())
        .select_from(Bill)
        .where(
            Bill.org_id == org_id,
            Bill.status == BillStatus.DRAFT,
            Bill.bill_date.between(start, end),
        )
    )
    return VatReportOut(
        year=year,
        month=month,
        period_start=start,
        period_end=end,
        currency=organisation.currency,
        country_code=organisation.country_code,
        output_groups=output.out(),
        sales_net_minor=sum(invoice.amount_minor for invoice in invoices),
        vat_charged_minor=vat_charged,
        credit_note_count=len(credit_notes),
        credit_note_net_minor=credit_net,
        credit_note_vat_minor=credit_vat,
        output_vat_minor=output_vat,
        input_groups=purchases.out(),
        purchases_net_minor=sum(bill.amount_minor for bill in bills),
        input_vat_minor=input_vat,
        net_vat_minor=net,
        position="payable" if net > 0 else "refundable" if net < 0 else "nil",
        draft_invoice_count=int(draft_invoices or 0),
        draft_bill_count=int(draft_bills or 0),
        documents=documents,
        generated_at=datetime.now(UTC),
    )
