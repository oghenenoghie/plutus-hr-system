"""Ghana, from 1 September 2026 (Income Tax (Amendment) Act 2026, Act 1178).

Built in: the Act 1178 PAYE rates and the GHS 588 monthly threshold, PAYE
due on the 15th, and social security at 5.5% employee and 13% employer on
basic salary, paid out as the SSNIT Omnibus's worked example pays it: 13.5%
to SSNIT (Tier 1) and 5% to the Tier 2 corporate trustee. Entered by each
organisation: the monthly PAYE band limits above the threshold (GRA's
monthly table wasn't found, and sources disagree where 30% starts), whether
SSNIT is deductible before PAYE, the contribution ceiling (sources
disagree), and the SSNIT and Tier 2 deadlines.

Periods before 1 September 2026 aren't covered: the earlier schedule wasn't
captured, so they're refused.
"""

# Researched in docs/countries/GH-ghana.md.

from datetime import date

from app.compliance.engine.countries._common import (
    ALL_CASH,
    APPROVAL,
    BASIC_ONLY,
    COMPANY_SETTINGS,
    HALF_UP,
    RESEARCHED,
    due,
    money,
    option,
    ppm,
    yes,
)
from app.compliance.engine.rules import (
    BandRounding,
    ContributionKind,
    ContributionRule,
    CountryRuleSet,
    DeductionCap,
    EarningsBase,
    IncomeTaxRule,
    RuleSetStatus,
    SourceReference,
    TaxBand,
    TaxMethod,
)
from app.compliance.engine.settings import (
    RuleSetTemplate,
    SettingKind,
    SettingSpec,
    SettingValues,
    setting_int,
)
from app.domain.payroll.frequency import PayFrequency

CURRENCY = "GHS"
SSNIT = "Social Security and National Insurance Trust"
TIER_2 = "Tier 2 corporate trustee"
PAYE_DUE = due(15)

SOURCES = (
    SourceReference(
        id="gra-act-1178",
        title="GRA, Amendments: Income Tax (Amendment) Act, 2026 (Act 1178), new rates from "
        "1 September 2026; first GHS 7,056 a year at 0%",
        reference="https://gra.gov.gh/news/portfolio/amendments-income-tax-act-2026-act-1178/",
        official=True,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="gh-paye-bands",
        title="Act 1178 annual bands and the GHS 588 monthly threshold, as reported (Mercans, "
        "Regfollower, GhanaWeb, TaxLawGH)",
        reference="https://mercans.com/resources/statutory-alerts/ghana-revised-personal-income-"
        "tax-paye-rates-1st-september-2026/",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="ssnit-omnibus",
        title="SSNIT, Omnibus: worked example paying 13.5% of basic salary to SSNIT (Tier 1) "
        "and 5% to the Tier 2 trustee",
        reference="https://www.ssnit.org.gh/wp-content/uploads/2023/08/SSNIT-Omnibus.pdf",
        official=True,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="gh-ssnit-rates",
        title="National Pensions Act 2008 (Act 766) rates: 5.5% employee and 13% employer of "
        "basic salary, as reported (several secondary sources)",
        reference="https://www.taxlawgh.com/ghana-tax-rates",
        official=False,
        captured_on=RESEARCHED,
    ),
    COMPANY_SETTINGS,
)


def _band_limit(key: str, rate: str, annual: str, monthly: str) -> SettingSpec:
    return SettingSpec(
        key=key,
        label=f"Monthly PAYE: upper limit of the {rate} band",
        help=f"Act 1178's {rate} band ends at GHS {annual} a year, as reported; GRA's monthly "
        "table wasn't found, and dividing by 12 isn't a substitute for it. Enter the monthly "
        "limit from GRA's table.",
        kind=SettingKind.AMOUNT,
        options=(option(monthly, f"GHS {annual} ÷ 12", "Act 1178 annual band, divided by 12"),),
        minimum=money("588.01", CURRENCY),
    )


def _ghs(amount: str) -> str:
    return str(money(amount, CURRENCY))


