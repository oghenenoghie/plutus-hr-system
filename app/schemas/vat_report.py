import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class VatReportGroup(BaseModel):
    """Documents of one VAT rate: "VAT 7.5%", "VAT exempt", "Zero-rated", a
    named rate, or none recorded."""

    label: str
    treatment: str | None
    rate_ppm: int
    document_count: int
    net_minor: int
    vat_minor: int


class VatReportDocument(BaseModel):
    kind: Literal["invoice", "credit_note", "bill"]
    id: uuid.UUID
    number: str
    date: date
    party_name: str
    rate_label: str
    # A credit note's figures are negative: it takes back output VAT.
    net_minor: int
    vat_minor: int


class VatReportOut(BaseModel):
    year: int
    month: int
    period_start: date
    period_end: date
    currency: str
    country_code: str
    # Output VAT: charged to customers on invoices sent in the month, less
    # what credit notes issued in the month took back.
    output_groups: list[VatReportGroup]
    sales_net_minor: int
    vat_charged_minor: int
    credit_note_count: int
    credit_note_net_minor: int
    credit_note_vat_minor: int
    output_vat_minor: int
    # Input VAT: charged by vendors on bills dated in the month and approved.
    input_groups: list[VatReportGroup]
    purchases_net_minor: int
    input_vat_minor: int
    # Output less input: positive is owed to the tax authority, negative is
    # a credit to carry forward or claim back.
    net_vat_minor: int
    position: Literal["payable", "refundable", "nil"]
    draft_invoice_count: int
    draft_bill_count: int
    documents: list[VatReportDocument]
    generated_at: datetime
