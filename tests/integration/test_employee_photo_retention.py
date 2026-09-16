import uuid
from datetime import date, timedelta
from io import BytesIO

from PIL import Image

from app.core.db import tenant_session
from app.core.storage import get_object_storage, photo_object_key
from app.models.employee import Employee
from app.services.employee_photos import purge_expired_employee_photos, set_employee_photo
from app.services.final_settlement import process_final_settlement
from tests.integration.api_helpers import create_employee, create_org


def _fake_photo_bytes() -> bytes:
    image = Image.new("RGB", (200, 200), color=(1, 2, 3))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_purge_deletes_photo_once_retention_window_has_elapsed() -> None:
    org_id = create_org()
    employee_id = create_employee(org_id, employee_number="EMP-RET1")

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        set_employee_photo(db, employee, raw_bytes=_fake_photo_bytes(), consent=True)
        version = employee.photo_version
        process_final_settlement(
            db,
            org_id=org_id,
            employee=employee,
            termination_date=date(2026, 1, 1),
            gratuity_minor=0,
            leave_days_paid_out=0,
            leave_payout_minor=0,
        )

    storage = get_object_storage()
    key = photo_object_key(org_id, employee_id, version)
    assert storage.read(key)  # type: ignore[attr-defined]  # LocalObjectStorage in tests

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        purged = purge_expired_employee_photos(db, org_id, as_of=date(2026, 6, 1))
        assert purged == 1

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.photo_version == 0
        assert employee.photo_consent_at is None


def test_purge_leaves_photo_within_retention_window() -> None:
    org_id = create_org()
    employee_id = create_employee(org_id, employee_number="EMP-RET2")
    termination_date = date(2026, 6, 1)

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        set_employee_photo(db, employee, raw_bytes=_fake_photo_bytes(), consent=True)
        process_final_settlement(
            db,
            org_id=org_id,
            employee=employee,
            termination_date=termination_date,
            gratuity_minor=0,
            leave_days_paid_out=0,
            leave_payout_minor=0,
        )

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        purged = purge_expired_employee_photos(
            db, org_id, as_of=termination_date + timedelta(days=1)
        )
        assert purged == 0

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.photo_version > 0
