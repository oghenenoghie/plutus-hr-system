import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.fixed_asset import AssetAssignmentStatus, FixedAssetCategory, FixedAssetStatus


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