SETTINGS = (
    _band_limit("paye_5_band_limit", "5%", "8,016", _ghs("668")),
    _band_limit("paye_10_band_limit", "10%", "9,216", _ghs("768")),
    _band_limit("paye_17_5_band_limit", "17.5%", "44,016", _ghs("3,668")),
    SettingSpec(
        key="paye_25_band_limit",
        label="Monthly PAYE: upper limit of the 25% band",
        help="Sources disagree where 30% starts: most go straight from 25% to 30% at GHS "
        "236,016 a year; Regfollower reproduces a GRA-style table with 30% from GHS 408,000. "
        "GRA's monthly table wasn't found. Enter the monthly limit from GRA's table.",
        kind=SettingKind.AMOUNT,
        options=(
            option(_ghs("19,668"), "GHS 236,016 ÷ 12", "Most sources: Mercans, GhanaWeb"),
            option(_ghs("34,000"), "GHS 408,000 ÷ 12", "Regfollower"),
        ),
        minimum=money("588.01", CURRENCY),
    ),
    _band_limit("paye_30_band_limit", "30%", "600,000", _ghs("50,000")),
    SettingSpec(
        key="ssnit_tax_deductible",
        label="Is the employee's 5.5% SSNIT contribution deducted before PAYE?",
        help="No source found says whether the employee's social security contribution comes "
        "off pay before PAYE.",
        kind=SettingKind.CHOICE,
        options=(
            option("yes", "Yes", "Your organisation's practice"),
            option("no", "No", "Your organisation's practice"),
        ),
    ),
    SettingSpec(
        key="ssnit_monthly_ceiling",
        label="Monthly ceiling on basic salary for social security",
        help="Sources disagree: GHS 69,000 a month in one, GHS 61,000 a year in another.",
        kind=SettingKind.AMOUNT,
        options=(
            option(_ghs("69,000"), "GHS 69,000 a month", "Secondary source"),
            option(_ghs("5,083.33"), "GHS 61,000 a year ÷ 12", "Secondary source"),
        ),
        minimum=1,
    ),
    SettingSpec(
        key="ssnit_due_day",
        label="Day of the following month SSNIT (Tier 1) is due",
        help="Most sources say the 15th; one payroll vendor says the 14th (unverified).",
        kind=SettingKind.DAY,
        options=(
            option("15", "15th", "Several secondary sources"),
            option("14", "14th", "One payroll vendor (unverified)"),
        ),
    ),
    SettingSpec(
        key="tier2_due_day",
        label="Day of the following month the Tier 2 contribution is due",
        help="No source found gives the deadline for paying the Tier 2 corporate trustee.",
        kind=SettingKind.DAY,
    ),
)


def build(values: SettingValues) -> CountryRuleSet:
    ceiling = setting_int(values, "ssnit_monthly_ceiling")
    ssnit_due = due(setting_int(values, "ssnit_due_day"))
    ssnit_group = "ssnit" if yes(values, "ssnit_tax_deductible") else None
    return CountryRuleSet(
        id="GH-2026.2",
        country="GH",
        currency=CURRENCY,
        effective_from=date(2026, 9, 1),
        effective_to=None,
        tax_year_start_month=1,
        frequencies=frozenset({PayFrequency.MONTHLY}),
        status=RuleSetStatus.ACTIVE,
        approval=APPROVAL,
        sources=SOURCES,
        income_tax=IncomeTaxRule(
            code="PAYE",
            name="PAYE",
            authority="Ghana Revenue Authority",
            method=TaxMethod.PER_PERIOD,
            taxable_categories=ALL_CASH,
            # Act 1178's rates and monthly threshold; the monthly limits above
            # it are the organisation's (Tax Settings).
            bands=(
                TaxBand(money("588", CURRENCY), 0),
                TaxBand(setting_int(values, "paye_5_band_limit"), ppm("5")),
                TaxBand(setting_int(values, "paye_10_band_limit"), ppm("10")),
                TaxBand(setting_int(values, "paye_17_5_band_limit"), ppm("17.5")),
                TaxBand(setting_int(values, "paye_25_band_limit"), ppm("25")),
                TaxBand(setting_int(values, "paye_30_band_limit"), ppm("30")),
                TaxBand(None, ppm("35")),
            ),
            band_rounding=BandRounding.TOTAL,
            rounding=HALF_UP,
            due=PAYE_DUE,
            source="gh-paye-bands",
            liability_account="paye_payable",
            deduction_caps=(DeductionCap("ssnit", None),) if ssnit_group else (),
        ),
        # 18.5% of basic salary: 5.5% from the employee, 13% from the
        # employer. The Omnibus pays 13.5% to SSNIT and 5% to the Tier 2
        # trustee, so the employer's 13% is shown as 8% to SSNIT and 5% to
        # the trustee: each payee is owed what the Omnibus says.
        contributions=(
            ContributionRule(
                code="SSNIT",
                name="Social security (SSNIT)",
                kind=ContributionKind.EMPLOYEE,
                authority=SSNIT,
                base=EarningsBase(BASIC_ONLY),
                rounding=HALF_UP,
                due=ssnit_due,
                source="gh-ssnit-rates",
                liability_account="ssnit_payable",
                rate_ppm=ppm("5.5"),
                base_ceiling_minor=ceiling,
                tax_deduction_group=ssnit_group,
            ),
            ContributionRule(
                code="SSNIT-ER",
                name="Social security, Tier 1 (employer)",
                kind=ContributionKind.EMPLOYER,
                authority=SSNIT,
                base=EarningsBase(BASIC_ONLY),
                rounding=HALF_UP,
                due=ssnit_due,
                source="ssnit-omnibus",
                liability_account="ssnit_payable",
                expense_account="payroll_expense_ssnit",
                rate_ppm=ppm("8"),
                base_ceiling_minor=ceiling,
            ),
            ContributionRule(
                code="TIER2-ER",
                name="Occupational pension, Tier 2 (employer)",
                kind=ContributionKind.EMPLOYER,
                authority=TIER_2,
                base=EarningsBase(BASIC_ONLY),
                rounding=HALF_UP,
                due=due(setting_int(values, "tier2_due_day")),
                source="ssnit-omnibus",
                liability_account="tier2_pension_payable",
                expense_account="payroll_expense_tier2_pension",
                rate_ppm=ppm("5"),
                base_ceiling_minor=ceiling,
            ),
        ),
    )


TEMPLATE = RuleSetTemplate(
    id="GH-2026.2",
    country="GH",
    effective_from=date(2026, 9, 1),
    effective_to=None,
    settings=SETTINGS,
    build=build,
    summary=__doc__ or "",
)
