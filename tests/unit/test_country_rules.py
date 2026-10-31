"""The five countries' approved payroll rules (app/compliance/engine/countries/),
each checked against a payslip worked out by hand from the figures in its
module and docs/countries/. The Tax Settings each example uses are written
out in the test, as an organisation would enter them."""

from datetime import date

import pytest

from app.compliance.engine.calculate import (
    EmployeeFacts,
    MissingEmployeeDataError,
    PayslipResult,
    calculate_payroll_levies,
    calculate_payslip,
)
from app.compliance.engine.countries import TEMPLATES, ci, gh, gm, ke, rw
from app.compliance.engine.registry import (
    MissingTaxSettingsError,
    resolve_rule_set,
)
from app.compliance.engine.rules import EarningCategory, require_active
from app.compliance.engine.settings import (
    RuleSetTemplate,
    SettingError,
    SettingKind,
    SettingSpec,
    display_setting,
    entry_text,
    missing_settings,
    parse_setting,
    settings_problems,
)
from app.compliance.multicountry import TaxConfigurationError, get_country_profile
from app.domain.payroll.frequency import PayFrequency
from tests.unit.tax_engine_fixtures import pay

BASIC = EarningCategory.BASIC
HOUSING = EarningCategory.HOUSING
TRANSPORT = EarningCategory.TRANSPORT


def entered(template: RuleSetTemplate, **values: str) -> dict[str, str]:
    """Settings as a person enters them, in stored form."""
    currency = get_country_profile(template.country).currency
    stored: dict[str, str] = {}
    for key, value in values.items():
        spec = template.spec(key)
        assert spec is not None, key
        stored[key] = parse_setting(spec, value, currency=currency)
    return stored


def payslip(
    template: RuleSetTemplate,
    settings: dict[str, str],
    *earnings: tuple[EarningCategory, int],
    period_end: date,
    facts: EmployeeFacts | None = None,
) -> PayslipResult:
    rule_set = resolve_rule_set(template.country, period_end, settings=settings)
    return calculate_payslip(rule_set, pay(*earnings, period_end=period_end, facts=facts))


def amounts(result: PayslipResult) -> dict[str, int]:
    return {line.code: line.amount_minor for line in result.lines}


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_every_template_is_well_formed_and_approved_by_plutus(template: RuleSetTemplate) -> None:
    assert settings_problems(template) == []
    built = template.build(template.preview_values())
    require_active(built)
    assert built.approval.approved_by == "Plutus Technologies"
    assert built.approval.basis.value == "owner_approved"
    assert built.currency == get_country_profile(template.country).currency
    # Whatever an organisation enters is its own, and is labelled so.
    assert "company-settings" in {source.id for source in built.sources}


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_payroll_is_refused_until_every_setting_is_entered(template: RuleSetTemplate) -> None:
    with pytest.raises(MissingTaxSettingsError, match="Tax Settings") as refused:
        resolve_rule_set(template.country, template.effective_from, settings={})
    required = {spec.key for spec in missing_settings(template.settings, {})}
    assert {spec.key for spec in refused.value.missing} == required


# Kenya: KES. NSSF 6% to KES 108,000; SHIF 2.75%, at least KES 300; Housing
# Levy 1.5% each side; NITA KES 50; PAYE bands with KES 2,400 personal relief.
KENYA = entered(ke.TEMPLATE, nssf_tax_deductible="yes", nita_applies="yes", nita_due_day="5")
MARCH_2026 = date(2026, 3, 31)


def test_kenya_on_100000_a_month() -> None:
    result = payslip(ke.TEMPLATE, KENYA, (BASIC, 10_000_000), period_end=MARCH_2026)
    # Deductible before PAYE: NSSF 6,000 (pension cap 30,000), SHIF 2,750,
    # Housing Levy 1,500, so taxable 89,750. PAYE: 10% x 24,000 = 2,400;
    # 25% x 8,333 = 2,083.25; 30% x 57,417 = 17,225.10; less 2,400 relief
    # = 19,308.35.
    assert amounts(result) == {
        "NSSF": 600_000,
        "NSSF-ER": 600_000,
        "SHIF": 275_000,
        "HOUSING-LEVY": 150_000,
        "HOUSING-LEVY-ER": 150_000,
        "NITA": 5_000,
        "PAYE": 1_930_835,
    }
    assert result.income_tax.taxable_income_minor == 8_975_000
    assert result.net_pay_minor == 7_044_165
    assert result.line("NITA").due_date == date(2026, 4, 5)
    assert result.line("PAYE").due_date == date(2026, 4, 9)


