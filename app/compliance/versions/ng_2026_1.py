"""NG-2026.1 — Nigeria Tax Act 2025, effective 1 January 2026.

Every figure here must trace to
.claude/skills/plutus-payroll-python/references/nigeria-statutory-compliance.md.
To change the law, add a new RuleVersion with a later effective_from and a
matching golden-test update — never edit a number here in place; historical
pay runs must stay reproducible against the rules in force at the time.
"""

from datetime import date

from app.compliance.models import (
    Band,
    ItfRule,
    NhfRule,
    NsitfRule,
    PayeRule,
    PensionRule,
    RuleVersion,
    WhtCategoryRule,
    WhtRule,
)

NG_2026_1 = RuleVersion(
    id="NG-2026.1",
    country="NG",
    effective_from=date(2026, 1, 1),
    effective_to=None,
    paye=PayeRule(
        # §1 band table, in kobo (NGN minor units, exponent 2).
        bands=(
            Band(up_to_minor=80_000_000, rate_ppm=0),  # first ₦800,000 @ 0%
            Band(up_to_minor=300_000_000, rate_ppm=150_000),  # to ₦3,000,000 @ 15%
            Band(up_to_minor=1_200_000_000, rate_ppm=180_000),  # to ₦12,000,000 @ 18%
            Band(up_to_minor=2_500_000_000, rate_ppm=210_000),  # to ₦25,000,000 @ 21%
            Band(up_to_minor=5_000_000_000, rate_ppm=230_000),  # to ₦50,000,000 @ 23%
            Band(up_to_minor=None, rate_ppm=250_000),  # above ₦50,000,000 @ 25%
        ),
        tax_free_threshold_minor=80_000_000,  # ₦800,000/yr
        rent_relief_rate_ppm=200_000,  # 20% of annual rent paid
        rent_relief_cap_minor=50_000_000,  # capped at ₦500,000
        due_day_of_following_month=10,  # §9
    ),
    pension=PensionRule(
        employee_rate_ppm=80_000,  # §3: minimum 8% employee
        employer_rate_ppm=100_000,  # §3: minimum 10% employer
        due_working_days_after_payment=7,  # §3 — working days, not "the 7th"; see §11 errata
    ),
    nhf=NhfRule(
        rate_ppm=25_000,  # §4: 2.5% of basic salary
        due_days_after_payment=30,  # §4: within one month; see §11 errata
    ),
    nsitf=NsitfRule(
        rate_ppm=10_000,  # §6: 1% of total monthly payroll (as defined in §6)
        due_day_of_following_month=16,  # §6: before the 16th; see §11 errata
    ),
    itf=ItfRule(
        rate_ppm=10_000,  # §7: 1% of annual payroll, for qualifying employers
        due_month=4,
        due_day=1,  # §7: on/before 1 April annually
    ),
    wht=WhtRule(
        # §8: rates are "commonly 5% or 10% depending on transaction type" —
        # resolve by category, never a flat rate. These two categories are
        # the ones the reference names explicitly; confirm against the NRS
        # schedule before relying on this for a category not listed here.
        categories=(
            WhtCategoryRule(category="goods", rate_ppm=50_000),
            WhtCategoryRule(category="services", rate_ppm=100_000),
        ),
        due_day_of_following_month=21,
    ),
)
