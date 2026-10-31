import io
import uuid
import zipfile
from datetime import date

import pytest

from app.compliance.multicountry import TaxStatus
from app.schemas.analytics import CompareMode, Unit
from app.services.analytics.common import average, change, percent, row, top_rows
from app.services.analytics.exports import format_value
from app.services.analytics.filters import (
    FilterError,
    add_months,
    comparison_window,
    month_buckets,
    month_keys,
    months_spanned,
    parse_filters,
)
from app.services.analytics.workforce import turnover_rate
from app.services.report_export import ReportTable, to_xlsx
from tests.unit.tax_engine_fixtures import mark_country

TODAY = date(2026, 10, 24)


def _parse(**overrides: object) -> object:
    values: dict[str, object] = {
        "today": TODAY,
        "date_from": None,
        "date_to": None,
        "compare": None,
        "department_ids": [],
        "location_ids": [],
        "employment_types": [],
        "statuses": [],
        "payroll_status": None,
        "country": None,
    }
    values.update(overrides)
    return parse_filters(**values)  # type: ignore[arg-type]


# --- comparisons and ratios -------------------------------------------------


def test_change_reports_absolute_and_percentage() -> None:
    assert change(120, 100) == (20.0, 20.0)
    assert change(80, 100) == (-20.0, -20.0)
    assert change(5, -10) == (15.0, 150.0)  # against the size of a negative base


def test_change_has_no_percentage_from_zero_or_missing() -> None:
    assert change(5, 0) == (5.0, None)
    assert change(0, 0) == (0.0, None)
    assert change(None, 10) == (None, None)
    assert change(10, None) == (None, None)


def test_ratios_are_none_for_a_zero_denominator() -> None:
    assert percent(1, 3) == 33.33
    assert percent(0, 0) is None
    assert average(10, 4) == 2.5
    assert average(10, 0) is None


def test_turnover_uses_average_headcount() -> None:
    assert turnover_rate(1, 4, 4) == 25.0
    assert turnover_rate(2, 10, 30) == 10.0
    assert turnover_rate(0, 0, 0) is None  # nobody to turn over
    assert turnover_rate(1, 0, 0) is None


# --- periods ----------------------------------------------------------------


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)


def test_whole_months_compare_with_the_same_number_of_months() -> None:
    # Q2 against Q1, not against the 91 days before it.
    assert comparison_window(date(2026, 4, 1), date(2026, 6, 30), CompareMode.PREVIOUS_PERIOD) == (
        date(2026, 1, 1),
        date(2026, 3, 31),
    )
    # A month against the one before, across a year end and into February.
    assert comparison_window(date(2026, 1, 1), date(2026, 1, 31), CompareMode.PREVIOUS_PERIOD) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )
    assert comparison_window(date(2026, 3, 1), date(2026, 3, 31), CompareMode.PREVIOUS_PERIOD) == (
        date(2026, 2, 1),
        date(2026, 2, 28),
    )


def test_other_ranges_compare_with_the_same_number_of_days() -> None:
    assert comparison_window(date(2026, 3, 10), date(2026, 3, 19), CompareMode.PREVIOUS_PERIOD) == (
        date(2026, 2, 28),
        date(2026, 3, 9),
    )


def test_previous_year_handles_a_leap_day() -> None:
    assert comparison_window(date(2024, 2, 29), date(2024, 3, 31), CompareMode.PREVIOUS_YEAR) == (
        date(2023, 2, 28),
        date(2023, 3, 31),
    )
    assert comparison_window(date(2026, 1, 1), date(2026, 1, 31), CompareMode.NONE) is None


def test_month_buckets_are_clipped_to_the_range() -> None:
    assert month_buckets(date(2026, 1, 15), date(2026, 3, 10)) == [
        ("2026-01", date(2026, 1, 15), date(2026, 1, 31)),
        ("2026-02", date(2026, 2, 1), date(2026, 2, 28)),
        ("2026-03", date(2026, 3, 1), date(2026, 3, 10)),
    ]
    assert month_keys(date(2025, 12, 31), date(2026, 1, 1)) == ["2025-12", "2026-01"]
    assert months_spanned(date(2025, 12, 31), date(2026, 1, 1)) == 2


# --- filter validation ------------------------------------------------------


def test_default_range_is_the_last_twelve_months() -> None:
    filters = _parse()
    assert filters.date_from == date(2025, 11, 1)  # type: ignore[attr-defined]
    assert filters.date_to == TODAY  # type: ignore[attr-defined]
    assert filters.compare == CompareMode.PREVIOUS_PERIOD  # type: ignore[attr-defined]
    assert filters.currency == "NGN"  # type: ignore[attr-defined]