def test_kenya_settings_change_what_comes_off_before_paye_and_the_nita_levy() -> None:
    settings = KENYA | entered(ke.TEMPLATE, nssf_tax_deductible="no", nita_applies="no")
    result = payslip(ke.TEMPLATE, settings, (BASIC, 10_000_000), period_end=MARCH_2026)
    # Taxable 100,000 - 2,750 - 1,500 = 95,750: 2,400 + 2,083.25 + 30% x
    # 63,417 = 19,025.10, less 2,400 = 21,108.35. No NITA line.
    assert "NITA" not in amounts(result)
    assert result.line("PAYE").amount_minor == 2_110_835
    # The NITA due day isn't asked for once the levy doesn't apply.
    assert (
        missing_settings(ke.TEMPLATE.settings, {"nssf_tax_deductible": "no", "nita_applies": "no"})
        == []
    )


def test_kenya_nssf_stops_at_the_upper_limit_and_shif_has_a_floor() -> None:
    high = payslip(ke.TEMPLATE, KENYA, (BASIC, 20_000_000), period_end=MARCH_2026)
    assert high.line("NSSF").amount_minor == 648_000  # 6% of 108,000
    low = payslip(ke.TEMPLATE, KENYA, (BASIC, 1_000_000), period_end=MARCH_2026)
    assert low.line("SHIF").amount_minor == 30_000  # 2.75% of 10,000 is 275


def test_kenya_starts_with_the_nssf_year_4_rates() -> None:
    with pytest.raises(TaxConfigurationError, match="No approved Kenya payroll rules"):
        resolve_rule_set("KE", date(2026, 1, 31), settings=KENYA)


# The Gambia: GMD. PAYE 0% to GMD 3,000 a month, then 5% to 25% with the
# monthly limits the organisation enters (here GRA's annual bands / 12);
# NPF 5% and 10% of basic; IICF 1% capped at GMD 15.
GAMBIA = entered(
    gm.TEMPLATE,
    paye_5_band_limit="3833.33",
    paye_10_band_limit="4666.67",
    paye_15_band_limit="5500",
    paye_20_band_limit="6333.33",
    npf_tax_deductible="no",
    iicf_base="fixed_pay",
    iicf_due_day="15",
    fps_applies="no",
)


def test_the_gambia_on_12000_a_month() -> None:
    result = payslip(
        gm.TEMPLATE, GAMBIA, (BASIC, 1_000_000), (HOUSING, 200_000), period_end=MARCH_2026
    )
    # PAYE on 12,000: 5% x 833.33 + 10% x 833.34 + 15% x 833.33 + 20% x
    # 833.33 + 25% x 5,666.67 = 41.6665 + 83.334 + 124.9995 + 166.666 +
    # 1,416.6675 = 1,833.3335, rounded once to 1,833.33.
    assert amounts(result) == {
        "NPF": 50_000,
        "NPF-ER": 100_000,
        "IICF": 1_500,  # 1% of 12,000 is 120, capped at 15
        "PAYE": 183_333,
    }
    assert result.net_pay_minor == 966_667


def test_the_gambia_settings_add_npf_relief_and_the_federated_pension_scheme() -> None:
    settings = GAMBIA | entered(
        gm.TEMPLATE, npf_tax_deductible="yes", fps_applies="yes", fps_due_day="20"
    )
    result = payslip(
        gm.TEMPLATE, settings, (BASIC, 1_000_000), (HOUSING, 200_000), period_end=MARCH_2026
    )
    # Taxable 11,500: the top slice is 25% x 5,166.67 = 1,291.6675, so
    # 1,708.3335 in all. FPS is 15% of basic plus fixed allowances.
    assert result.line("PAYE").amount_minor == 170_833
    assert result.line("FPS").amount_minor == 180_000
    assert result.line("FPS").due_date == date(2026, 4, 20)


