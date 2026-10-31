"""Côte d'Ivoire, for 2026.

Built in: the six-band ITS schedule (Ordonnance No. 2023-719, from 2024),
its family reduction (RICF: XOF 5,500 a month for each half-share above
one share, counting up to five shares), CNPS retirement at 6.3% employee
and 7.7% employer, maternity at 0.75% from the employer, and universal
health cover (CMU) at XOF 1,000 a month. Entered by each organisation,
where no source settles them or sources disagree: what CNPS contributions
are charged on, the retirement ceiling, the family benefits rate, the
ceiling on family benefits, maternity and work accidents, the employer's
work accident rate, the employee's share of CMU, the training levy rates,
the employer tax on salaries, and every deadline.

ITS needs each employee's family shares, and the employer tax on salaries
whether each is an expatriate: payroll refuses an employee without them.
CMU is charged for the employee only; dependants' cover isn't included.
"""

# Researched in docs/countries/CI-cote-divoire.md.

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
)
from app.compliance.engine.rules import (
    Applicability,
    BandRounding,
    ContributionKind,
    ContributionRule,
    CountryRuleSet,
    EarningsBase,
    FamilySharesCredit,
    IncomeTaxRule,
    PayrollLevyRule,
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

CURRENCY = "XOF"
DGI = "Direction Générale des Impôts"
CNPS = "Caisse Nationale de Prévoyance Sociale"
FDFP = "Fonds de Développement de la Formation Professionnelle"
CMU_PER_PERSON = money("1,000", CURRENCY)

SOURCES = (
    SourceReference(
        id="ci-its",
        title="ITS schedule (CGI article 119 bis) and family reduction (article 120) after "
        "Ordonnance No. 2023-719, as reported for 2026 (AfricaPaieRH, Kabomal)",
        reference="https://africapaierh.com/blog/calcul-its-cote-divoire-2026/",
        official=False,
        captured_on=RESEARCHED,
    ),
    SourceReference(
        id="ci-cnps",
        title="CLEISS, Les cotisations en Côte d'Ivoire: retirement 6.3% employee and 7.7% "
        "employer, maternity 0.75%, CMU XOF 1,000 a person a month (rates at 1 January 2025)",
        reference="https://www.cleiss.fr/docs/cotisations/cotedivoire.html",
        official=False,
        captured_on=RESEARCHED,
    ),
    COMPANY_SETTINGS,
)


def _xof(amount: str) -> str:
    return str(money(amount, CURRENCY))


def _deadline(key: str, what: str) -> SettingSpec:
    return SettingSpec(
        key=key,
        label=f"Day of the following month {what} due",
        help=f"No source found gives the deadline for {what.removesuffix(' is').removesuffix(' are')}.",
        kind=SettingKind.DAY,
    )


SETTINGS = (
    SettingSpec(
        key="cnps_base",
        label="What CNPS contributions are charged on",
        help="No source found states the pay CNPS contributions are charged on. The ITS is "
        "charged on gross pay.",
        kind=SettingKind.CHOICE,
        options=(
            option("all_cash", "Gross pay", "Your organisation's practice"),
            option(
                "fixed_pay", "Basic salary plus fixed allowances", "Your organisation's practice"
            ),
            option("basic", "Basic salary", "Your organisation's practice"),
        ),
    ),
    SettingSpec(
        key="cnps_retirement_ceiling",
        label="Monthly ceiling for CNPS retirement contributions",
        help="Sources disagree: XOF 3,375,000 a month (CLEISS, rates at 1 January 2025) or "
        "XOF 1,647,315 a month (a 2026 source).",
        kind=SettingKind.AMOUNT,
        options=(
            option(_xof("3,375,000"), "XOF 3,375,000", "CLEISS, rates at 1 January 2025"),
            option(_xof("1,647,315"), "XOF 1,647,315", "A 2026 source"),
        ),
        minimum=1,
    ),
    SettingSpec(
        key="family_benefits_rate",
        label="Employer's CNPS family benefits rate",
        help="Sources disagree: 5% (CLEISS 2025) or 5.75% (a 2026 source). 5.75% may be 5% "
        "plus the 0.75% maternity rate reported together; maternity is charged separately "
        "here, so choose 5% if that's the case.",
        kind=SettingKind.PERCENT,
        options=(
            option(str(ppm("5")), "5%", "CLEISS, rates at 1 January 2025"),
            option(str(ppm("5.75")), "5.75%", "A 2026 source"),
        ),
    ),
    SettingSpec(
        key="cnps_other_ceiling",
        label="Monthly ceiling for family benefits, maternity and work accidents",
        help="No source found gives the ceiling for these CNPS branches. Enter the monthly "
        "ceiling CNPS applies to your organisation.",
        kind=SettingKind.AMOUNT,
        minimum=1,
    ),
    SettingSpec(
        key="work_accident_rate",
        label="Employer's CNPS work accident rate",
        help="2% to 5% depending on the organisation's risk class, and revised for its claims "
        "record. Enter the rate CNPS has notified you of.",
        kind=SettingKind.PERCENT,
    ),
    SettingSpec(
        key="cmu_employee_amount",
        label="Employee's share of the XOF 1,000 monthly CMU contribution",
        help="CMU is XOF 1,000 a person a month (CLEISS); how it splits between employer and "
        "employee wasn't found. The employer pays the rest. Dependants' cover isn't included.",
        kind=SettingKind.AMOUNT,
        maximum=CMU_PER_PERSON,
    ),
    SettingSpec(
        key="apprenticeship_tax_rate",
        label="Apprenticeship tax (FDFP) rate",
        help="Sources disagree: 0.4% of gross pay (Africarrières, Deel) or 0.5% (Rivermate, "
        "French edition).",
        kind=SettingKind.PERCENT,
        options=(
            option(str(ppm("0.4")), "0.4%", "Africarrières; Deel"),
            option(str(ppm("0.5")), "0.5%", "Rivermate (French edition)"),
        ),
    ),
    SettingSpec(
        key="continuing_training_rate",
        label="Continuing-training tax (FDFP) rate",
        help="Sources disagree: 1.2% of gross pay in all (0.6% plus 0.6%; Africarrières, Deel) "
        "or 1.5% (Rivermate, French edition).",
        kind=SettingKind.PERCENT,
        options=(
            option(str(ppm("1.2")), "1.2%", "Africarrières; Deel"),
            option(str(ppm("1.5")), "1.5%", "Rivermate (French edition)"),
        ),
    ),
    SettingSpec(
        key="employer_salary_tax",
        label="Employer tax on salaries",
        help="Sources disagree on the rates for local staff and expatriates. Each employee's "
        "record must say whether they're an expatriate.",
        kind=SettingKind.CHOICE,
        options=(
            option(
                "2.8_12",
                "2.8% for local staff, 12% for expatriates",
                "Rivermate (English edition, July 2025)",
            ),
            option(
                "1.2_10.4",
                "1.2% for local staff, 10.4% for expatriates",
                "Rivermate (French edition)",
            ),
        ),
    ),
    _deadline("its_due_day", "ITS is"),
    _deadline("cnps_due_day", "CNPS contributions are"),
    _deadline("employer_taxes_due_day", "the training levies and employer tax on salaries are"),
)

_EMPLOYER_SALARY_TAX = {"2.8_12": ("2.8", "12"), "1.2_10.4": ("1.2", "10.4")}
_CNPS_BASES = {"all_cash": ALL_CASH, "fixed_pay": FIXED_PAY, "basic": BASIC_ONLY}


def build(values: SettingValues) -> CountryRuleSet:
    cnps_due = due(setting_int(values, "cnps_due_day"))
    employer_taxes_due = due(setting_int(values, "employer_taxes_due_day"))
    retirement_ceiling = setting_int(values, "cnps_retirement_ceiling")
    other_ceiling = setting_int(values, "cnps_other_ceiling")
    cmu_employee = setting_int(values, "cmu_employee_amount")
    local_rate, expatriate_rate = _EMPLOYER_SALARY_TAX[values["employer_salary_tax"]]
    cnps_base = EarningsBase(_CNPS_BASES[values["cnps_base"]])

    def cnps(
        code: str,
        name: str,
        kind: ContributionKind,
        *,
        source: str,
        rate_ppm: int | None = None,
        flat_amount_minor: int | None = None,
        ceiling: int | None = None,
    ) -> ContributionRule:
        employer = kind is ContributionKind.EMPLOYER
        return ContributionRule(
            code=code,
            name=name,
            kind=kind,
            authority=CNPS,
            base=cnps_base,
            rounding=HALF_UP,
            due=cnps_due,
            source=source,
            liability_account="cnps_payable",
            expense_account="payroll_expense_cnps" if employer else None,
            rate_ppm=rate_ppm,
            flat_amount_minor=flat_amount_minor,
            base_ceiling_minor=ceiling,
        )

    def salary_tax(code: str, name: str, rate: str, applies_to: Applicability) -> ContributionRule:
        return ContributionRule(
            code=code,
            name=name,
            kind=ContributionKind.EMPLOYER,
            authority=DGI,
            base=EarningsBase(ALL_CASH),
            rounding=HALF_UP,
            due=employer_taxes_due,
            source="company-settings",
            liability_account="employer_salary_tax_payable",
            expense_account="payroll_expense_employer_salary_tax",
            rate_ppm=ppm(rate),
            applies_to=applies_to,
        )

    employee, employer = ContributionKind.EMPLOYEE, ContributionKind.EMPLOYER
    contributions = [
        cnps(
            "CNPS-RETIREMENT",
            "CNPS retirement",
            employee,
            source="ci-cnps",
            rate_ppm=ppm("6.3"),
            ceiling=retirement_ceiling,
        ),
        cnps(
            "CNPS-RETIREMENT-ER",
            "CNPS retirement (employer)",
            employer,
            source="ci-cnps",
            rate_ppm=ppm("7.7"),
            ceiling=retirement_ceiling,
        ),
        cnps(
            "CNPS-FAMILY-ER",
            "CNPS family benefits (employer)",
            employer,
            source="company-settings",
            rate_ppm=setting_int(values, "family_benefits_rate"),
            ceiling=other_ceiling,
        ),
        cnps(
            "CNPS-MATERNITY-ER",
            "CNPS maternity (employer)",
            employer,
            source="ci-cnps",
            rate_ppm=ppm("0.75"),
            ceiling=other_ceiling,
        ),
        cnps(
            "CNPS-ACCIDENT-ER",
            "CNPS work accidents (employer)",
            employer,
            source="company-settings",
            rate_ppm=setting_int(values, "work_accident_rate"),
            ceiling=other_ceiling,
        ),
    ]
    if cmu_employee:
        contributions.append(
            cnps(
                "CMU",
                "Universal health cover (CMU)",
                employee,
                source="company-settings",
                flat_amount_minor=cmu_employee,
            )
        )
    if cmu_employee < CMU_PER_PERSON:
        contributions.append(
            cnps(
                "CMU-ER",
                "Universal health cover (CMU, employer)",
                employer,
                source="company-settings",
                flat_amount_minor=CMU_PER_PERSON - cmu_employee,
            )
        )
    contributions += [
        salary_tax(
            "SALARY-TAX-LOCAL-ER",
            "Employer tax on salaries (local staff)",
            local_rate,
            Applicability.LOCAL_STAFF,
        ),
        salary_tax(
            "SALARY-TAX-EXPAT-ER",
            "Employer tax on salaries (expatriates)",
            expatriate_rate,
            Applicability.EXPATRIATES,
        ),
    ]

    def fdfp(code: str, name: str, key: str) -> PayrollLevyRule:
        return PayrollLevyRule(
            code=code,
            name=name,
            authority=FDFP,
            base_categories=ALL_CASH,
            rate_ppm=setting_int(values, key),
            rounding=HALF_UP,
            due=employer_taxes_due,
            source="company-settings",
            liability_account="fdfp_payable",
            expense_account="payroll_expense_fdfp",
        )

    return CountryRuleSet(
        id="CI-2026.1",
        country="CI",
        currency=CURRENCY,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        tax_year_start_month=1,
        frequencies=frozenset({PayFrequency.MONTHLY}),
        status=RuleSetStatus.ACTIVE,
        approval=APPROVAL,
        sources=SOURCES,
        income_tax=IncomeTaxRule(
            code="ITS",
            name="Impôt sur les traitements et salaires (ITS)",
            authority=DGI,
            method=TaxMethod.PER_PERIOD,
            # Gross salary, with no 20% abatement since 2024.
            taxable_categories=ALL_CASH,
            bands=(
                TaxBand(money("75,000", CURRENCY), 0),
                TaxBand(money("240,000", CURRENCY), ppm("16")),
                TaxBand(money("800,000", CURRENCY), ppm("21")),
                TaxBand(money("2,400,000", CURRENCY), ppm("24")),
                TaxBand(money("8,000,000", CURRENCY), ppm("28")),
                TaxBand(None, ppm("32")),
            ),
            band_rounding=BandRounding.TOTAL,
            rounding=HALF_UP,
            due=due(setting_int(values, "its_due_day")),
            source="ci-its",
            liability_account="its_payable",
            # One share is two half-shares; at most five shares count, so
            # the reduction is at most 8 x 5,500 = XOF 44,000 a month.
            credits=(
                FamilySharesCredit(
                    code="RICF",
                    amount_per_half_share_minor=money("5,500", CURRENCY),
                    base_half_shares=2,
                    max_half_shares=10,
                    source="ci-its",
                ),
            ),
        ),
        contributions=tuple(contributions),
        payroll_levies=(
            fdfp("FDFP-APPRENTICESHIP", "Apprenticeship tax (FDFP)", "apprenticeship_tax_rate"),
            fdfp(
                "FDFP-TRAINING",
                "Continuing-training tax (FDFP)",
                "continuing_training_rate",
            ),
        ),
    )


TEMPLATE = RuleSetTemplate(
    id="CI-2026.1",
    country="CI",
    effective_from=date(2026, 1, 1),
    effective_to=None,
    settings=SETTINGS,
    build=build,
    summary=__doc__ or "",
)
