"""The country-neutral tax engine: typed, effective-dated country rule sets
(rules), the pure payroll calculation over them (calculate), their postings
(postings), VAT and other transaction taxes (indirect_tax), and the gate that
hands out only approved rule sets (registry).

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
from app.compliance.engine.indirect_tax import (
    IndirectTaxComponent,
    IndirectTaxResult,
    IndirectTaxRuleSet,
    TaxTreatment,
    calculate_indirect_tax,
)
from app.compliance.engine.postings import build_levy_postings, build_payslip_postings
from app.compliance.engine.registry import (
    REGISTERED_INDIRECT_TAX_RULE_SETS,
    REGISTERED_RULE_SETS,
    indirect_registry_problems,
    registry_problems,
    resolve_indirect_tax_rule_set,
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
    "REGISTERED_INDIRECT_TAX_RULE_SETS",
    "REGISTERED_RULE_SETS",
    "CountryRuleSet",
    "Earning",
    "EmployeeFacts",
    "IncomeTaxWorking",
    "IndirectTaxComponent",
    "IndirectTaxResult",
    "IndirectTaxRuleSet",
    "LineKind",
    "MissingEmployeeDataError",
    "PayslipInputs",
    "PayslipResult",
    "RuleSetError",
    "RuleSetStatus",
    "StatutoryLine",
    "TaxTreatment",
    "YearToDate",
    "activation_problems",
    "build_levy_postings",
    "build_payslip_postings",
    "calculate_indirect_tax",
    "calculate_payroll_levies",
    "calculate_payslip",
    "indirect_registry_problems",
    "registry_problems",
    "require_active",
    "resolve_indirect_tax_rule_set",
    "resolve_rule_set",
    "structural_problems",
]
