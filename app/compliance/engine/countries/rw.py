"""Rwanda, 2026 and 2027.

Built in: the four-band PAYE schedule of Law No. 027/2022 (0%, 10%, 20% and
30%, with cut-offs at RWF 60,000, 100,000 and 200,000 a month; the
three-band schedule some guides still show was the law's first year only),
RSSB pension on gross pay including transport (6% employee and 6% employer
in 2026; 14% in all from 1 January 2027, under Presidential Order
No. 086/01 of 2024), RSSB maternity leave at 0.3% from the employer, CBHI at
0.5% of the employee's net pay (RRA, citing Prime Minister's Order
No. 034/01 of 2020), and the 15th as the deadline for PAYE, RSSB and CBHI.
Entered by each organisation: whether RSSB contributions are deducted
before PAYE, the employee's maternity rate (sources disagree), what
maternity and occupational hazards are charged on, the occupational hazards
rate (sources disagree), and, from 2027, the employee's share of the 14%
pension (the order doesn't divide it; the employer pays the rest).

Pension rises again to 16% in January 2028, so 2028 periods are refused
until a rule set for 2028 is added.
"""

# Researched in docs/countries/RW-rwanda.md.

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
    NetPayBase,
    RuleSetStatus,
    SourceReference,
    TaxBand,
    TaxMethod,
)
from app.compliance.engine.settings import (
    RuleSetTemplate,
    SettingKind,
    SettingOption,
    SettingSpec,
    SettingValues,
    setting_int,
)
from app.domain.payroll.frequency import PayFrequency

CURRENCY = "RWF"
RRA = "Rwanda Revenue Authority"
RSSB = "Rwanda Social Security Board"
DUE_15TH = due(15)  # PAYE and RSSB: one declaration, by the 15th of the following month

SOURCES = (
    SourceReference(
        id="rw-paye-bands",
        title="Law No. 027/2022 on taxes on income, four-bracket schedule from November 2023, "
        "as reported (Orbitax; PwC Worldwide Tax Summaries)",
        reference="https://taxsummaries.pwc.com/rwanda/individual/taxes-on-personal-income",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="rw-pension-2025",
        title="RSSB pension 6% employee and 6% employer on gross pay including transport, from "
        "January 2025, as reported (Sage, PaySpace, The New Times)",
        reference="https://support.payspace.com/portal/en/kb/articles/rwanda-pension-reforms-"
        "effective-january-2025",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="rw-maternity",
        title="RSSB maternity leave 0.3% employer; employee 0.3% in most sources, 0% in one, "
        "as reported (payroll guides)",
        reference="https://www.playroll.com/payroll/rwanda",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="rra-cbhi",
        title="RRA, CBHI contribution: under Prime Minister's Order No. 034/01 of 13/01/2020, "
        "the employee contributes 0.5% of net salary, deducted and paid by the employer",
        reference="https://www.rra.gov.rw/en/domestic-tax-services/rssb-contributions/"
        "cbhi-contribution",
        official=True,
        captured_on=date(2026, 10, 27),
    ),
    SourceReference(
        id="ey-cbhi-2020",
        title="EY, Rwanda establishes subsidy contributions from employees for the community-"
        "based health insurance scheme: remitted to RSSB by the 15th of the following month",
        reference="https://globaltaxnews.ey.com/news/2020-5351-rwanda-establishes-subsidy-"
        "contributions-from-employees-for-community-based-health-insurance-scheme",
        official=False,
        captured_on=date(2026, 10, 27),
    ),
    SourceReference(
        id="rw-due-dates",
        title="PAYE and RSSB contributions declared to RRA by the 15th of the following month, "
        "as reported (several secondary sources)",
        reference="https://www.rivermate.com/guides/rwanda/taxes",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="rw-pension-order-2024",
        title="Presidential Order No. 086/01 of 12 December 2024 on the pension scheme: "
        "contributions of 12% from 1 January 2025 and 14% from 1 January 2027 (official text, "
        "ILO NATLEX copy)",
        reference="https://natlex.ilo.org/dyn/natlex2/natlex2/files/download/117567/RWA-117567.pdf",
        official=True,
        captured_on=date(2026, 10, 31),
    ),
    SourceReference(
        id="rssb-faq",
        title="RSSB, Frequently asked questions: employer and employee contribute equally to "
        "the pension scheme",
        reference="https://www.rssb.rw/uploads/RSSB_FAQS_All_languages_2_760b75b195.pdf",
        official=True,
        captured_on=date(2026, 10, 31),
    ),
    COMPANY_SETTINGS,
)

_BASES = {
    "all_cash": ALL_CASH,
    "fixed_pay": FIXED_PAY,
    "basic": BASIC_ONLY,
}


