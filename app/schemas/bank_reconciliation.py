import uuid
from datetime import date, datetime

from pydantic import BaseModel


class BankStatementLineImportRequest(BaseModel):
    transaction_date: date
    description: str
    amount_minor: int
    external_reference: str | None = None


class ImportStatementLinesRequest(BaseModel):
    account_code: str
    lines: list[BankStatementLineImportRequest]


class MatchStatementLineRequest(BaseModel):
    ledger_entry_id: uuid.UUID


class BankStatementLineOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    account_code: str
    transaction_date: date
    description: str
    amount_minor: int
    external_reference: str | None
    matched_ledger_entry_id: uuid.UUID | None
    matched_at: datetime | None
    matched_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReconciliationLedgerEntryOut(BaseModel):
    """A slimmer view of LedgerEntry than app.schemas.general_ledger's own
    LedgerEntryOut — this one is built straight from the ORM row with no
    account-name enrichment, since all a reconciler needs here is enough
    to eyeball a match against a bank statement line."""

    id: uuid.UUID
    account: str
    debit_minor: int
    credit_minor: int
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReconciliationStatusOut(BaseModel):
    unmatched_statement_lines: list[BankStatementLineOut]
    unmatched_ledger_entries: list[ReconciliationLedgerEntryOut]

    model_config = {"from_attributes": True}
