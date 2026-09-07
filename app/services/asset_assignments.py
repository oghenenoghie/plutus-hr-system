import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.asset_assignment import AssetAssignment
from app.models.company_asset import CompanyAsset, CompanyAssetStatus


def assign_asset(
    db: Session,
    asset: CompanyAsset,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    assigned_date: date,
) -> AssetAssignment:
    if asset.status != CompanyAssetStatus.AVAILABLE:
        raise ValueError(f"asset is {asset.status.value}, not available")

    assignment = AssetAssignment(
        org_id=org_id,
        asset_id=asset.id,
        employee_id=employee_id,
        assigned_date=assigned_date,
    )
    asset.status = CompanyAssetStatus.ASSIGNED
    db.add_all([assignment, asset])
    db.flush()
    return assignment


def return_asset(
    db: Session,
    assignment: AssetAssignment,
    asset: CompanyAsset,
    *,
    returned_date: date,
    condition_notes: str | None = None,
) -> AssetAssignment:
    if assignment.returned_date is not None:
        raise ValueError("this assignment has already been returned")
    if returned_date < assignment.assigned_date:
        raise ValueError("returned_date must not be before assigned_date")

    assignment.returned_date = returned_date
    assignment.condition_notes = condition_notes
    asset.status = CompanyAssetStatus.AVAILABLE
    db.add_all([assignment, asset])
    db.flush()
    return assignment