def _base_options(what: str) -> tuple[SettingOption, ...]:
    practice = f"Your organisation's practice: no source gives the {what} base"
    return (
        option("all_cash", "Gross pay, as for RSSB pension", practice),
        option("fixed_pay", "Basic salary plus fixed allowances", practice),
        option("basic", "Basic salary", practice),
    )


SETTINGS = (
    SettingSpec(
        key="rssb_tax_deductible",
        label="Are the employee's RSSB pension and maternity contributions deducted before PAYE?",
        help="No statute found says. One payroll vendor works out PAYE on gross pay and takes "
        "the contributions off afterwards, but that is its method, not the law.",
        kind=SettingKind.CHOICE,
        options=(
            option("no", "No", "One payroll vendor's method"),
            option("yes", "Yes", "Your organisation's practice"),
        ),
    ),
    SettingSpec(
        key="maternity_employee_rate",
        label="Employee's RSSB maternity leave rate",
        help="Most sources give 0.3% from the employee as well as 0.3% from the employer; one "
        "gives 0% from the employee.",
        kind=SettingKind.PERCENT,
        options=(
            option(str(ppm("0.3")), "0.3%", "Most sources"),
            option("0", "0%", "One source"),
        ),
    ),
    SettingSpec(
        key="maternity_base",
        label="What RSSB maternity leave is charged on",
        help="No source found gives the base for maternity leave contributions.",
        kind=SettingKind.CHOICE,
        options=_base_options("maternity"),
    ),
    SettingSpec(
        key="occupational_hazards_rate",
        label="Employer's occupational hazards rate",
        help="Sources disagree: 2%, 1% or 0.5%, paid by the employer.",
        kind=SettingKind.PERCENT,
        options=(
            option(str(ppm("2")), "2%", "Secondary source"),
            option(str(ppm("1")), "1%", "Secondary source"),
            option(str(ppm("0.5")), "0.5%", "Secondary source"),
        ),
    ),
    SettingSpec(
        key="occupational_hazards_base",
        label="What occupational hazards contributions are charged on",
        help="No source found gives the base for occupational hazards contributions.",
        kind=SettingKind.CHOICE,
        options=_base_options("occupational hazards"),
    ),
)


PENSION_TOTAL_2027 = ppm("14")

PENSION_SHARE_2027 = SettingSpec(
    key="pension_employee_rate_2027",
    label="Employee's share of the 14% RSSB pension contribution in 2027",
    help="Presidential Order No. 086/01 of 2024 raises the pension contribution to 14% from "
    "1 January 2027 without dividing it between employer and employee. RSSB says both "
    "contribute equally (7% each); payroll guidance says an employer may instead pay the "
    "employee's increase (6% from the employee, 8% from the employer). The employer pays "
    "the rest of the 14%.",
    kind=SettingKind.PERCENT,
    options=(
        option(
            str(ppm("7")), "7%, half each", "RSSB FAQ: employer and employee contribute equally"
        ),
        option(
            str(ppm("6")),
            "6%, the employer pays the employee's increase",
            "Payroll guidance (Sage), as reported",
        ),
    ),
    maximum=PENSION_TOTAL_2027,
)


def _pension(
    employee_ppm: int, employer_ppm: int, source: str, group: str | None
) -> list[ContributionRule]:
    """RSSB pension on gross pay, one line for each side that pays any."""
    lines = []
    if employee_ppm:
        lines.append(
            ContributionRule(
                code="RSSB-PENSION",
                name="RSSB pension",
                kind=ContributionKind.EMPLOYEE,
                authority=RSSB,
                base=EarningsBase(ALL_CASH),
                rounding=HALF_UP,
                due=DUE_15TH,
                source=source,
                liability_account="rssb_payable",
                rate_ppm=employee_ppm,
                tax_deduction_group=group,
            )
        )
    if employer_ppm:
        lines.append(
            ContributionRule(
                code="RSSB-PENSION-ER",
                name="RSSB pension (employer)",
                kind=ContributionKind.EMPLOYER,
                authority=RSSB,
                base=EarningsBase(ALL_CASH),
                rounding=HALF_UP,
                due=DUE_15TH,
                source=source,
                liability_account="rssb_payable",
                expense_account="payroll_expense_rssb",
                rate_ppm=employer_ppm,
            )
        )
    return lines


def build(values: SettingValues) -> CountryRuleSet:
    rssb_group = "rssb" if yes(values, "rssb_tax_deductible") else None
    return _build(
        values,
        rule_set_id="RW-2026.1",
        effective_from=date(2026, 1, 1),
        effective_to=date(2027, 1, 1),
        pension=_pension(ppm("6"), ppm("6"), "rw-pension-2025", rssb_group),
    )


