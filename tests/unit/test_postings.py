from app.domain.payroll.payslip import PayslipComputation
from app.domain.payroll.postings import build_payslip_postings


def test_postings_always_balance() -> None:
    computation = PayslipComputation(
        gross_minor=500_000_00,
        pensionable_pay_minor=500_000_00,
        pension_employee_minor=40_000_00,
        pension_employer_minor=50_000_00,
        nhf_minor=7_500_00,
        cumulative_rent_relief_minor=3_333_33,
        cumulative_chargeable_income_minor=419_166_67,
        paye_minor=0,
        net_pay_minor=452_500_00,
    )
    postings = build_payslip_postings(computation)

    total_debit = sum(p.debit_minor for p in postings)
    total_credit = sum(p.credit_minor for p in postings)
    assert total_debit == total_credit
    assert total_debit == computation.gross_minor + computation.pension_employer_minor


def test_postings_omit_zero_lines_but_stay_balanced() -> None:
    computation = PayslipComputation(
        gross_minor=100_000_00,
        pensionable_pay_minor=0,
        pension_employee_minor=0,
        pension_employer_minor=0,
        nhf_minor=0,
        cumulative_rent_relief_minor=0,
        cumulative_chargeable_income_minor=100_000_00,
        paye_minor=0,
        net_pay_minor=100_000_00,
    )
    postings = build_payslip_postings(computation)

    accounts = {p.account for p in postings}
    assert "pension_payable" not in accounts
    assert "nhf_payable" not in accounts
    assert "paye_payable" not in accounts

    assert sum(p.debit_minor for p in postings) == sum(p.credit_minor for p in postings)
