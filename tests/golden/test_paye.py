"""Golden tests for PAYE, locked per
.claude/skills/plutus-payroll-python/references/nigeria-statutory-compliance.md §12.
CI must fail if any of these regress.
"""

import pytest

from app.compliance.versions.ng_2026_1 import NG_2026_1
from app.domain.payroll.paye import (
    compute_chargeable_income,
    compute_incremental_paye,
    compute_paye_annual,
)
from app.domain.payroll.reliefs import compute_rent_relief
from app.domain.payroll.tin import MissingTinError, ensure_tin_present

BANDS = NG_2026_1.paye.bands
PAYE_RULE = NG_2026_1.paye


def kobo(naira: int) -> int:
    return naira * 100


def test_worked_example_from_reference() -> None:
    """chargeable ₦3,162,000 -> ₦0 + ₦330,000 (15%) + ₦29,160 (18%) = ₦359,160."""
    assert compute_paye_annual(kobo(3_162_000), BANDS) == kobo(359_160)


@pytest.mark.parametrize(
    "chargeable_naira, expected_kobo",
    [
        (0, 0),
        (799_999, 0),
        (800_000, 0),  # exactly at the tax-free threshold
        (800_001, 15),  # ₦1 into the 15% band
        (2_999_999, 32_999_985),
        (3_000_000, 33_000_000),  # exactly at the 15%/18% boundary
        (3_000_001, 33_000_018),
        (11_999_999, 194_999_982),
        (12_000_000, 195_000_000),  # exactly at the 18%/21% boundary
        (12_000_001, 195_000_021),
        (24_999_999, 467_999_979),
        (25_000_000, 468_000_000),  # exactly at the 21%/23% boundary
        (25_000_001, 468_000_023),
        (49_999_999, 1_042_999_977),
        (50_000_000, 1_043_000_000),  # exactly at the 23%/25% boundary
        (50_000_001, 1_043_000_025),
    ],
)
def test_band_boundaries(chargeable_naira: int, expected_kobo: int) -> None:
    assert compute_paye_annual(kobo(chargeable_naira), BANDS) == expected_kobo


def test_chargeable_income_never_negative() -> None:
    """Deductions exceeding gross floor at zero, never go negative."""
    result = compute_chargeable_income(
        annual_gross_minor=kobo(500_000),
        pension_employee_minor=kobo(200_000),
        nhf_minor=kobo(100_000),
        rent_relief_minor=kobo(500_000),
    )
    assert result == 0
    assert compute_paye_annual(result, BANDS) == 0


def test_rent_relief_capped_at_500k() -> None:
    # 20% of ₦4,000,000 = ₦800,000, which exceeds the ₦500,000 cap.
    assert compute_rent_relief(kobo(4_000_000), PAYE_RULE) == kobo(500_000)


def test_rent_relief_exactly_at_cap() -> None:
    # 20% of ₦2,500,000 = ₦500,000 exactly.
    assert compute_rent_relief(kobo(2_500_000), PAYE_RULE) == kobo(500_000)


def test_rent_relief_below_cap() -> None:
    # 20% of ₦1,000,000 = ₦200,000, under the cap.
    assert compute_rent_relief(kobo(1_000_000), PAYE_RULE) == kobo(200_000)


def test_zero_rent_paid_gives_zero_relief() -> None:
    assert compute_rent_relief(0, PAYE_RULE) == 0


def test_missing_tin_blocks_the_run() -> None:
    with pytest.raises(MissingTinError):
        ensure_tin_present(None)
    with pytest.raises(MissingTinError):
        ensure_tin_present("   ")


def test_valid_tin_does_not_raise() -> None:
    ensure_tin_present("12345678-0001")


def test_mid_year_pay_change_uses_cumulative_recompute() -> None:
    """A mid-year raise must be taxed via cumulative YTD chargeable income,
    not a naive re-slice of the new monthly figure (§1, §12)."""
    # Jan-Jun at a lower salary: YTD chargeable income reaches ₦1,500,000,
    # with ₦105,000 (₦800k@0% + ₦700k@15%) withheld so far.
    ytd_before_raise = kobo(1_500_000)
    withheld_so_far = compute_paye_annual(ytd_before_raise, BANDS)
    assert withheld_so_far == kobo(105_000)

    # July: a raise pushes YTD cumulative chargeable income to ₦4,000,000.
    ytd_after_raise = kobo(4_000_000)
    incremental_due = compute_incremental_paye(ytd_after_raise, withheld_so_far, BANDS)

    total_owed_on_ytd = compute_paye_annual(ytd_after_raise, BANDS)
    assert incremental_due == total_owed_on_ytd - withheld_so_far
    assert incremental_due > 0

    # A naive monthly slice (ytd_after_raise / 12 * PAYE-on-that-slice * 12)
    # would not equal the cumulative-recompute figure — that's the point.
    naive_monthly_slice = compute_paye_annual(ytd_after_raise // 12, BANDS)
    assert incremental_due != naive_monthly_slice * 12


def test_incremental_paye_never_negative_when_income_falls() -> None:
    """If YTD chargeable income somehow doesn't grow, no PAYE is clawed
    back through this function — it floors at zero."""
    withheld_so_far = compute_paye_annual(kobo(4_000_000), BANDS)
    incremental_due = compute_incremental_paye(kobo(3_000_000), withheld_so_far, BANDS)
    assert incremental_due == 0
