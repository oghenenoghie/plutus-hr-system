import pytest

from app.domain.money import Money, apply_rate_ppm


def test_apply_rate_ppm_basic() -> None:
    assert apply_rate_ppm(1_000_000, 150_000) == 150_000  # 15% of 1,000,000


def test_apply_rate_ppm_rounds_half_up() -> None:
    # 100 kobo * 15% = 15 kobo exactly; 3 kobo * 15% = 0.45 -> rounds to 0.
    assert apply_rate_ppm(100, 150_000) == 15
    assert apply_rate_ppm(3, 150_000) == 0
    # 1 * 500_000 (50%) = 0.5 -> rounds up to 1 under round-half-up.
    assert apply_rate_ppm(1, 500_000) == 1


def test_apply_rate_ppm_rejects_negative_amount() -> None:
    with pytest.raises(ValueError):
        apply_rate_ppm(-1, 100_000)


def test_money_rejects_cross_currency_arithmetic() -> None:
    ngn = Money(1_000, "NGN")
    with pytest.raises(ValueError):
        ngn + Money(1_000, "USD")


def test_money_rejects_unknown_currency() -> None:
    with pytest.raises(ValueError):
        Money(1_000, "XYZ")


def test_money_add_and_sub() -> None:
    assert Money(500, "NGN") + Money(250, "NGN") == Money(750, "NGN")
    assert Money(500, "NGN") - Money(250, "NGN") == Money(250, "NGN")


def test_money_display() -> None:
    assert Money(123_456, "NGN").display() == "1234.56 NGN"
