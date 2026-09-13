from datetime import date

from app.domain.employee_lifecycle import LifecycleStage, LifecycleState, derive_lifecycle_stage


def test_recent_hire_is_onboarding() -> None:
    stage = derive_lifecycle_stage(LifecycleState.ACTIVE, date(2026, 1, 1), as_of=date(2026, 2, 1))
    assert stage == LifecycleStage.ONBOARDING


def test_hire_past_the_onboarding_window_is_active() -> None:
    stage = derive_lifecycle_stage(LifecycleState.ACTIVE, date(2026, 1, 1), as_of=date(2026, 6, 1))
    assert stage == LifecycleStage.ACTIVE


def test_suspended_state_wins_over_tenure() -> None:
    stage = derive_lifecycle_stage(
        LifecycleState.SUSPENDED, date(2020, 1, 1), as_of=date(2026, 1, 1)
    )
    assert stage == LifecycleStage.SUSPENDED


def test_terminated_state_wins_over_everything() -> None:
    stage = derive_lifecycle_stage(
        LifecycleState.TERMINATED, date(2026, 1, 1), as_of=date(2026, 1, 2)
    )
    assert stage == LifecycleStage.TERMINATED
