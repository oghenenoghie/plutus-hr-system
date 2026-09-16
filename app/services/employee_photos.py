import logging
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.storage import get_object_storage, photo_object_key, photo_thumbnail_key
from app.domain.employee_photo import process_employee_photo
from app.models.employee import Employee
from app.models.final_settlement import FinalSettlement

logger = logging.getLogger(__name__)


class PhotoConsentRequiredError(ValueError):
    pass


def _delete_current_photo_objects(employee: Employee) -> None:
    if employee.photo_version == 0:
        return
    storage = get_object_storage()
    # Best-effort: an already-missing object (e.g. a prior partial
    # failure) must not block clearing the employee's own record.
    for key in (
        photo_object_key(employee.org_id, employee.id, employee.photo_version),
        photo_thumbnail_key(employee.org_id, employee.id, employee.photo_version),
    ):
        try:
            storage.delete_object(key)
        except Exception:
            logger.warning("failed to delete employee photo object %s", key, exc_info=True)


def set_employee_photo(db: Session, employee: Employee, *, raw_bytes: bytes, consent: bool) -> None:
    """Processes, stores, and points employee.photo_version at a new
    photo. consent must be explicit and true — NDPR treats a photo as
    personal data, so there is no default-yes here (see
    python-engineering.md's employee-photos section)."""
    if not consent:
        raise PhotoConsentRequiredError("consent is required to store a photo")

    processed = process_employee_photo(raw_bytes)
    next_version = employee.photo_version + 1

    storage = get_object_storage()
    storage.put_object(
        photo_object_key(employee.org_id, employee.id, next_version),
        processed.full_webp,
        content_type="image/webp",
    )
    storage.put_object(
        photo_thumbnail_key(employee.org_id, employee.id, next_version),
        processed.thumbnail_webp,
        content_type="image/webp",
    )

    _delete_current_photo_objects(employee)
    employee.photo_version = next_version
    employee.photo_consent_at = datetime.now(UTC)
    db.add(employee)


def remove_employee_photo(db: Session, employee: Employee) -> None:
    _delete_current_photo_objects(employee)
    employee.photo_version = 0
    employee.photo_consent_at = None
    db.add(employee)


def employee_photo_urls(
    employee: Employee, *, base_url: str, ttl_seconds: int
) -> tuple[str | None, str | None]:
    if employee.photo_version == 0:
        return None, None
    storage = get_object_storage()
    full_url = storage.presigned_url(
        photo_object_key(employee.org_id, employee.id, employee.photo_version),
        ttl_seconds=ttl_seconds,
        base_url=base_url,
    )
    thumb_url = storage.presigned_url(
        photo_thumbnail_key(employee.org_id, employee.id, employee.photo_version),
        ttl_seconds=ttl_seconds,
        base_url=base_url,
    )
    return full_url, thumb_url


def purge_expired_employee_photos(db: Session, org_id: uuid.UUID, *, as_of: date) -> int:
    """Retention purge for the Final Settlement exit flow — deletes a
    terminated employee's photo once employee_photo_retention_days has
    elapsed since their termination_date, per python-engineering.md's
    NDPR note ("triggers deletion on the retention schedule rather than
    leaving orphans"). Run daily by the scheduler, per org."""
    retention_days = get_settings().employee_photo_retention_days
    cutoff = as_of.toordinal() - retention_days

    candidates = db.execute(
        select(Employee, FinalSettlement.termination_date)
        .join(FinalSettlement, FinalSettlement.employee_id == Employee.id)
        .where(Employee.org_id == org_id, Employee.photo_version > 0)
    ).all()

    purged = 0
    for employee, termination_date in candidates:
        if termination_date.toordinal() <= cutoff:
            remove_employee_photo(db, employee)
            purged += 1
    return purged
