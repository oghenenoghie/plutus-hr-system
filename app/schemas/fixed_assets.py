import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.accounting.depreciation import DepreciationMethod
from app.models.fixed_asset import AssetAssignmentStatus, FixedAssetCategory, FixedAssetStatus

AcquisitionType = Literal["acquired", "leased"]


class FixedAssetCreate(BaseModel):
    name: str
    asset_tag: str
    acquisition_date: date
    cost_minor: int
    salvage_value_minor: int = 0
    useful_life_months: int
    # Optional device categorisation, folded in from HR's retired
    # CompanyAsset tracking — see register_fixed_asset for the rule that
    # laptop/phone/vehicle must be issued to someone at creation.
    category: FixedAssetCategory | None = None
    assigned_employee_id: uuid.UUID | None = None
    # An asset the organisation owned before it used Plutus. It's brought
    # onto the books as an opening balance against Opening Balance Equity
    # (no cash moves — it was paid for long ago), carrying the depreciation
    # it had already built up. See register_fixed_asset.
    opening_balance: bool = False
    opening_accumulated_depreciation_minor: int = 0
    # Owned, or leased (a right-of-use asset over lease_term_months, the
    # lease's payment period). How it's written down: straight line (at
    # depreciation_rate_ppm a year, or over the useful life without one),
    # reducing balance (the rate on net book value) or written off at once.
    acquisition_type: AcquisitionType = "acquired"
    depreciation_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    depreciation_rate_ppm: int | None = Field(default=None, gt=0, le=1_000_000)
    lease_term_months: int | None = Field(default=None, gt=0)
    asset_category_id: uuid.UUID | None = None


class AssetCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    depreciation_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    depreciation_rate_ppm: int | None = Field(default=None, gt=0, le=1_000_000)
    useful_life_months: int | None = Field(default=None, gt=0)


class AssetCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    depreciation_method: DepreciationMethod
    depreciation_rate_ppm: int | None
    useful_life_months: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class YearEndDepreciationRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)


class YearEndDepreciationLine(BaseModel):
    fixed_asset_id: uuid.UUID
    asset_tag: str
    name: str
    acquisition_type: AcquisitionType
    depreciation_method: DepreciationMethod
    charge_minor: int
    accumulated_depreciation_minor: int
    book_value_minor: int


class YearEndDepreciationOut(BaseModel):
    year: int
    charged: list[YearEndDepreciationLine]
    total_minor: int
    # Assets whose depreciation for the year had been posted before.
    already_run: list[str]


class LeasePaymentRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    payment_date: date


class FixedAssetDispose(BaseModel):
    proceeds_minor: int = 0


class FixedAssetTransferRequest(BaseModel):
    to_department_id: uuid.UUID | None
    transfer_date: date
    note: str | None = None


class FixedAssetRevalueRequest(BaseModel):
    new_value_minor: int
    revaluation_date: date
    reason: str


class FixedAssetDepreciationEvent(BaseModel):
    """One change to an asset's accumulated depreciation.

    opening: what it had built up before Plutus (an opening-balance asset).
    depreciation: one period posted from Plutus.
    revaluation: a revaluation reset it to zero (revalue_fixed_asset).
    """

    kind: Literal["opening", "depreciation", "revaluation"]
    date: date
    amount_minor: int
    accumulated_minor: int
    journal_entry_id: uuid.UUID | None
    description: str


class FixedAssetDepreciationHistory(BaseModel):
    fixed_asset_id: uuid.UUID
    accumulated_depreciation_minor: int
    events: list[FixedAssetDepreciationEvent]
    # The asset's accumulated depreciation that no event above accounts
    # for — zero unless depreciation reached it outside these postings
    # (e.g. assets migrated in without journals, audit P26).
    unexplained_minor: int


class FixedAssetOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    department_id: uuid.UUID | None
    name: str
    asset_tag: str
    acquisition_date: date
    cost_minor: int
    salvage_value_minor: int
    useful_life_months: int
    accumulated_depreciation_minor: int
    book_value_minor: int
    status: FixedAssetStatus
    disposed_at: datetime | None
    disposal_proceeds_minor: int | None
    category: FixedAssetCategory | None
    assignment_status: AssetAssignmentStatus | None
    assigned_employee_id: uuid.UUID | None
    acquisition_type: AcquisitionType = "acquired"
    depreciation_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    depreciation_rate_ppm: int | None = None
    lease_term_months: int | None = None
    asset_category_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FixedAssetTransferOut(BaseModel):
    id: uuid.UUID
    fixed_asset_id: uuid.UUID
    from_department_id: uuid.UUID | None
    to_department_id: uuid.UUID | None
    transfer_date: date
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FixedAssetRevaluationOut(BaseModel):
    id: uuid.UUID
    fixed_asset_id: uuid.UUID
    revaluation_date: date
    old_book_value_minor: int
    new_book_value_minor: int
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FixedAssetAssignmentCreate(BaseModel):
    employee_id: uuid.UUID
    assigned_date: date


class FixedAssetAssignmentReturn(BaseModel):
    returned_date: date
    condition_notes: str | None = None


class FixedAssetAssignmentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    fixed_asset_id: uuid.UUID
    employee_id: uuid.UUID
    assigned_date: date
    returned_date: date | None
    condition_notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MyFixedAssetOut(BaseModel):
    """What an employee sees of their own currently-held assets — deliberately
    excludes cost/depreciation, which stays finance-only (see
    /fixed-assets/me's docstring)."""

    assignment_id: uuid.UUID
    fixed_asset_id: uuid.UUID
    name: str
    asset_tag: str
    category: FixedAssetCategory | None
    assigned_date: date
