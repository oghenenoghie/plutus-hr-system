"""The country-neutral payroll engine: typed, effective-dated country rule
sets (rules), the pure calculation over them (calculate), their postings
(postings), and the gate that hands out only approved rule sets (registry).

See docs/architecture/multicountry-tax.md, Part 3.
"""

from app.compliance.engine.calculate import (
    Earning,
    EmployeeFacts,
    IncomeTaxWorking,
    LineKind,
    MissingEmployeeDataError,
    PayslipInputs,
    PayslipResult,
    StatutoryLine,
    YearToDate,
    calculate_payroll_levies,
    calculate_payslip,
)
from app.compliance.engine.postings import build_levy_postings, build_payslip_postings
from app.compliance.engine.registry import (
    REGISTERED_RULE_SETS,
    registry_problems,
    resolve_rule_set,
)
from app.compliance.engine.rules import (
    CountryRuleSet,
    RuleSetError,
    RuleSetStatus,
    activation_problems,
    require_active,
    structural_problems,
)

__all__ = [
    "REGISTERED_RULE_SETS",
    "CountryRuleSet",
    "Earning",
    "EmployeeFacts",
    "IncomeTaxWorking",
    "LineKind",
    "MissingEmployeeDataError",
    "PayslipInputs",
    "PayslipResult",
    "RuleSetError",
    "RuleSetStatus",
    "StatutoryLine",
    "YearToDate",
    "activation_problems",
    "build_levy_postings",
    "build_payslip_postings",
    "calculate_payroll_levies",
    "calculate_payslip",
    "registry_problems",
    "require_active",
    "resolve_rule_set",
    "structural_problems",
]
