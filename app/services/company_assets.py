import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.company_asset import CompanyAsset, CompanyAssetCategory


def register_company_asset(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    asset_tag: str,
    category: CompanyAssetCategory,
    purchase_date: date | None = None,
    purchase_value_minor: int | None = None,
) -> CompanyAsset:
    if purchase_value_minor is not None and purchase_value_minor < 0:
        raise ValueError("purchase_value_minor must not be negative")

    asset = CompanyAsset(
        org_id=org_id,
        name=name,
        asset_tag=asset_tag,
        category=category,
        purchase_date=purchase_date,
        purchase_value_minor=purchase_value_minor,
    )
    db.add(asset)
    db.flush()
    return asset
