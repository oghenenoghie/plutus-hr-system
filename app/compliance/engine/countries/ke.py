"""Kenya, from February 2026 (NSSF Year 4 rates).

Built in: the PAYE bands and personal relief, what's deductible before PAYE
under KRA's December 2024 notice, NSSF, SHIF, the Affordable Housing Levy and
the NITA levy's amount. Entered by each organisation: whether NSSF is
deductible before PAYE (no source settles it), whether it pays the NITA levy
and when it's due (sources disagree). Mortgage interest and post-retirement
medical fund deductions are voluntary and aren't modelled.
"""

# Researched in docs/countries/KE-kenya.md.

from datetime import date

from app.compliance.engine.countries._common import (
    ALL_CASH,
    APPROVAL,
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
    FixedCredit,
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

CURRENCY = "KES"
PAYE_DUE = due(9)  # PAYE, NSSF, SHIF and the Housing Levy: the 9th of the following month

SOURCES = (
    SourceReference(
        id="kra-paye-notice-2024",
        title="KRA, Amendments to PAYE computation pursuant to the Tax Laws (Amendment) Act, "
        "2024 (deductions before PAYE, from December 2024 payroll)",
        reference="https://www.kra.go.ke/news-center/public-notices/2157-amendments-to-paye-"
        "computation-pursuant-to-the-tax-laws-amendment-act%2C-2024",
        official=True,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="ke-paye-bands",
        title="PAYE bands (Finance Act 2023) and personal relief, as reported for 2026 "
        "(Business Radar and other secondary sources)",
        reference="https://businessradar.co.ke/?p=9779",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="nssf-year-4-notice",
        title="NSSF, Notice to employers: Year 4 (2026) contribution rates, from February 2026",
        reference="https://www.nssf.or.ke/notice-to-employers-year-4-2026-nssf-contribution-rates",
        official=True,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="shif-act-2023",
        title="Social Health Insurance Act 2023 and regulations of 8 March 2024, as reported (EY)",
        reference="https://www.ey.com/en_gl/technical/tax-alerts/kenya-employers-to-begin-"
        "making-contributions-to-social-health-insurance-fund",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="housing-levy-2024",
        title="Affordable Housing Act 2024, as reported (Business Daily)",
        reference="https://www.businessdailyafrica.com/bd/economy/workers-gain-as-kra-grants-"
        "tax-relief-on-housing-levy-shif-4863782",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="nita-faq",
        title="NITA, levy FAQ (KES 50 per employee a month)",
        reference="https://www.nita.go.ke/faq-s/99-nita-services",
        official=True,
        captured_on=RESEARCHED,
    ),
    COMPANY_SETTINGS,
)

SETTINGS = (
    SettingSpec(
        key="nssf_tax_deductible",
        label="Is the employee's NSSF contribution deducted before PAYE?",
        help="KRA's December 2024 notice lets pension contributions up to KES 30,000 a month "
        "come off pay before PAYE, but doesn't name NSSF. The Finance Committee chair said in "
        "June 2024 that NSSF savings would be deductible.",
        kind=SettingKind.CHOICE,
        options=(
            option(
                "yes",
                "Yes, within the KES 30,000 a month pension cap",
                "Finance Committee chair, June 2024 debate (reported)",
            ),
            option("no", "No", "KRA's December 2024 notice doesn't name NSSF"),
        ),
    ),
    SettingSpec(
        key="nita_applies",
        label="Does your organisation pay the NITA industrial training levy?",
        help="Sources disagree on which employers must pay: one says those with more than 20 "
        "employees, another those with 100 or more. Hotels and restaurants paying the catering "
        "levy are exempt.",
        kind=SettingKind.CHOICE,
        options=(
            option("yes", "Yes", "NITA levy FAQ"),
            option("no", "No", "Exempt, or below the threshold that applies to you"),
        ),
    ),
    SettingSpec(
        key="nita_due_day",
        label="Day of the following month the NITA levy is due",
        help="Sources disagree: the 5th (Industrial Training (Amendment) Act 2022, as reported) "
        "or the 10th (older guidance) of the following month. NITA's FAQ says the last working "
        "day of the month itself; Plutus records a day of the following month.",
        kind=SettingKind.DAY,
        options=(
            option("5", "5th", "Industrial Training (Amendment) Act 2022, as reported"),
            option("10", "10th", "Older NITA guidance"),
        ),
        required_when=("nita_applies", "yes"),
    ),
)


def build(values: SettingValues) -> CountryRuleSet:
    def kes(amount: str) -> int:
        return money(amount, CURRENCY)

    nssf_group = "pension" if yes(values, "nssf_tax_deductible") else None
    contributions = [
        ContributionRule(
            code="NSSF",
            name="NSSF",
            kind=ContributionKind.EMPLOYEE,
            authority="National Social Security Fund",
            base=EarningsBase(ALL_CASH),
            rounding=HALF_UP,
            due=PAYE_DUE,
            source="nssf-year-4-notice",
            liability_account="nssf_payable",
            rate_ppm=ppm("6"),
            base_ceiling_minor=kes("108,000"),  # the Upper Earnings Limit: at most KES 6,480
            tax_deduction_group=nssf_group,
        ),
        ContributionRule(
            code="NSSF-ER",
            name="NSSF (employer)",
            kind=ContributionKind.EMPLOYER,
            authority="National Social Security Fund",
            base=EarningsBase(ALL_CASH),
            rounding=HALF_UP,
            due=PAYE_DUE,
            source="nssf-year-4-notice",
            liability_account="nssf_payable",
            expense_account="payroll_expense_nssf",
            rate_ppm=ppm("6"),
            base_ceiling_minor=kes("108,000"),
        ),
        ContributionRule(
            code="SHIF",
            name="Social Health Insurance Fund",
            kind=ContributionKind.EMPLOYEE,
            authority="Social Health Authority",
            base=EarningsBase(ALL_CASH),
            rounding=HALF_UP,
            due=PAYE_DUE,
            source="shif-act-2023",
            liability_account="shif_payable",
            rate_ppm=ppm("2.75"),
            amount_floor_minor=kes("300"),
            tax_deduction_group="shif",
        ),
        ContributionRule(
            code="HOUSING-LEVY",
            name="Affordable Housing Levy",
            kind=ContributionKind.EMPLOYEE,
            authority="Kenya Revenue Authority",
            base=EarningsBase(ALL_CASH),
            rounding=HALF_UP,
            due=PAYE_DUE,
            source="housing-levy-2024",
            liability_account="housing_levy_payable",
            rate_ppm=ppm("1.5"),
            tax_deduction_group="housing_levy",
        ),
        ContributionRule(
            code="HOUSING-LEVY-ER",
            name="Affordable Housing Levy (employer)",
            kind=ContributionKind.EMPLOYER,
            authority="Kenya Revenue Authority",
            base=EarningsBase(ALL_CASH),
            rounding=HALF_UP,
            due=PAYE_DUE,
            source="housing-levy-2024",
            liability_account="housing_levy_payable",
            expense_account="payroll_expense_housing_levy",
            rate_ppm=ppm("1.5"),
        ),
    ]
    if yes(values, "nita_applies"):
        contributions.append(
            ContributionRule(
                code="NITA",
                name="Industrial Training Levy (NITA)",
                kind=ContributionKind.EMPLOYER,
                authority="National Industrial Training Authority",
                base=EarningsBase(ALL_CASH),
                rounding=HALF_UP,
                due=due(setting_int(values, "nita_due_day")),
                source="nita-faq",
                liability_account="nita_payable",
                expense_account="payroll_expense_nita",
                flat_amount_minor=kes("50"),
            )
        )
    return CountryRuleSet(
        id="KE-2026.1",
        country="KE",
        currency=CURRENCY,
        effective_from=date(2026, 2, 1),
        effective_to=None,
        tax_year_start_month=1,
        frequencies=frozenset({PayFrequency.MONTHLY}),
        status=RuleSetStatus.ACTIVE,
        approval=APPROVAL,
        sources=SOURCES,
        income_tax=IncomeTaxRule(
            code="PAYE",
            name="PAYE",
            authority="Kenya Revenue Authority",
            method=TaxMethod.PER_PERIOD,
            taxable_categories=ALL_CASH,
            bands=(
                TaxBand(kes("24,000"), ppm("10")),
                TaxBand(kes("32,333"), ppm("25")),
                TaxBand(kes("500,000"), ppm("30")),
                TaxBand(kes("800,000"), ppm("32.5")),
                TaxBand(None, ppm("35")),
            ),
            band_rounding=BandRounding.TOTAL,
            rounding=HALF_UP,
            due=PAYE_DUE,
            source="ke-paye-bands",
            liability_account="paye_payable",
            # KRA's December 2024 notice: the Housing Levy and SHIF in full,
            # pension contributions up to KES 30,000 a month.
            deduction_caps=(
                DeductionCap("pension", kes("30,000")),
                DeductionCap("shif", None),
                DeductionCap("housing_levy", None),
            ),
            credits=(FixedCredit("PERSONAL-RELIEF", kes("2,400"), "ke-paye-bands"),),
        ),
        contributions=tuple(contributions),
    )


TEMPLATE = RuleSetTemplate(
    id="KE-2026.1",
    country="KE",
    effective_from=date(2026, 2, 1),
    effective_to=None,
    settings=SETTINGS,
    build=build,
    summary=__doc__ or "",
)