def test_the_gambia_refuses_band_limits_that_dont_rise() -> None:
    settings = GAMBIA | entered(gm.TEMPLATE, paye_5_band_limit="5000")
    with pytest.raises(TaxConfigurationError, match="Tax Settings don't make usable payroll"):
        resolve_rule_set("GM", MARCH_2026, settings=settings)


# Ghana: GHS, from 1 September 2026. PAYE 0% to GHS 588, then 5%, 10%,
# 17.5%, 25%, 30% and 35% with the monthly limits entered; social security
# 5.5% employee, 8% employer to SSNIT and 5% employer to Tier 2, on basic.
GHANA = entered(
    gh.TEMPLATE,
    paye_5_band_limit="668",
    paye_10_band_limit="768",
    paye_17_5_band_limit="3668",
    paye_25_band_limit="19668",
    paye_30_band_limit="50000",
    ssnit_tax_deductible="yes",
    ssnit_monthly_ceiling="69000",
    ssnit_due_day="15",
    tier2_due_day="14",
)
SEPTEMBER_2026 = date(2026, 9, 30)


def test_ghana_on_6000_a_month() -> None:
    result = payslip(
        gh.TEMPLATE, GHANA, (BASIC, 500_000), (HOUSING, 100_000), period_end=SEPTEMBER_2026
    )
    # Taxable 6,000 - 275 = 5,725. PAYE: 5% x 80 = 4; 10% x 100 = 10;
    # 17.5% x 2,900 = 507.50; 25% x 2,057 = 514.25; 1,035.75 in all.
    assert amounts(result) == {
        "SSNIT": 27_500,
        "SSNIT-ER": 40_000,
        "TIER2-ER": 25_000,
        "PAYE": 103_575,
    }
    assert result.net_pay_minor == 468_925
    # SSNIT is owed 13.5% of basic, the Tier 2 trustee 5%.
    assert result.line("SSNIT").amount_minor + result.line("SSNIT-ER").amount_minor == 67_500
    assert result.line("TIER2-ER").due_date == date(2026, 10, 14)


def test_ghana_social_security_stops_at_the_ceiling_entered() -> None:
    settings = GHANA | entered(gh.TEMPLATE, ssnit_monthly_ceiling="5083.33")
    result = payslip(gh.TEMPLATE, settings, (BASIC, 10_000_000), period_end=SEPTEMBER_2026)
    assert result.line("SSNIT").amount_minor == 27_958  # 5.5% of 5,083.33 = 279.58315


def test_ghana_periods_before_act_1178_are_refused() -> None:
    with pytest.raises(TaxConfigurationError, match="No approved Ghana payroll rules"):
        resolve_rule_set("GH", date(2026, 8, 31), settings=GHANA)


# Rwanda: RWF, no minor unit. PAYE 0/10/20/30% at 60,000, 100,000 and
# 200,000; RSSB pension 6% each side on gross; maternity 0.3%; CBHI 0.5% of
# net pay.
RWANDA = entered(
    rw.TEMPLATE,
    rssb_tax_deductible="no",
    maternity_employee_rate="0.3",
    maternity_base="all_cash",
    occupational_hazards_rate="2",
    occupational_hazards_base="all_cash",
)


def test_rwanda_on_350000_a_month() -> None:
    result = payslip(
        rw.TEMPLATE, RWANDA, (BASIC, 300_000), (TRANSPORT, 50_000), period_end=MARCH_2026
    )
    # PAYE on 350,000: 4,000 + 20,000 + 45,000 = 69,000. Net before CBHI:
    # 350,000 - 21,000 - 1,050 - 69,000 = 258,950; CBHI 0.5% = 1,294.75,
    # rounded to 1,295.
    assert amounts(result) == {
        "RSSB-PENSION": 21_000,
        "RSSB-PENSION-ER": 21_000,
        "RSSB-MATERNITY": 1_050,
        "RSSB-MATERNITY-ER": 1_050,
        "RSSB-HAZARDS-ER": 7_000,
        "PAYE": 69_000,
        "CBHI": 1_295,
    }
    assert result.net_pay_minor == 257_655
    assert result.line("CBHI").due_date == date(2026, 4, 15)


