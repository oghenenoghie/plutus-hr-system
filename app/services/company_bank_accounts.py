import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chart_account import AccountType, ChartAccount
from app.models.company_bank_account import CompanyBankAccount


def _asset_account_or_raise(db: Session, *, org_id: uuid.UUID, code: str) -> ChartAccount:
    account = db.scalar(
        select(ChartAccount).where(ChartAccount.org_id == org_id, ChartAccount.code == code)
    )
    if account is None or account.type != AccountType.ASSET:
        raise ValueError(f"{code!r} is not a known asset account")
    return account


def register_company_bank_account(
    db: Session,
    *,
    org_id: uuid.UUID,
    bank_name: str,
    account_number: str,
    account_name: str,
    chart_account_code: str,
) -> CompanyBankAccount:
    _asset_account_or_raise(db, org_id=org_id, code=chart_account_code)

    bank_account = CompanyBankAccount(
        org_id=org_id,
        bank_name=bank_name,
        account_number=account_number,
        account_name=account_name,
        chart_account_code=chart_account_code,
    )
    db.add(bank_account)
    db.flush()
    return bank_account


def list_company_bank_accounts(db: Session, *, org_id: uuid.UUID) -> list[CompanyBankAccount]:
    return list(
        db.scalars(
            select(CompanyBankAccount)
            .where(CompanyBankAccount.org_id == org_id)
            .order_by(CompanyBankAccount.created_at)
        )
    )
