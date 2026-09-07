import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.company_asset import CompanyAssetCategory, CompanyAssetStatus


class CompanyAssetCreate(BaseModel):
    name: str
    asset_tag: str
    category: CompanyAssetCategory
    purchase_date: date | None = None
    purchase_value_minor: int | None = None


class CompanyAssetUpdate(BaseModel):
    name: str | None = None
    category: CompanyAssetCategory | None = None
    status: CompanyAssetStatus | None = None
    purchase_date: date | None = None
    purchase_value_minor: int | None = None


class CompanyAssetOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    asset_tag: str
    category: CompanyAssetCategory
    status: CompanyAssetStatus
    purchase_date: date | None
    purchase_value_minor: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
