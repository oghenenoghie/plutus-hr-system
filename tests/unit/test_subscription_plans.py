from app.domain.subscription_plans import PlanCode, is_over_employee_limit


def test_under_the_limit_is_not_over() -> None:
    assert is_over_employee_limit(PlanCode.FREE, 5) is False


def test_over_the_limit_is_over() -> None:
    assert is_over_employee_limit(PlanCode.FREE, 6) is True


def test_enterprise_has_no_limit() -> None:
    assert is_over_employee_limit(PlanCode.ENTERPRISE, 100_000) is False
