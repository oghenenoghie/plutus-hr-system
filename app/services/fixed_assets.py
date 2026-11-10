import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.accounting.depreciation import (
    DepreciationMethod,
    check_method,
    months_held,
    period_charge,
)
from app.domain.accounting.posting_rules import PostingLine
from app.models.asset_category import AssetCategory
from app.models.fixed_asset import (
    AssetAssignmentStatus,
    FixedAsset,
    FixedAssetCategory,
    FixedAssetStatus,
)
from app.models.fixed_asset_assignment import FixedAssetAssignment
from app.models.fixed_asset_revaluation import FixedAssetRevaluation
from app.models.fixed_asset_transfer import FixedAssetTransfer
from app.models.journal_entry import JournalEntry, JournalSourceType
from app.models.ledger import LedgerEntry
from app.schemas.fixed_assets import FixedAssetDepreciationEvent, FixedAssetDepreciationHistory
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.chart_accounts import (
    OPENING_BALANCE_EQUITY_ACCOUNT,
    seed_lease_accounts,
    seed_opening_balance_equity_account,
)
from app.services.general_ledger import post_manual_journal_entry
from app.services.posting import lagos_date, post_journal, today_lagos

# Depreciation journals are linked to their asset (source FIXED_ASSET), one
# event per period: asset.depreciated:1, :2, ... The opening balance of an
# asset already owned is an OPENING_BALANCE journal with this event.
_DEPRECIATED_EVENT = "asset.depreciated"
_OPENING_EVENT = "fixed_asset.opening_balance"
_LEASE_PAYMENT_EVENT = "lease.payment"

ACQUIRED = "acquired"
LEASED = "leased"


def ledger_accounts(asset: FixedAsset) -> tuple[str, str, str]:
    """(cost, accumulated, expense) accounts: an owned asset's fixed assets,
    accumulated depreciation and depreciation expense, or a leased asset's
    right-of-use asset, accumulated amortisation and amortisation expense."""
    if asset.is_leased:
        return "right_of_use_assets", "accumulated_amortisation", "amortisation_expense"
    return "fixed_assets", "accumulated_depreciation", "depreciation_expense"


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
    opening_balance: bool = False,
    opening_accumulated_depreciation_minor: int = 0,
    cash_account_code: str = "cash",
    acquisition_type: str = ACQUIRED,
    depreciation_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE,
    depreciation_rate_ppm: int | None = None,
    lease_term_months: int | None = None,
    asset_category_id: uuid.UUID | None = None,
) -> FixedAsset:
    """Registers an asset and puts it on the books.

    A purchase (the default) is paid from cash: Dr fixed_assets / Cr cash.

    An asset the organisation already owned when it started using Plutus
    (opening_balance) was paid for long ago, so no cash moves. It comes on
    as an opening balance at its original cost, with the depreciation it
    had already built up, the rest against Opening Balance Equity:
    Dr fixed_assets (cost) / Cr accumulated_depreciation (built up) /
    Cr opening_balance_equity (book value). Depreciation then carries on
    from there at the same monthly rate until it reaches cost less
    salvage value.

    A leased asset (acquisition_type "leased") is the right to use it for
    the lease term: Dr right_of_use_assets / Cr lease_liability at its
    cost, amortised over the lease; payments reduce the liability
    (record_lease_payment).
    """
    if acquisition_type not in (ACQUIRED, LEASED):
        raise ValueError("acquisition_type is acquired or leased")
    check_method(depreciation_method, rate_ppm=depreciation_rate_ppm)
    if acquisition_type == LEASED:
        if lease_term_months is None or lease_term_months <= 0:
            raise ValueError("a leased asset needs its lease term (payment period) in months")
        if opening_balance:
            raise ValueError(
                "a lease already running when you started on Plutus goes on with a manual "
                "journal; record new leases here"
            )
    elif lease_term_months is not None:
        raise ValueError("only a leased asset has a lease term")
    if asset_category_id is not None and db.get(AssetCategory, asset_category_id) is None:
        raise ValueError("asset category not found")
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
    if opening_accumulated_depreciation_minor < 0:
        raise ValueError("opening_accumulated_depreciation_minor cannot be negative")
    if opening_accumulated_depreciation_minor > 0 and not opening_balance:
        raise ValueError(
            "only an asset already owned (opening_balance) can have depreciation built up"
        )
    if opening_accumulated_depreciation_minor > cost_minor - salvage_value_minor:
        raise ValueError(
            "opening_accumulated_depreciation_minor cannot exceed cost less salvage value"
        )

    if acquisition_type == LEASED:
        seed_lease_accounts(db, org_id=org_id)
        post_manual_journal_entry(
            db,
            org_id=org_id,
            description=f"Leased asset {asset_tag}: right of use and lease liability",
            lines=[
                JournalEntryLineCreate(account_code="right_of_use_assets", debit_minor=cost_minor),
                JournalEntryLineCreate(account_code="lease_liability", credit_minor=cost_minor),
            ],
        )
    elif not opening_balance:
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
        accumulated_depreciation_minor=opening_accumulated_depreciation_minor,
        category=category,
        assignment_status=AssetAssignmentStatus.AVAILABLE if category is not None else None,
        acquisition_type=acquisition_type,
        depreciation_method=DepreciationMethod(depreciation_method).value,
        depreciation_rate_ppm=depreciation_rate_ppm,
        lease_term_months=lease_term_months,
        asset_category_id=asset_category_id,
    )
    db.add(asset)
    db.flush()

    if opening_balance:
        seed_opening_balance_equity_account(db, org_id=org_id)
        lines = [PostingLine(account="fixed_assets", debit_minor=cost_minor)]
        if opening_accumulated_depreciation_minor > 0:
            lines.append(
                PostingLine(
                    account="accumulated_depreciation",
                    credit_minor=opening_accumulated_depreciation_minor,
                )
            )
        book_value_minor = cost_minor - opening_accumulated_depreciation_minor
        # Zero for an asset fully depreciated before Plutus with no salvage
        # value; a posting line can't carry nothing.
        if book_value_minor > 0:
            lines.append(
                PostingLine(account=OPENING_BALANCE_EQUITY_ACCOUNT, credit_minor=book_value_minor)
            )
        post_journal(
            db,
            org_id=org_id,
            entry_date=today_lagos(),
            source_type=JournalSourceType.OPENING_BALANCE,
            source_id=asset.id,
            source_event=_OPENING_EVENT,
            description=f"Opening balance of fixed asset {asset_tag}",
            lines=lines,
        )

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