def test_rwanda_settings_take_rssb_off_before_paye_and_drop_the_employee_maternity_line() -> None:
    settings = RWANDA | entered(rw.TEMPLATE, rssb_tax_deductible="yes", maternity_employee_rate="0")
    result = payslip(
        rw.TEMPLATE, settings, (BASIC, 300_000), (TRANSPORT, 50_000), period_end=MARCH_2026
    )
    # Taxable 350,000 - 21,000 = 329,000: 4,000 + 20,000 + 30% x 129,000.
    assert "RSSB-MATERNITY" not in amounts(result)
    assert result.line("PAYE").amount_minor == 62_700


# From 2027 the pension is 14% in all (Presidential Order No. 086/01 of 2024);
# the organisation enters the employee's share and the employer pays the rest.
JANUARY_2027 = date(2027, 1, 31)


def test_rwanda_2027_needs_only_the_pension_share_on_top_of_2026s_settings() -> None:
    with pytest.raises(MissingTaxSettingsError) as refused:
        resolve_rule_set("RW", JANUARY_2027, settings=RWANDA)
    assert [spec.key for spec in refused.value.missing] == ["pension_employee_rate_2027"]


@pytest.mark.parametrize(
    ("share", "employee", "employer"),
    [("7", 24_500, 24_500), ("6", 21_000, 28_000)],
)
def test_rwanda_2027_divides_the_14_percent_pension_as_entered(
    share: str, employee: int, employer: int
) -> None:
    settings = RWANDA | entered(rw.TEMPLATE_2027, pension_employee_rate_2027=share)
    result = payslip(
        rw.TEMPLATE_2027, settings, (BASIC, 300_000), (TRANSPORT, 50_000), period_end=JANUARY_2027
    )
    assert result.rule_set_id == "RW-2027.1"
    lines = amounts(result)
    assert (lines["RSSB-PENSION"], lines["RSSB-PENSION-ER"]) == (employee, employer)
    assert employee + employer == 49_000  # 14% of 350,000
    # PAYE and the other lines are as in 2026; CBHI is 0.5% of what's left.
    assert lines["PAYE"] == 69_000
    net_before_cbhi = 350_000 - employee - 1_050 - 69_000
    assert lines["CBHI"] == (net_before_cbhi * 5 + 500) // 1000
    assert result.net_pay_minor == net_before_cbhi - lines["CBHI"]


def test_rwanda_2027_on_7_percent_each_worked_by_hand() -> None:
    settings = RWANDA | entered(rw.TEMPLATE_2027, pension_employee_rate_2027="7")
    result = payslip(
        rw.TEMPLATE_2027, settings, (BASIC, 300_000), (TRANSPORT, 50_000), period_end=JANUARY_2027
    )
    # 350,000 - 24,500 - 1,050 - 69,000 = 255,450; CBHI 0.5% = 1,277.25,
    # rounded to 1,277.
    assert result.line("CBHI").amount_minor == 1_277
    assert result.net_pay_minor == 254_173


@pytest.mark.parametrize(("share", "codes"), [("14", {"RSSB-PENSION"}), ("0", {"RSSB-PENSION-ER"})])
def test_rwanda_2027_leaves_out_a_side_that_pays_nothing(share: str, codes: set[str]) -> None:
    settings = RWANDA | entered(rw.TEMPLATE_2027, pension_employee_rate_2027=share)
    result = payslip(rw.TEMPLATE_2027, settings, (BASIC, 350_000), period_end=JANUARY_2027)
    assert {code for code in amounts(result) if code.startswith("RSSB-PENSION")} == codes
    assert (
        sum(amount for code, amount in amounts(result).items() if code.startswith("RSSB-PENSION"))
        == 49_000
    )


def test_rwanda_2027_share_cant_exceed_the_14_percent() -> None:
    with pytest.raises(SettingError, match="between 0% and 14%"):
        parse_setting(rw.PENSION_SHARE_2027, "15", currency="RWF")