def build_2027(values: SettingValues) -> CountryRuleSet:
    rssb_group = "rssb" if yes(values, "rssb_tax_deductible") else None
    employee_ppm = setting_int(values, PENSION_SHARE_2027.key)
    # The order sets the total; the organisation's setting divides it.
    return _build(
        values,
        rule_set_id="RW-2027.1",
        effective_from=date(2027, 1, 1),
        effective_to=date(2028, 1, 1),
        pension=_pension(
            employee_ppm,
            PENSION_TOTAL_2027 - employee_ppm,
            "rw-pension-order-2024",
            rssb_group,
        ),
    )


def _build(
    values: SettingValues,
    *,
    rule_set_id: str,
    effective_from: date,
    effective_to: date,
    pension: list[ContributionRule],
) -> CountryRuleSet:
    rssb_group = "rssb" if yes(values, "rssb_tax_deductible") else None
    maternity_base = EarningsBase(_BASES[values["maternity_base"]])
    contributions = list(pension)
    maternity_employee_ppm = setting_int(values, "maternity_employee_rate")
    if maternity_employee_ppm:
        contributions.append(
            ContributionRule(
                code="RSSB-MATERNITY",
                name="RSSB maternity leave",
                kind=ContributionKind.EMPLOYEE,
                authority=RSSB,
                base=maternity_base,
                rounding=HALF_UP,
                due=DUE_15TH,
                source="company-settings",
                liability_account="rssb_payable",
                rate_ppm=maternity_employee_ppm,
                tax_deduction_group=rssb_group,
            )
        )
    contributions += [
        ContributionRule(
            code="RSSB-MATERNITY-ER",
            name="RSSB maternity leave (employer)",
            kind=ContributionKind.EMPLOYER,
            authority=RSSB,
            base=maternity_base,
            rounding=HALF_UP,
            due=DUE_15TH,
            source="rw-maternity",
            liability_account="rssb_payable",
            expense_account="payroll_expense_rssb",
            rate_ppm=ppm("0.3"),
        ),
        ContributionRule(
            code="RSSB-HAZARDS-ER",
            name="RSSB occupational hazards (employer)",
            kind=ContributionKind.EMPLOYER,
            authority=RSSB,
            base=EarningsBase(_BASES[values["occupational_hazards_base"]]),
            rounding=HALF_UP,
            due=DUE_15TH,
            source="company-settings",
            liability_account="rssb_payable",
            expense_account="payroll_expense_rssb",
            rate_ppm=setting_int(values, "occupational_hazards_rate"),
        ),
        # Worked out after PAYE and the contributions above, on what's left.
        # Remitted to RSSB by the 15th (EY).
        ContributionRule(
            code="CBHI",
            name="Community-based health insurance",
            kind=ContributionKind.EMPLOYEE,
            authority=RSSB,
            base=NetPayBase(),
            rounding=HALF_UP,
            due=DUE_15TH,
            source="rra-cbhi",
            liability_account="cbhi_payable",
            rate_ppm=ppm("0.5"),
        ),
    ]
    return CountryRuleSet(
        id=rule_set_id,
        country="RW",
        currency=CURRENCY,
        effective_from=effective_from,
        effective_to=effective_to,
        tax_year_start_month=1,
        frequencies=frozenset({PayFrequency.MONTHLY}),
        status=RuleSetStatus.ACTIVE,
        approval=APPROVAL,
        sources=SOURCES,
        income_tax=IncomeTaxRule(
            code="PAYE",
            name="PAYE",
            authority=RRA,
            method=TaxMethod.PER_PERIOD,
            taxable_categories=ALL_CASH,
            bands=(
                TaxBand(money("60,000", CURRENCY), 0),
                TaxBand(money("100,000", CURRENCY), ppm("10")),
                TaxBand(money("200,000", CURRENCY), ppm("20")),
                TaxBand(None, ppm("30")),
            ),
            # RWF has no smaller unit: PAYE is rounded once, to the franc.
            band_rounding=BandRounding.TOTAL,
            rounding=HALF_UP,
            due=DUE_15TH,
            source="rw-paye-bands",
            liability_account="paye_payable",
            deduction_caps=(DeductionCap("rssb", None),) if rssb_group else (),
        ),
        contributions=tuple(contributions),
    )


TEMPLATE = RuleSetTemplate(
    id="RW-2026.1",
    country="RW",
    effective_from=date(2026, 1, 1),
    effective_to=date(2027, 1, 1),
    settings=SETTINGS,
    build=build,
    summary=__doc__ or "",
)

# The same rules, with 14% pension divided as the organisation enters it.
TEMPLATE_2027 = RuleSetTemplate(
    id="RW-2027.1",
    country="RW",
    effective_from=date(2027, 1, 1),
    effective_to=date(2028, 1, 1),
    settings=(*SETTINGS, PENSION_SHARE_2027),
    build=build_2027,
    summary=__doc__ or "",
)
