import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.general_ledger import LedgerEntryOut


class CompanyBankAccountCreate(BaseModel):
    bank_name: str
    account_number: str
    account_name: str
    chart_account_code: str


class CompanyBankAccountOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    bank_name: str
    account_number: str
    account_name: str
    chart_account_code: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BankStatementLineCreate(BaseModel):
    statement_date: date
    description: str
    amount_minor: int


class BankStatementLineOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    bank_account_id: uuid.UUID
    statement_date: date
    description: str
    amount_minor: int
    matched_ledger_entry_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BankStatementLineMatch(BaseModel):
    ledger_entry_id: uuid.UUID


class ReconciliationSummaryOut(BaseModel):
    bank_account_id: uuid.UUID
    bank_balance_minor: int
    ledger_balance_minor: int
    difference_minor: int
    unmatched_statement_lines: list[BankStatementLineOut]
    unmatched_ledger_entries: list[LedgerEntryOut]
