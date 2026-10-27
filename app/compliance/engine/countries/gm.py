"""The Gambia, from January 2026.

Built in: GRA's PAYE rates and its GMD 3,000 monthly threshold, NPF at 5%
employee and 10% employer on basic salary, and the IICF's 1% capped at
GMD 15. Entered by each organisation: the monthly PAYE band limits above the
threshold (GRA publishes annual bands), whether NPF is deductible before
PAYE, what "total earnings" means for the IICF and when it's due, and
whether the organisation is in the Federated Pension Scheme.

Not modelled: fringe benefits tax (Plutus doesn't record benefits in kind)
and the expatriate quota (an annual per-person charge).
"""

# Researched in docs/countries/GM-the-gambia.md.

from datetime import date

from app.compliance.engine.countries._common import (
    ALL_CASH,
    APPROVAL,
    BASIC_ONLY,
    COMPANY_SETTINGS,
    FIXED_PAY,
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

CURRENCY = "GMD"
SSHFC = "Social Security and Housing Finance Corporation"
DUE_15TH = due(15)  # PAYE and NPF: the 15th of the following month

SOURCES = (
    SourceReference(
        id="gra-employment-income-tax-brochure",
        title="GRA, employment income tax brochure: 0% to 25%, bands at GMD 36,000, 46,000, "
        "56,000, 66,000 and 76,000 a year, as at January 2018 (quoted by search)",
        reference="https://www.gra.gm/download-file/8d0ccc58-d217-11ed-9b31-029254d29bb1",
        official=True,
        captured_on=date(2026, 10, 26),
    ),
    SourceReference(
        id="gra-domestic-faqs",
        title="GRA, Domestic taxes FAQs: tax-free GMD 36,000 a year, GMD 3,000 a month "
        "(quoted by search)",
        reference="https://www.gra.gm/domestic-faqs",
        official=True,
        captured_on=date(2026, 10, 26),
    ),
    SourceReference(
        id="sshfc-overview",
        title="SSHFC, overview: NPF employee contribution 5% of basic salary (quoted by search)",
        reference="https://www.sshfc.gm/overview",
        official=True,
        captured_on=date(2026, 10, 26),
    ),
    SourceReference(
        id="nao-sshfc-audit",
        title="National Audit Office, performance audit of SSHFC: NPF employer 10%; Federated "
        "Pension Scheme 15% of gross salary, employer-paid",
        reference="https://nao.gm/wp-content/uploads/2023/04/Performance-Audit-Report-on-the-"
        "Management-of-Social-Security-Funds-by-SSHFC.pdf",
        official=True,
        captured_on=date(2026, 10, 26),
    ),
    SourceReference(
        id="sshfc-iicf",
        title="SSHFC, Industrial Injury Compensation Fund: 1% of total earnings, ceiling GMD 15, "
        "employer-paid (quoted by search)",
        reference="https://www.sshfc.gm/industrial-injury-compensation-fund",
        official=True,
        captured_on=date(2026, 10, 26),
    ),
    SourceReference(
        id="gm-due-dates",
        title="Afrotools, Gambia employer payroll compliance 2026: PAYE and NPF due by the 15th",
        reference="https://afrotools.com/blog/gambia-employer-payroll-compliance-2026/",
        official=False,
        captured_on=RESEARCHED,
    ),
    COMPANY_SETTINGS,
)


def _band_limit(key: str, rate: str, annual: str, monthly: str) -> SettingSpec:
    return SettingSpec(
        key=key,
        label=f"Monthly PAYE: upper limit of the {rate} band",
        help=f"GRA publishes the {rate} band as ending at GMD {annual} a year; its monthly "
        "table wasn't found. Enter the monthly limit you apply, for example the annual "
        "figure divided by 12.",
        kind=SettingKind.AMOUNT,
        options=(option(monthly, f"GMD {annual} ÷ 12", "GRA annual band, divided by 12"),),
        minimum=money("3,000.01", CURRENCY),
    )


SETTINGS = (
    _band_limit("paye_5_band_limit", "5%", "46,000", str(money("3,833.33", CURRENCY))),
    _band_limit("paye_10_band_limit", "10%", "56,000", str(money("4,666.67", CURRENCY))),
    _band_limit("paye_15_band_limit", "15%", "66,000", str(money("5,500.00", CURRENCY))),
    _band_limit("paye_20_band_limit", "20%", "76,000", str(money("6,333.33", CURRENCY))),
    SettingSpec(
        key="npf_tax_deductible",
        label="Is the employee's NPF contribution deducted before PAYE?",
        help="No source found says whether the employee's 5% NPF contribution comes off pay "
        "before PAYE.",
        kind=SettingKind.CHOICE,
        options=(
            option("yes", "Yes", "Your organisation's practice"),
            option("no", "No", "Your organisation's practice"),
        ),
    ),
    SettingSpec(
        key="iicf_base",
        label="What the IICF's 1% is charged on",
        help='SSHFC says 1% of "total earnings" without defining them; one guide says basic '
        "salary plus fixed allowances.",
        kind=SettingKind.CHOICE,
        options=(
            option(
                "fixed_pay",
                "Basic salary plus fixed allowances",
                "Payroll guide (Africarrières)",
            ),
            option("all_earnings", "All cash earnings", 'SSHFC: "total earnings"'),
        ),
    ),
    SettingSpec(
        key="iicf_due_day",
        label="Day of the following month the IICF contribution is due",
        help="No source found gives the IICF deadline.",
        kind=SettingKind.DAY,
    ),
    SettingSpec(
        key="fps_applies",
        label="Is your organisation in the Federated Pension Scheme?",
        help="SSHFC's Federated Pension Scheme is 15% of gross salary (basic plus fixed "
        "allowances), paid by the employer. Which employers it covers wasn't found.",
        kind=SettingKind.CHOICE,
        options=(
            option("yes", "Yes", "SSHFC; National Audit Office report"),
            option("no", "No", "Your organisation isn't in the scheme"),
        ),
    ),
    SettingSpec(
        key="fps_due_day",
        label="Day of the following month the Federated Pension Scheme contribution is due",
        help="No source found gives the Federated Pension Scheme deadline.",
        kind=SettingKind.DAY,
        required_when=("fps_applies", "yes"),
    ),
)


def build(values: SettingValues) -> CountryRuleSet:
    npf_group = "npf" if yes(values, "npf_tax_deductible") else None
    iicf_base = FIXED_PAY if values.get("iicf_base") == "fixed_pay" else ALL_CASH
    contributions = [
        ContributionRule(
            code="NPF",
            name="National Provident Fund",
            kind=ContributionKind.EMPLOYEE,
            authority=SSHFC,
            base=EarningsBase(BASIC_ONLY),
            rounding=HALF_UP,
            due=DUE_15TH,
            source="sshfc-overview",
            liability_account="npf_payable",
            rate_ppm=ppm("5"),
            tax_deduction_group=npf_group,
        ),
        ContributionRule(
            code="NPF-ER",
            name="National Provident Fund (employer)",
            kind=ContributionKind.EMPLOYER,
            authority=SSHFC,
            base=EarningsBase(BASIC_ONLY),
            rounding=HALF_UP,
            due=DUE_15TH,
            source="nao-sshfc-audit",
            liability_account="npf_payable",
            expense_account="payroll_expense_npf",
            rate_ppm=ppm("10"),
        ),
        ContributionRule(
            code="IICF",
            name="Industrial Injury Compensation Fund",
            kind=ContributionKind.EMPLOYER,
            authority=SSHFC,
            base=EarningsBase(iicf_base),
            rounding=HALF_UP,
            due=due(setting_int(values, "iicf_due_day")),
            source="sshfc-iicf",
            liability_account="iicf_payable",
            expense_account="payroll_expense_iicf",
            rate_ppm=ppm("1"),
            amount_cap_minor=money("15", CURRENCY),
        ),
    ]
    if yes(values, "fps_applies"):
        contributions.append(
            ContributionRule(
                code="FPS",
                name="Federated Pension Scheme",
                kind=ContributionKind.EMPLOYER,
                authority=SSHFC,
                base=EarningsBase(FIXED_PAY),
                rounding=HALF_UP,
                due=due(setting_int(values, "fps_due_day")),
                source="nao-sshfc-audit",
                liability_account="fps_payable",
                expense_account="payroll_expense_fps",
                rate_ppm=ppm("15"),
            )
        )
    return CountryRuleSet(
        id="GM-2026.1",
        country="GM",
        currency=CURRENCY,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        tax_year_start_month=1,
        frequencies=frozenset({PayFrequency.MONTHLY}),
        status=RuleSetStatus.ACTIVE,
        approval=APPROVAL,
        sources=SOURCES,
        income_tax=IncomeTaxRule(
            code="PAYE",
            name="PAYE",
            authority="Gambia Revenue Authority",
            method=TaxMethod.PER_PERIOD,
            taxable_categories=ALL_CASH,
            # GRA's rates and monthly threshold; the monthly limits above it
            # are the organisation's (Tax Settings).
            bands=(
                TaxBand(money("3,000", CURRENCY), 0),
                TaxBand(setting_int(values, "paye_5_band_limit"), ppm("5")),
                TaxBand(setting_int(values, "paye_10_band_limit"), ppm("10")),
                TaxBand(setting_int(values, "paye_15_band_limit"), ppm("15")),
                TaxBand(setting_int(values, "paye_20_band_limit"), ppm("20")),
                TaxBand(None, ppm("25")),
            ),
            band_rounding=BandRounding.TOTAL,
            rounding=HALF_UP,
            due=DUE_15TH,
            source="gra-employment-income-tax-brochure",
            liability_account="paye_payable",
            deduction_caps=(DeductionCap("npf", None),) if npf_group else (),
        ),
        contributions=tuple(contributions),
    )


TEMPLATE = RuleSetTemplate(
    id="GM-2026.1",
    country="GM",
    effective_from=date(2026, 1, 1),
    effective_to=None,
    settings=SETTINGS,
    build=build,
    summary=__doc__ or "",
)
