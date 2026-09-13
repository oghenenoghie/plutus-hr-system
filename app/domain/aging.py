import enum
from datetime import date


class AgingBucket(str, enum.Enum):
    NOT_YET_DUE = "not_yet_due"
    DAYS_1_30 = "1_30"
    DAYS_31_60 = "31_60"
    DAYS_61_90 = "61_90"
    DAYS_90_PLUS = "90_plus"


def bucket_for(due_date: date, as_of: date) -> AgingBucket:
    days_overdue = (as_of - due_date).days
    if days_overdue <= 0:
        return AgingBucket.NOT_YET_DUE
    if days_overdue <= 30:
        return AgingBucket.DAYS_1_30
    if days_overdue <= 60:
        return AgingBucket.DAYS_31_60
    if days_overdue <= 90:
        return AgingBucket.DAYS_61_90
    return AgingBucket.DAYS_90_PLUS
