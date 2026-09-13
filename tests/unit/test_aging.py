from datetime import date

from app.domain.aging import AgingBucket, bucket_for


def test_due_today_is_not_yet_due() -> None:
    assert bucket_for(date(2026, 3, 1), as_of=date(2026, 3, 1)) == AgingBucket.NOT_YET_DUE


def test_due_in_the_future_is_not_yet_due() -> None:
    assert bucket_for(date(2026, 3, 10), as_of=date(2026, 3, 1)) == AgingBucket.NOT_YET_DUE


def test_bucket_boundaries() -> None:
    as_of = date(2026, 6, 1)
    assert bucket_for(date(2026, 5, 2), as_of=as_of) == AgingBucket.DAYS_1_30  # 30 days overdue
    assert bucket_for(date(2026, 5, 1), as_of=as_of) == AgingBucket.DAYS_31_60  # 31 days overdue
    assert bucket_for(date(2026, 4, 2), as_of=as_of) == AgingBucket.DAYS_31_60  # 60 days overdue
    assert bucket_for(date(2026, 4, 1), as_of=as_of) == AgingBucket.DAYS_61_90  # 61 days overdue
    assert bucket_for(date(2026, 3, 3), as_of=as_of) == AgingBucket.DAYS_61_90  # 90 days overdue
    assert bucket_for(date(2026, 3, 2), as_of=as_of) == AgingBucket.DAYS_90_PLUS  # 91 days overdue