def _charge(asset: FixedAsset, months: int) -> int:
    return period_charge(
        method=DepreciationMethod(asset.depreciation_method),
        cost_minor=asset.cost_minor,
        salvage_value_minor=asset.salvage_value_minor,
        accumulated_minor=asset.accumulated_depreciation_minor,
        useful_life_months=asset.useful_life_months,
        rate_ppm=asset.depreciation_rate_ppm,
        months=months,
    )


def _post_charge(
    db: Session, asset: FixedAsset, *, amount: int, entry_date: date, event: str, description: str
) -> None:
    _cost, accumulated, expense = ledger_accounts(asset)
    post_journal(
        db,
        org_id=asset.org_id,
        entry_date=entry_date,
        source_type=JournalSourceType.FIXED_ASSET,
        source_id=asset.id,
        source_event=event,
        description=description,
        lines=[
            PostingLine(account=expense, debit_minor=amount),
            PostingLine(account=accumulated, credit_minor=amount),
        ],
    )
    asset.accumulated_depreciation_minor += amount
    db.add(asset)
    db.flush()


def record_depreciation(db: Session, asset: FixedAsset) -> FixedAsset:
    """One month's depreciation (amortisation, for a leased asset) by the
    asset's method."""
    if asset.status != FixedAssetStatus.ACTIVE:
        raise ValueError("only an active asset can be depreciated")
    if asset.cost_minor - asset.salvage_value_minor - asset.accumulated_depreciation_minor <= 0:
        raise ValueError("this asset is already fully depreciated")
    amount = _charge(asset, 1)
    if amount <= 0:
        raise ValueError("this month's depreciation rounds to nothing")

    # Linked to the asset so its depreciation history can be listed
    # (depreciation_history); the description stays what it always was.
    periods_posted = db.scalar(
        select(func.count())
        .select_from(JournalEntry)
        .where(
            JournalEntry.org_id == asset.org_id,
            JournalEntry.source_type == JournalSourceType.FIXED_ASSET,
            JournalEntry.source_id == asset.id,
            JournalEntry.source_event.like(f"{_DEPRECIATED_EVENT}:%"),
        )
    )
    _post_charge(
        db,
        asset,
        amount=amount,
        entry_date=today_lagos(),
        event=f"{_DEPRECIATED_EVENT}:{(periods_posted or 0) + 1}",
        description=f"Depreciation for {asset.asset_tag}",
    )
    return asset


