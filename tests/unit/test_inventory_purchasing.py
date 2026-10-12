from decimal import Decimal

import pytest

from app.domain.inventory.purchasing import (
    line_gross_minor,
    line_net_minor,
    line_total_minor,
    max_receivable_base,
    receipt_progress,
    receipt_value_minor,
)


def test_line_amounts() -> None:
    assert line_gross_minor(Decimal(10), 5_000_00) == 50_000_00
    assert line_net_minor(Decimal(10), 5_000_00, 1_000_00) == 49_000_00
    assert line_total_minor(Decimal(10), 5_000_00, 1_000_00, 3_675_00) == 52_675_00
    # Fractional quantities round once, half to even.
    assert line_gross_minor(Decimal("2.5"), 3) == 8  # 7.5 -> 8
    assert line_gross_minor(Decimal("0.5"), 3) == 2  # 1.5 -> 2


def test_discount_cannot_exceed_the_line() -> None:
    with pytest.raises(ValueError, match="discount"):
        line_net_minor(Decimal(1), 100, 101)
    with pytest.raises(ValueError, match="negative"):
        line_net_minor(Decimal(1), 100, -1)


def test_receipt_value_is_the_share_of_the_net_line() -> None:
    # 10 boxes for N49,000 net: 4 boxes enter stock at N19,600.
    assert receipt_value_minor(Decimal(4), Decimal(10), 5_000_00, 1_000_00) == 19_600_00
    assert receipt_value_minor(Decimal(10), Decimal(10), 5_000_00, 1_000_00) == 49_000_00
    assert receipt_value_minor(Decimal(0), Decimal(10), 5_000_00, 0) == 0
    # Within an over-receipt tolerance, extra goods carry the same unit price.
    assert receipt_value_minor(Decimal(11), Decimal(10), 100, 0) == 1_100


def test_receipt_value_rounds_once() -> None:
    # 3 units at 100 kobo less a 2 kobo discount = 298 net; one unit's share
    # is 99.33 kobo -> 99, and with a 1 kobo discount 99.67 -> 100.
    assert receipt_value_minor(Decimal(1), Decimal(3), 100, 2) == 99
    assert receipt_value_minor(Decimal(1), Decimal(3), 100, 1) == 100


def test_max_receivable_applies_the_tolerance_and_rounds_down() -> None:
    assert max_receivable_base(Decimal(100), 0) == Decimal(100)
    assert max_receivable_base(Decimal(100), 500) == Decimal(105)
    assert max_receivable_base(Decimal("0.0003"), 5000) == Decimal("0.0004")  # 0.00045 -> down
    with pytest.raises(ValueError):
        max_receivable_base(Decimal(1), 10_001)


def test_receipt_progress() -> None:
    assert receipt_progress([]) == "none"
    assert receipt_progress([(Decimal(10), Decimal(0))]) == "none"
    assert receipt_progress([(Decimal(10), Decimal(4)), (Decimal(1), Decimal(1))]) == "partial"
    assert receipt_progress([(Decimal(10), Decimal(10)), (Decimal(1), Decimal(2))]) == "full"
