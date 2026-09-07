import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.chart_account import AccountType


class LedgerEntryOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    journal_entry_id: uuid.UUID
    pay_run_id: uuid.UUID | None
    employee_id: uuid.UUID | None
    account: str
    account_name: str | None
    debit_minor: int
    credit_minor: int
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TrialBalanceLine(BaseModel):
    account: str
    account_name: str | None
    account_type: AccountType | None
    total_debit_minor: int
    total_credit_minor: int
    balance_minor: int


class JournalEntryLineCreate(BaseModel):
    account_code: str
    debit_minor: int = 0
    credit_minor: int = 0
    description: str | None = None


class JournalEntryCreate(BaseModel):
    description: str
    lines: list[JournalEntryLineCreate]
