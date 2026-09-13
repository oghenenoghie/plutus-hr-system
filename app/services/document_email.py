"""Emails a rendered accounting PDF (invoice, bill, or statement) as an
attachment. Unlike payslip_delivery.py, these don't record a delivery-log
row — that log exists for payslips because it's a compliance-relevant,
audited record of what was sent to whom; a copy of an invoice or bill is
a lighter-weight "send me this" action, so a failure surfaces directly to
the caller as an exception rather than a background task's silent log
entry.
"""

from datetime import date

from app.models.bill import Bill
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.organisation import Organisation
from app.models.vendor import Vendor
from app.schemas.financial_statements import BalanceSheetOut, IncomeStatementOut
from app.services.bill_pdf import render_bill_pdf
from app.services.email import send_email_with_attachment
from app.services.financial_statement_pdf import (
    render_balance_sheet_pdf,
    render_income_statement_pdf,
)
from app.services.invoice_pdf import render_invoice_pdf
from app.services.reports import CustomerStatementLine, VendorStatementLine
from app.services.statement_pdf import render_customer_statement_pdf, render_vendor_statement_pdf


def email_invoice_pdf(
    *, organisation: Organisation, invoice: Invoice, customer: Customer, to: str | None = None
) -> str:
    recipient = to or customer.contact_email
    if not recipient:
        raise ValueError("customer has no contact email on file")
    pdf_bytes = render_invoice_pdf(organisation=organisation, invoice=invoice, customer=customer)
    return send_email_with_attachment(
        to=recipient,
        subject=f"Invoice {invoice.invoice_number} from {organisation.name}",
        html_body=f"<p>Please find attached invoice {invoice.invoice_number}.</p>",
        attachment_bytes=pdf_bytes,
        attachment_filename=f"invoice-{invoice.invoice_number}.pdf",
    )


def email_bill_pdf(
    *, organisation: Organisation, bill: Bill, vendor: Vendor, to: str | None = None
) -> str:
    recipient = to or vendor.contact_email
    if not recipient:
        raise ValueError("vendor has no contact email on file")
    pdf_bytes = render_bill_pdf(organisation=organisation, bill=bill, vendor=vendor)
    return send_email_with_attachment(
        to=recipient,
        subject=f"Bill {bill.bill_number} from {organisation.name}",
        html_body=f"<p>Please find attached bill {bill.bill_number}.</p>",
        attachment_bytes=pdf_bytes,
        attachment_filename=f"bill-{bill.bill_number}.pdf",
    )


def email_vendor_statement_pdf(
    *,
    organisation: Organisation,
    vendor: Vendor,
    lines: list[VendorStatementLine],
    from_date: date | None,
    to_date: date | None,
    to: str | None = None,
) -> str:
    recipient = to or vendor.contact_email
    if not recipient:
        raise ValueError("vendor has no contact email on file")
    pdf_bytes = render_vendor_statement_pdf(
        organisation=organisation, vendor=vendor, lines=lines, from_date=from_date, to_date=to_date
    )
    return send_email_with_attachment(
        to=recipient,
        subject=f"Statement of account from {organisation.name}",
        html_body=f"<p>Please find attached your statement of account with {organisation.name}.</p>",
        attachment_bytes=pdf_bytes,
        attachment_filename=f"statement-{vendor.name}.pdf",
    )


def email_customer_statement_pdf(
    *,
    organisation: Organisation,
    customer: Customer,
    lines: list[CustomerStatementLine],
    from_date: date | None,
    to_date: date | None,
    to: str | None = None,
) -> str:
    recipient = to or customer.contact_email
    if not recipient:
        raise ValueError("customer has no contact email on file")
    pdf_bytes = render_customer_statement_pdf(
        organisation=organisation,
        customer=customer,
        lines=lines,
        from_date=from_date,
        to_date=to_date,
    )
    return send_email_with_attachment(
        to=recipient,
        subject=f"Statement of account from {organisation.name}",
        html_body=f"<p>Please find attached your statement of account with {organisation.name}.</p>",
        attachment_bytes=pdf_bytes,
        attachment_filename=f"statement-{customer.name}.pdf",
    )


def email_balance_sheet_pdf(
    *, organisation: Organisation, statement: BalanceSheetOut, to: str
) -> str:
    pdf_bytes = render_balance_sheet_pdf(organisation=organisation, statement=statement)
    return send_email_with_attachment(
        to=to,
        subject=f"Balance Sheet — {organisation.name}",
        html_body="<p>Please find attached the balance sheet.</p>",
        attachment_bytes=pdf_bytes,
        attachment_filename="balance-sheet.pdf",
    )


def email_income_statement_pdf(
    *, organisation: Organisation, statement: IncomeStatementOut, to: str
) -> str:
    pdf_bytes = render_income_statement_pdf(organisation=organisation, statement=statement)
    return send_email_with_attachment(
        to=to,
        subject=f"Income Statement — {organisation.name}",
        html_body="<p>Please find attached the income statement.</p>",
        attachment_bytes=pdf_bytes,
        attachment_filename="income-statement.pdf",
    )