def test_rwanda_2028_is_refused_until_the_16_percent_pension_is_encoded() -> None:
    settings = RWANDA | entered(rw.TEMPLATE_2027, pension_employee_rate_2027="7")
    assert resolve_rule_set("RW", date(2027, 12, 31), settings=settings).id == "RW-2027.1"
    with pytest.raises(TaxConfigurationError, match="No approved Rwanda payroll rules"):
        resolve_rule_set("RW", date(2028, 1, 31), settings=settings)


# Côte d'Ivoire: XOF, no minor unit. ITS 0/16/21/24/28/32%, less XOF 5,500
# per half-share above one share; CNPS retirement 6.3% and 7.7%; CMU XOF
# 1,000; training levies on the run.
COTE_DIVOIRE = entered(
    ci.TEMPLATE,
    cnps_base="all_cash",
    cnps_retirement_ceiling="1647315",
    family_benefits_rate="5",
    cnps_other_ceiling="70000",
    work_accident_rate="2",
    cmu_employee_amount="500",
    apprenticeship_tax_rate="0.4",
    continuing_training_rate="1.2",
    employer_salary_tax="2.8_12",
    its_due_day="15",
    cnps_due_day="15",
    employer_taxes_due_day="15",
)
LOCAL_COUPLE_ONE_CHILD = EmployeeFacts(half_shares=5, is_expatriate=False)


def test_cote_divoire_on_500000_a_month() -> None:
    result = payslip(
        ci.TEMPLATE,
        COTE_DIVOIRE,
        (BASIC, 500_000),
        period_end=MARCH_2026,
        facts=LOCAL_COUPLE_ONE_CHILD,
    )
    # ITS: 16% x 165,000 = 26,400; 21% x 260,000 = 54,600; 81,000, less
    # 3 half-shares above one share x 5,500 = 16,500, so 64,500.
    assert amounts(result) == {
        "CNPS-RETIREMENT": 31_500,
        "CNPS-RETIREMENT-ER": 38_500,
        "CNPS-FAMILY-ER": 3_500,  # 5% of the 70,000 ceiling
        "CNPS-MATERNITY-ER": 525,
        "CNPS-ACCIDENT-ER": 1_400,
        "CMU": 500,
        "CMU-ER": 500,
        "SALARY-TAX-LOCAL-ER": 14_000,
        "ITS": 64_500,
    }
    assert result.net_pay_minor == 500_000 - 31_500 - 500 - 64_500

    rule_set = resolve_rule_set("CI", MARCH_2026, settings=COTE_DIVOIRE)
    levies = calculate_payroll_levies(
        rule_set,
        period_end=MARCH_2026,
        frequency=PayFrequency.MONTHLY,
        earnings_by_employee=[result.inputs.earnings, result.inputs.earnings],
    )
    assert {line.code: line.amount_minor for line in levies} == {
        "FDFP-APPRENTICESHIP": 4_000,  # 0.4% of the run's 1,000,000
        "FDFP-TRAINING": 12_000,
    }


def test_cote_divoire_cnps_is_charged_on_the_base_entered() -> None:
    settings = COTE_DIVOIRE | entered(ci.TEMPLATE, cnps_base="basic")
    result = payslip(
        ci.TEMPLATE,
        settings,
        (BASIC, 400_000),
        (HOUSING, 100_000),
        period_end=MARCH_2026,
        facts=LOCAL_COUPLE_ONE_CHILD,
    )
    assert result.line("CNPS-RETIREMENT").amount_minor == 25_200  # 6.3% of basic only
    assert result.line("ITS").amount_minor == 64_500  # still on gross pay


def test_cote_divoire_family_reduction_is_capped_at_five_shares() -> None:
    large_family = EmployeeFacts(half_shares=14, is_expatriate=False)
    result = payslip(
        ci.TEMPLATE, COTE_DIVOIRE, (BASIC, 500_000), period_end=MARCH_2026, facts=large_family
    )
    assert result.line("ITS").amount_minor == 81_000 - 44_000