def test_one_sided_ranges_are_completed() -> None:
    only_end = _parse(date_to=date(2026, 6, 30))
    assert only_end.date_from == date(2025, 7, 1)  # type: ignore[attr-defined]
    only_start = _parse(date_from=date(2026, 3, 1))
    assert only_start.date_to == TODAY  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"date_from": date(2026, 2, 1), "date_to": date(2026, 1, 1)}, "after"),
        ({"date_from": date(2023, 1, 1), "date_to": date(2026, 1, 31)}, "36 months"),
        ({"date_from": date(1999, 1, 1), "date_to": date(1999, 12, 31)}, "before"),
        ({"date_to": date(2028, 1, 1)}, "within a year"),
        ({"compare": "decade"}, "compare"),
        ({"employment_types": ["astronaut"]}, "employment type"),
        ({"statuses": ["retired"]}, "employment status"),
        ({"payroll_status": "draft"}, "payroll_status"),
        ({"country": "XX"}, "unknown country"),
        ({"department_ids": [uuid.uuid4() for _ in range(51)]}, "at most 50"),
    ],
)
def test_invalid_filters_raise(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(FilterError, match=message):
        _parse(**overrides)


def test_a_country_without_approved_rules_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    mark_country(monkeypatch, "KE", TaxStatus.DRAFT)
    with pytest.raises(FilterError, match="not production-enabled"):
        _parse(country="KE")


def test_a_thirty_six_month_range_is_allowed() -> None:
    filters = _parse(date_from=date(2023, 11, 1), date_to=date(2026, 10, 31))
    assert filters.date_from == date(2023, 11, 1)  # type: ignore[attr-defined]


def test_duplicate_filter_values_collapse() -> None:
    department = uuid.uuid4()
    filters = _parse(department_ids=[department, department], employment_types=["intern", "intern"])
    assert filters.department_ids == (department,)  # type: ignore[attr-defined]
    assert len(filters.employment_types) == 1  # type: ignore[attr-defined]


# --- small groups and folding ----------------------------------------------


@pytest.mark.parametrize(("count", "hidden"), [(0, False), (1, True), (2, True), (3, False)])
def test_small_groups_lose_their_value(count: int, hidden: bool) -> None:
    result = row("d", "Dept", 1000, count=count, protect=True)
    assert result.suppressed is hidden
    assert (result.value is None) is hidden
    assert result.count == count


def test_unprotected_rows_keep_their_value() -> None:
    assert row("d", "Dept", 1000, count=1).value == 1000


def test_top_rows_fold_the_tail_into_other() -> None:
    rows = [row(str(i), f"T{i}", value, count=1) for i, value in enumerate([5, 9, 1, 7, 3])]
    folded = top_rows(rows, 3)
    assert [r.label for r in folded] == ["T1", "T3", "Other"]
    assert folded[-1].value == 9 and folded[-1].count == 3
    assert top_rows(rows, 5) == sorted(rows, key=lambda r: -(r.value or 0))


# --- formatting and export --------------------------------------------------


def test_values_are_formatted_by_unit() -> None:
    assert format_value(123456, Unit.MONEY, "NGN") == "1,234.56"
    assert format_value(-500, Unit.MONEY, "NGN") == "-5.00"
    assert format_value(33.333, Unit.PERCENT, None) == "33.33"
    assert format_value(1500, Unit.COUNT, None) == "1,500"
    assert format_value(8.5, Unit.HOURS, None) == "8.5"
    assert format_value(None, Unit.COUNT, None) == ""


def test_xlsx_is_a_valid_workbook_with_numbers_and_safe_text() -> None:
    table = ReportTable(
        title="Report: test",
        filename="test",
        headers=["Item", "Value"],
        rows=[['=HYPERLINK("x")', "1,234.56"], ["Plain & <text>", "-3"]],
        subtitle=["Period: 2026"],
        numeric={1},
    )
    content = to_xlsx(table)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert set(archive.namelist()) >= {
            "[Content_Types].xml",
            "xl/workbook.xml",
            "xl/worksheets/sheet1.xml",
        }
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
        workbook = archive.read("xl/workbook.xml").decode()
    assert "<v>1234.56</v>" in sheet and "<v>-3</v>" in sheet
    # A would-be formula stays an inline string, never an <f> element.
    assert "<f>" not in sheet and 't="inlineStr"' in sheet
    assert "Plain &amp; &lt;text&gt;" in sheet
    assert 'name="Report  test"' in workbook  # ':' is not allowed in a sheet name
