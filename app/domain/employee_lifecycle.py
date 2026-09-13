import enum
from datetime import date


class LifecycleState(str, enum.Enum):
    """An employee's own record of their standing — set directly (ACTIVE by
    default, TERMINATED only via /final-settlements). LifecycleStage below
    is a read-only view derived from this plus tenure; it never gets
    written back."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class LifecycleStage(str, enum.Enum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


# Nigerian practice commonly runs a 3-month probation before confirmation;
# used here only to flag a still-new hire for visibility. Formal probation
# tracking (a start/end date, a confirmation decision) is a separate,
# not-yet-built concern — this is deliberately just a tenure window, not a
# probation record.
_ONBOARDING_WINDOW_DAYS = 90


def derive_lifecycle_stage(
    lifecycle_state: LifecycleState, date_of_joining: date, as_of: date
) -> LifecycleStage:
    if lifecycle_state == LifecycleState.TERMINATED:
        return LifecycleStage.TERMINATED
    if lifecycle_state == LifecycleState.SUSPENDED:
        return LifecycleStage.SUSPENDED
    if (as_of - date_of_joining).days < _ONBOARDING_WINDOW_DAYS:
        return LifecycleStage.ONBOARDING
    return LifecycleStage.ACTIVE