def year_end_event(year: int) -> str:
    return f"{_DEPRECIATED_EVENT}:FY{year}"


def run_year_end_depreciation(
    db: Session, org_id: uuid.UUID, *, year: int
) -> tuple[list[tuple[FixedAsset, int]], list[FixedAsset]]:
    """The year's depreciation for every active asset, by each one's method
    and rate (reducing balance on the net book value at the start of the
    year), for the months of the year it was held. Dated 31 December and
    posted to depreciation (or amortisation) expense in the profit and loss
    account and accumulated depreciation on the balance sheet.

    Once per asset per year: an asset whose year has been run already is
    returned in the second list and not charged again, so the run can be
    repeated for assets added later. An asset with nothing left to
    depreciate is left out of both lists."""
    year_end = date(year, 12, 31)
    charged: list[tuple[FixedAsset, int]] = []
    already: list[FixedAsset] = []
    assets = db.scalars(
        select(FixedAsset)
        .where(
            FixedAsset.org_id == org_id,
            FixedAsset.status == FixedAssetStatus.ACTIVE,
            FixedAsset.acquisition_date <= year_end,
        )
        .order_by(FixedAsset.asset_tag)
    ).all()
    done = set(
        db.scalars(
            select(JournalEntry.source_id).where(
                JournalEntry.org_id == org_id,
                JournalEntry.source_type == JournalSourceType.FIXED_ASSET,
                JournalEntry.source_event == year_end_event(year),
            )
        )
    )
    for asset in assets:
        if asset.id in done:
            already.append(asset)
            continue
        months = months_held(asset.acquisition_date, year)
        if months == 0:
            continue
        amount = _charge(asset, months)
        if amount <= 0:
            continue
        _post_charge(
            db,
            asset,
            amount=amount,
            entry_date=year_end,
            event=year_end_event(year),
            description=(
                f"{'Amortisation' if asset.is_leased else 'Depreciation'} for {asset.asset_tag}, "
                f"year ended {year_end.isoformat()}"
            ),
        )
        charged.append((asset, amount))
    return charged, already


def record_lease_payment(
    db: Session,
    asset: FixedAsset,
    *,
    amount_minor: int,
    payment_date: date,
    cash_account_code: str = "cash",
) -> JournalEntry:
    """A lease payment: Dr lease_liability / Cr Cash and Bank."""
    if not asset.is_leased:
        raise ValueError("only a leased asset has lease payments")
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    count = db.scalar(
        select(func.count())
        .select_from(JournalEntry)
        .where(
            JournalEntry.org_id == asset.org_id,
            JournalEntry.source_type == JournalSourceType.FIXED_ASSET,
            JournalEntry.source_id == asset.id,
            JournalEntry.source_event.like(f"{_LEASE_PAYMENT_EVENT}:%"),
        )
    )
    return post_journal(
        db,
        org_id=asset.org_id,
        entry_date=payment_date,
        source_type=JournalSourceType.FIXED_ASSET,
        source_id=asset.id,
        source_event=f"{_LEASE_PAYMENT_EVENT}:{(count or 0) + 1}",
        description=f"Lease payment for {asset.asset_tag}",
        lines=[
            PostingLine(account="lease_liability", debit_minor=amount_minor),
            PostingLine(account=cash_account_code, credit_minor=amount_minor),
        ],
    )