def test_cote_divoire_charges_the_expatriate_rate_and_needs_the_employees_facts() -> None:
    expatriate = EmployeeFacts(half_shares=2, is_expatriate=True)
    result = payslip(
        ci.TEMPLATE, COTE_DIVOIRE, (BASIC, 500_000), period_end=MARCH_2026, facts=expatriate
    )
    assert result.line("SALARY-TAX-EXPAT-ER").amount_minor == 60_000
    assert "SALARY-TAX-LOCAL-ER" not in amounts(result)

    with pytest.raises(MissingEmployeeDataError, match="expatriate"):
        payslip(
            ci.TEMPLATE,
            COTE_DIVOIRE,
            (BASIC, 500_000),
            period_end=MARCH_2026,
            facts=EmployeeFacts(half_shares=2),
        )
    with pytest.raises(MissingEmployeeDataError, match="family shares"):
        payslip(
            ci.TEMPLATE,
            COTE_DIVOIRE,
            (BASIC, 500_000),
            period_end=MARCH_2026,
            facts=EmployeeFacts(is_expatriate=False),
        )


@pytest.mark.parametrize(("share", "lines"), [("0", {"CMU-ER": 1_000}), ("1000", {"CMU": 1_000})])
def test_cote_divoire_cmu_is_split_as_entered(share: str, lines: dict[str, int]) -> None:
    settings = COTE_DIVOIRE | entered(ci.TEMPLATE, cmu_employee_amount=share)
    result = payslip(
        ci.TEMPLATE, settings, (BASIC, 500_000), period_end=MARCH_2026, facts=LOCAL_COUPLE_ONE_CHILD
    )
    assert {code: amount for code, amount in amounts(result).items() if "CMU" in code} == lines


def test_cote_divoire_cmu_share_cant_exceed_the_contribution() -> None:
    spec = ci.TEMPLATE.spec("cmu_employee_amount")
    assert spec is not None
    with pytest.raises(SettingError, match="between"):
        parse_setting(spec, "1001", currency="XOF")


@pytest.mark.parametrize(
    ("kind", "currency", "entered_value", "stored", "shown"),
    [
        (SettingKind.PERCENT, "KES", "2.75", "27500", "2.75%"),
        (SettingKind.PERCENT, "KES", "5%", "50000", "5%"),
        (SettingKind.AMOUNT, "GHS", "5,083.33", "508333", "5,083.33 GHS"),
        (SettingKind.AMOUNT, "XOF", "1647315", "1647315", "1,647,315 XOF"),
        (SettingKind.DAY, "KES", "15", "15", "15"),
    ],
)
def test_settings_are_stored_in_fixed_units_and_read_back_as_entered(
    kind: SettingKind, currency: str, entered_value: str, stored: str, shown: str
) -> None:
    spec = SettingSpec(key="k", label="A figure", help="Why", kind=kind)
    assert parse_setting(spec, entered_value, currency=currency) == stored
    assert display_setting(spec, stored, currency=currency) == shown
    assert parse_setting(spec, entry_text(spec, stored, currency=currency), currency=currency) == (
        stored
    )


@pytest.mark.parametrize(
    ("kind", "currency", "value"),
    [
        (SettingKind.PERCENT, "KES", "2.12345"),  # finer than a part per million
        (SettingKind.PERCENT, "KES", "101"),
        (SettingKind.AMOUNT, "XOF", "10.5"),  # XOF has no minor unit
        (SettingKind.AMOUNT, "GHS", "-1"),
        (SettingKind.DAY, "KES", "29"),  # not in every month
        (SettingKind.DAY, "KES", "fifteen"),
    ],
)
def test_settings_refuse_values_that_dont_fit(kind: SettingKind, currency: str, value: str) -> None:
    spec = SettingSpec(key="k", label="A figure", help="Why", kind=kind)
    with pytest.raises(SettingError):
        parse_setting(spec, value, currency=currency)


def test_a_choice_takes_only_its_options() -> None:
    spec = ke.TEMPLATE.spec("nita_applies")
    assert spec is not None
    assert parse_setting(spec, "yes", currency="KES") == "yes"
    with pytest.raises(SettingError, match="choose one of"):
        parse_setting(spec, "maybe", currency="KES")
