import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fixed_asset import (
    AssetAssignmentStatus,
    FixedAsset,
    FixedAssetCategory,
    FixedAssetStatus,
)
from app.models.fixed_asset_assignment import FixedAssetAssignment
from app.models.fixed_asset_revaluation import FixedAssetRevaluation
from app.models.fixed_asset_transfer import FixedAssetTransfer
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.general_ledger import post_manual_journal_entry

# Categories that must be handed to a specific person at creation, the
# same rule HR's retired CompanyAsset never enforced (which is exactly
# how the two records used to drift apart) — a laptop/phone/vehicle
# doesn't just exist, it's issued to someone from day one.
_REQUIRES_ASSIGNEE = frozenset(
    {FixedAssetCategory.LAPTOP, FixedAssetCategory.PHONE, FixedAssetCategory.VEHICLE}
)


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
    category: FixedAssetCategory | None = None,
    assigned_employee_id: uuid.UUID | None = None,
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
    if category in _REQUIRES_ASSIGNEE and assigned_employee_id is None:
        raise ValueError(f"{category.value} assets must be assigned to an employee")

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
        category=category,
        assignment_status=AssetAssignmentStatus.AVAILABLE if category is not None else None,
    )
    db.add(asset)
    db.flush()

    if assigned_employee_id is not None:
        assign_fixed_asset(
            db,
            asset,
            org_id=org_id,
            employee_id=assigned_employee_id,
            assigned_date=acquisition_date,
        )
    return asset


def assign_fixed_asset(
    db: Session,
    asset: FixedAsset,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    assigned_date: date,
) -> FixedAssetAssignment:
    if asset.assignment_status != AssetAssignmentStatus.AVAILABLE:
        status_label = asset.assignment_status.value if asset.assignment_status else "untracked"
        raise ValueError(f"asset is {status_label}, not available")

    assignment = FixedAssetAssignment(
        org_id=org_id,
        fixed_asset_id=asset.id,
        employee_id=employee_id,
        assigned_date=assigned_date,
    )
    asset.assignment_status = AssetAssignmentStatus.ASSIGNED
    asset.assigned_employee_id = employee_id
    db.add_all([assignment, asset])
    db.flush()
    return assignment


def return_fixed_asset(
    db: Session,
    assignment: FixedAssetAssignment,
    asset: FixedAsset,
    *,
    returned_date: date,
    condition_notes: str | None = None,
) -> FixedAssetAssignment:
    if assignment.returned_date is not None:
        raise ValueError("this assignment has already been returned")
    if returned_date < assignment.assigned_date:
        raise ValueError("returned_date must not be before assigned_date")

    assignment.returned_date = returned_date
    assignment.condition_notes = condition_notes
    asset.assignment_status = AssetAssignmentStatus.AVAILABLE
    asset.assigned_employee_id = None
    db.add_all([assignment, asset])
    db.flush()
    return assignment


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

    # A disposed asset can't still be "held" by anyone — auto-close any
    # open assignment the same way a return would, rather than leaving it
    # dangling as ASSIGNED to someone who no longer effectively has it.
    if asset.assignment_status == AssetAssignmentStatus.ASSIGNED:
        open_assignment = db.scalar(
            select(FixedAssetAssignment).where(
                FixedAssetAssignment.fixed_asset_id == asset.id,
                FixedAssetAssignment.returned_date.is_(None),
            )
        )
        if open_assignment is not None:
            open_assignment.returned_date = asset.disposed_at.date()
            db.add(open_assignment)
    if asset.assignment_status is not None:
        asset.assignment_status = None
    asset.assigned_employee_id = None

    db.add(asset)
    db.flush()
    return asset


def transfer_fixed_asset(
    db: Session,
    asset: FixedAsset,
    *,
    to_department_id: uuid.UUID | None,
    transfer_date: date,
    note: str | None = None,
) -> FixedAsset:
    if to_department_id == asset.department_id:
        raise ValueError("asset is already assigned to that department")

    db.add(
        FixedAssetTransfer(
            org_id=asset.org_id,
            fixed_asset_id=asset.id,
            from_department_id=asset.department_id,
            to_department_id=to_department_id,
            transfer_date=transfer_date,
            note=note,
        )
    )
    asset.department_id = to_department_id
    db.add(asset)
    db.flush()
    return asset


def revalue_fixed_asset(
    db: Session,
    asset: FixedAsset,
    *,
    new_value_minor: int,
    revaluation_date: date,
    reason: str,
) -> FixedAsset:
    """Resets the asset's book value to new_value_minor: cost_minor becomes
    the new value, accumulated_depreciation_minor resets to zero, and
    useful_life_months (unchanged) now describes the asset's remaining
    life from this point — a common simplified revaluation treatment. The
    difference from the old book value posts as a surplus (credit,
    revaluation_surplus) if the asset is worth more, or a loss (debit,
    revaluation_loss) if it's worth less; new_value_minor equal to the old
    book value is a no-op posting-wise and rejected as pointless.
    """
    if asset.status != FixedAssetStatus.ACTIVE:
        raise ValueError("only an active asset can be revalued")
    if new_value_minor <= 0:
        raise ValueError("new_value_minor must be positive")

    old_book_value = asset.book_value_minor
    difference = new_value_minor - old_book_value
    if difference == 0:
        raise ValueError("new_value_minor must differ from the asset's current book value")

    if difference > 0:
        lines = [
            JournalEntryLineCreate(account_code="fixed_assets", debit_minor=difference),
            JournalEntryLineCreate(account_code="revaluation_surplus", credit_minor=difference),
        ]
    else:
        lines = [
            JournalEntryLineCreate(account_code="revaluation_loss", debit_minor=-difference),
            JournalEntryLineCreate(account_code="fixed_assets", credit_minor=-difference),
        ]
    post_manual_journal_entry(
        db,
        org_id=asset.org_id,
        description=f"Revaluation of fixed asset {asset.asset_tag}",
        lines=lines,
    )

    db.add(
        FixedAssetRevaluation(
            org_id=asset.org_id,
            fixed_asset_id=asset.id,
            revaluation_date=revaluation_date,
            old_book_value_minor=old_book_value,
            new_book_value_minor=new_value_minor,
            reason=reason,
        )
    )
    asset.cost_minor = new_value_minor
    asset.accumulated_depreciation_minor = 0
    db.add(asset)
    db.flush()
    return asset


def run_batch_depreciation(db: Session, org_id: uuid.UUID) -> list[FixedAsset]:
    """Depreciates every active fixed asset in the org by one period,
    skipping (not failing the batch for) any asset that's already fully
    depreciated — record_depreciation itself decides how much a single
    asset should move; this just runs it across all of them and returns
    the ones that actually changed."""
    assets = db.scalars(
        select(FixedAsset).where(
            FixedAsset.org_id == org_id, FixedAsset.status == FixedAssetStatus.ACTIVE
        )
    )
    depreciated = []
    for asset in assets:
        try:
            record_depreciation(db, asset)
        except ValueError:
            continue
        depreciated.append(asset)
    return depreciated
