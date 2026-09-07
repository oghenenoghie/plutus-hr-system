import uuid
from datetime import time

from sqlalchemy.orm import Session

from app.models.shift import Shift


def register_shift(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    start_time: time,
    end_time: time,
) -> Shift:
    shift = Shift(org_id=org_id, name=name, start_time=start_time, end_time=end_time)
    db.add(shift)
    db.flush()
    return shift
