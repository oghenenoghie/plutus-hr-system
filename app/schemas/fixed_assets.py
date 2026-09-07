import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.fixed_asset import FixedAssetStatus


class FixedAssetCreate(BaseModel):
    name: str
    asset_tag: str
    acquisition_date: date
    cost_minor: int
    salvage_value_minor: int = 0
    useful_life_months: int


class FixedAssetDispose(BaseModel):
    proceeds_minor: int = 0


class FixedAssetOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
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
    created_at: datetime

    model_config = {"from_attributes": True}
