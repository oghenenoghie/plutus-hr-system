import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.fixed_asset import FixedAsset, FixedAssetStatus
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.general_ledger import post_manual_journal_entry


def register_fixed_asset(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    asset_tag: str,
    acquisition_date: date,
    cost_minor: int,
    salvage_value_minor: int = 0,
    useful_life_months: int,
    cash_account_code: str = "cash",
) -> FixedAsset:
    if cost_minor <= 0:
        raise ValueError("cost_minor must be positive")
    if salvage_value_minor < 0:
        raise ValueError("salvage_value_minor cannot be negative")
    if salvage_value_minor >= cost_minor:
        raise ValueError("salvage_value_minor must be less than cost_minor")
    if useful_life_months <= 0:
        raise ValueError("useful_life_months must be positive")

    post_manual_journal_entry(
        db,
        org_id=org_id,
        description=f"Acquired fixed asset {asset_tag}",
        lines=[
            JournalEntryLineCreate(account_code="fixed_assets", debit_minor=cost_minor),
            JournalEntryLineCreate(account_code=cash_account_code, credit_minor=cost_minor),
        ],
    )

    asset = FixedAsset(
        org_id=org_id,
        name=name,
        asset_tag=asset_tag,
        acquisition_date=acquisition_date,
        cost_minor=cost_minor,
        salvage_value_minor=salvage_value_minor,
        useful_life_months=useful_life_months,
    )
    db.add(asset)
    db.flush()
    return asset


def record_depreciation(db: Session, asset: FixedAsset) -> FixedAsset:
    if asset.status != FixedAssetStatus.ACTIVE:
        raise ValueError("only an active asset can be depreciated")

    depreciable_amount = asset.cost_minor - asset.salvage_value_minor
    remaining = depreciable_amount - asset.accumulated_depreciation_minor
    if remaining <= 0:
        raise ValueError("this asset is already fully depreciated")

    monthly_amount = depreciable_amount // asset.useful_life_months
    amount = min(monthly_amount, remaining)

    post_manual_journal_entry(
        db,
        org_id=asset.org_id,
        description=f"Depreciation for {asset.asset_tag}",
        lines=[
            JournalEntryLineCreate(account_code="depreciation_expense", debit_minor=amount),
            JournalEntryLineCreate(account_code="accumulated_depreciation", credit_minor=amount),
        ],
    )
    asset.accumulated_depreciation_minor += amount
    db.add(asset)
    db.flush()
    return asset


def dispose_fixed_asset(
    db: Session,
    asset: FixedAsset,
    *,
    proceeds_minor: int = 0,
    cash_account_code: str = "cash",
) -> FixedAsset:
    if asset.status != FixedAssetStatus.ACTIVE:
        raise ValueError("this asset has already been disposed")
    if proceeds_minor < 0:
        raise ValueError("proceeds_minor cannot be negative")

    lines = [JournalEntryLineCreate(account_code="fixed_assets", credit_minor=asset.cost_minor)]
    if asset.accumulated_depreciation_minor > 0:
        lines.append(
            JournalEntryLineCreate(
                account_code="accumulated_depreciation",
                debit_minor=asset.accumulated_depreciation_minor,
            )
        )
    if proceeds_minor > 0:
        lines.append(
            JournalEntryLineCreate(account_code=cash_account_code, debit_minor=proceeds_minor)
        )

    # Plug the gain or loss so the entry balances: book_value is what's
    # being removed from the books net of what's recovered as proceeds.
    book_value = asset.cost_minor - asset.accumulated_depreciation_minor
    shortfall = book_value - proceeds_minor
    if shortfall > 0:
        lines.append(
            JournalEntryLineCreate(account_code="disposal_gain_loss", debit_minor=shortfall)
        )
    elif shortfall < 0:
        lines.append(
            JournalEntryLineCreate(account_code="disposal_gain_loss", credit_minor=-shortfall)
        )

    post_manual_journal_entry(
        db,
        org_id=asset.org_id,
        description=f"Disposed fixed asset {asset.asset_tag}",
        lines=lines,
    )

    asset.status = FixedAssetStatus.DISPOSED
    asset.disposed_at = datetime.now(UTC)
    asset.disposal_proceeds_minor = proceeds_minor
    db.add(asset)
    db.flush()
    return asset
