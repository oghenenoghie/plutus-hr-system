"""Pure stock-control rules: stocktake variances and approval (D6, D8) and
the report export formatting (app/domain/inventory/stocktakes.py,
app/services/inventory_report_export.py)."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.inventory.costing import EMPTY_POOL, CostPool
from app.domain.inventory.stocktakes import gain_value_minor, needs_approval, variance
from app.services.inventory_report_export import ReportTable, _csv_safe, naira, qty, to_csv

quantities = st.decimals(min_value=0, max_value=10**6, places=4, allow_nan=False)


@given(expected=quantities, counted=quantities)
def test_variance_reconstructs_the_count(expected: Decimal, counted: Decimal) -> None:
    # Posting the variance on top of the snapshot gives exactly what was counted.
    assert expected + variance(expected, counted) == counted


def test_gain_value_prefers_the_average_then_the_default_cost() -> None:
    pool = CostPool(quantity=Decimal(4), value_minor=1_000)  # N2.50 each
    assert gain_value_minor(Decimal(2), pool, default_cost_minor=999) == 500
    assert gain_value_minor(Decimal(3), EMPTY_POOL, default_cost_minor=450) == 1_350
    assert gain_value_minor(Decimal(3), EMPTY_POOL, default_cost_minor=None) is None
    with pytest.raises(ValueError):
        gain_value_minor(Decimal(0), pool, default_cost_minor=None)


@given(
    value=st.integers(min_value=1, max_value=10**12),
    quantity=st.decimals(min_value=Decimal("0.0001"), max_value=10**6, places=4),
    found=st.decimals(min_value=Decimal("0.0001"), max_value=10**6, places=4),
)
def test_gain_value_is_the_average_rounded_once(
    value: int, quantity: Decimal, found: Decimal
) -> None:
    pool = CostPool(quantity=quantity, value_minor=value)
    exact = Decimal(value) * found / quantity
    assert abs(gain_value_minor(found, pool, None) - exact) <= Decimal("0.5")  # type: ignore[operator]


def test_any_missing_stock_needs_approval() -> None:
    assert needs_approval([(Decimal("-0.0001"), -1)], gain_limit_minor=None)
    assert needs_approval([(Decimal(5), 10), (Decimal(-1), -1)], gain_limit_minor=10**9)


def test_found_stock_needs_approval_from_the_limit() -> None:
    found = [(Decimal(1), 600), (Decimal(2), 400), (Decimal(0), 0)]
    assert not needs_approval(found, gain_limit_minor=None)
    assert needs_approval(found, gain_limit_minor=1_000)
    assert not needs_approval(found, gain_limit_minor=1_001)
    # A count that matched the books needs no approval, even at a zero limit.
    assert not needs_approval([(Decimal(0), 0)], gain_limit_minor=0)
    assert needs_approval([(Decimal(1), 0)], gain_limit_minor=0) is False  # found, valued at 0
    assert needs_approval([(Decimal(1), 1)], gain_limit_minor=0)


def test_naira_and_quantities_format_for_people() -> None:
    assert naira(3_703_701) == "37,037.01"
    assert naira(-5) == "-0.05"
    assert naira(0) == "0.00"
    assert naira(None) == ""
    assert qty(Decimal("12.5000")) == "12.5"
    assert qty(Decimal("100.0000")) == "100"
    assert qty(Decimal("-0.0000")) == "0"


@pytest.mark.parametrize(
    ("cell", "written"),
    [
        ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
        ("+1+1", "'+1+1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("-1,234.50", "-1,234.50"),  # a negative amount is still a number
        ("-3", "-3"),
        ("Paper - A4", "Paper - A4"),
        ("", ""),
    ],
)
def test_csv_cells_that_look_like_formulas_are_neutralised(cell: str, written: str) -> None:
    assert _csv_safe(cell) == written


def test_csv_has_a_bom_title_headings_rows_and_totals() -> None:
    table = ReportTable(
        title="Stock valuation",
        filename="x",
        headers=["SKU", "Value"],
        rows=[["=EVIL()", "1.00"]],
        subtitle=["As at today"],
        totals=[["Total", "1.00"]],
    )
    text = to_csv(table).decode("utf-8")
    assert text.startswith("﻿Stock valuation\r\nAs at today\r\n\r\nSKU,Value\r\n")
    assert "'=EVIL(),1.00\r\nTotal,1.00\r\n" in text