def register_asset_category(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    depreciation_method: DepreciationMethod,
    depreciation_rate_ppm: int | None = None,
    useful_life_months: int | None = None,
) -> AssetCategory:
    check_method(depreciation_method, rate_ppm=depreciation_rate_ppm)
    if useful_life_months is not None and useful_life_months <= 0:
        raise ValueError("useful_life_months must be positive")
    name = name.strip()
    if not name:
        raise ValueError("a category needs a name")
    if db.scalar(
        select(AssetCategory.id).where(AssetCategory.org_id == org_id, AssetCategory.name == name)
    ):
        raise ValueError(f"there's already a category called {name!r}")
    category = AssetCategory(
        org_id=org_id,
        name=name,
        depreciation_method=DepreciationMethod(depreciation_method).value,
        depreciation_rate_ppm=depreciation_rate_ppm,
        useful_life_months=useful_life_months,
    )
    db.add(category)
    db.flush()
    return category


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

    cost_account, accumulated_account, _expense = ledger_accounts(asset)
    lines = [JournalEntryLineCreate(account_code=cost_account, credit_minor=asset.cost_minor)]
    if asset.accumulated_depreciation_minor > 0:
        lines.append(
            JournalEntryLineCreate(
                account_code=accumulated_account,
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
    if asset.is_leased:
        raise ValueError("a leased asset (a right of use) isn't revalued")
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


def depreciation_history(db: Session, asset: FixedAsset) -> FixedAssetDepreciationHistory:
    """Every change to the asset's accumulated depreciation, oldest first,
    with the running total after each.

    Depreciation posted since journals were linked to their asset comes
    from those journals (and the opening balance of an asset already
    owned from its OPENING_BALANCE journal). Depreciation posted before
    then has no link, only its description, "Depreciation for <tag>",
    which identifies the asset because a tag is unique within an
    organisation. A revaluation resets the total to zero. Whatever the
    asset carries that none of these explain (unexplained_minor) is
    reported rather than guessed at.
    """
    timed: list[tuple[datetime, int, FixedAssetDepreciationEvent]] = []

    linked = db.scalars(
        select(JournalEntry).where(
            JournalEntry.org_id == asset.org_id,
            JournalEntry.source_id == asset.id,
            JournalEntry.source_type.in_(
                (JournalSourceType.FIXED_ASSET, JournalSourceType.OPENING_BALANCE)
            ),
        )
    ).all()
    linked_ids = {journal.id for journal in linked}
    movement: dict[uuid.UUID, int] = {}
    if linked_ids:
        for line in db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.journal_entry_id.in_(linked_ids),
                LedgerEntry.account == ledger_accounts(asset)[1],
            )
        ):
            movement[line.journal_entry_id] = (
                movement.get(line.journal_entry_id, 0) + line.credit_minor - line.debit_minor
            )
    for journal in linked:
        amount = movement.get(journal.id, 0)
        if amount == 0:
            continue
        opening = journal.source_type == JournalSourceType.OPENING_BALANCE
        timed.append(
            (
                journal.created_at,
                0,
                FixedAssetDepreciationEvent(
                    kind="opening" if opening else "depreciation",
                    date=journal.entry_date,
                    amount_minor=amount,
                    accumulated_minor=0,
                    journal_entry_id=journal.id,
                    description=(
                        "Built up before Plutus (opening balance)"
                        if opening
                        else "Depreciation for the period"
                    ),
                ),
            )
        )

    legacy = select(LedgerEntry).where(
        LedgerEntry.org_id == asset.org_id,
        LedgerEntry.account == "accumulated_depreciation",
        LedgerEntry.description == f"Depreciation for {asset.asset_tag}",
    )
    if linked_ids:
        legacy = legacy.where(LedgerEntry.journal_entry_id.not_in(linked_ids))
    for line in db.scalars(legacy):
        amount = line.credit_minor - line.debit_minor
        if amount == 0:
            continue
        timed.append(
            (
                line.created_at,
                0,
                FixedAssetDepreciationEvent(
                    kind="depreciation",
                    date=lagos_date(line.created_at),
                    amount_minor=amount,
                    accumulated_minor=0,
                    journal_entry_id=line.journal_entry_id,
                    description="Depreciation for the period",
                ),
            )
        )

    for revaluation in db.scalars(
        select(FixedAssetRevaluation).where(FixedAssetRevaluation.fixed_asset_id == asset.id)
    ):
        timed.append(
            (
                revaluation.created_at,
                1,
                FixedAssetDepreciationEvent(
                    kind="revaluation",
                    date=revaluation.revaluation_date,
                    amount_minor=0,
                    accumulated_minor=0,
                    journal_entry_id=None,
                    description=f"Revalued: {revaluation.reason}",
                ),
            )
        )

    events = []
    running = 0
    for _moment, _order, event in sorted(timed, key=lambda item: (item[0], item[1])):
        if event.kind == "revaluation":
            event.amount_minor = -running
            running = 0
        else:
            running += event.amount_minor
        event.accumulated_minor = running
        events.append(event)

    return FixedAssetDepreciationHistory(
        fixed_asset_id=asset.id,
        accumulated_depreciation_minor=asset.accumulated_depreciation_minor,
        events=events,
        unexplained_minor=asset.accumulated_depreciation_minor - running,
    )
