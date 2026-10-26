# Plutus Multi-Country Tax Engine

## Purpose

This folder establishes a shared tax-engine foundation for the following jurisdictions:

- Nigeria (NG)
- The Gambia (GM)
- Ghana (GH)
- Rwanda (RW)
- Côte d'Ivoire (CI)
- Kenya (KE)

The accounting ledger, invoice model and payroll workflows should remain shared. Country-specific tax logic should be supplied through versioned jurisdiction rules and adapters.

## Current implementation

`src/multi-country/tax-engine.ts` provides:

- Supported-country and currency metadata.
- Tax rule types with country, category, approval status, source, version and effective dates.
- Rule lookup that blocks draft/retired rules and out-of-period calculations.
- VAT calculations using integer minor units and basis-point rates.
- An intentionally empty initial rule registry. No unverified rate is activated.

This is a foundation, not a complete tax-compliance implementation. It does not yet implement PAYE bands, corporate tax adjustments, withholding tax, social contributions, tax returns, registration thresholds, product taxability, exemptions, or electronic filing.

## Integration plan

1. Inspect the existing Plutus Nigeria tax implementation and preserve its behavior with regression tests.
2. Add database migrations for jurisdictions, tax rules, rule versions, source evidence, approvals and calculation audit records.
3. Add a server-side rule repository. Do not treat client-provided rates as authoritative.
4. Add country selection at the legal-entity/company level, with permission checks and an audit trail.
5. Route each tax calculation to a jurisdiction adapter and effective-dated approved rules.
6. Persist the rule ID and version used for every posted transaction and filed return.
7. Add jurisdiction-specific modules for VAT, payroll/PAYE, corporate income tax, withholding tax and statutory contributions.
8. Validate every rule against the relevant official tax authority and legislation. Have a qualified local tax professional review before production activation.

## Rule governance

- New or changed rules start in `draft`.
- A permitted compliance administrator records the official source, verification date, effective date and review evidence.
- An authorized approver activates the rule.
- Never overwrite a rule used by posted transactions; create a new version with the correct effective date.
- Keep historical calculations reproducible even after tax rules change.
- If a rule is missing, unapproved or outside its effective period, fail closed and explain the reason. Do not guess a tax rate.
- Country changes must not silently rewrite posted journals, historic invoices or filed returns.

## Money and rounding

The calculator accepts integer minor units. Verify each currency's minor-unit precision in the application's currency library; currencies do not all use two decimal places. Country-specific statutory rounding rules must be implemented and tested before production.

## Minimum test coverage

- Approved rule applies on its start date and end date.
- Rule is rejected before or after its effective period.
- Draft and retired rules are rejected.
- Missing country/rule configuration fails closed.
- VAT-exclusive and VAT-inclusive calculations.
- Zero rate and rounding boundary cases.
- Currency minor-unit precision.
- Credit notes and reversals through a separate workflow.
- Regression tests for existing Nigerian calculations.
- Tests for each jurisdiction against locally reviewed expected results.

## Security

- Only trusted server-side code may select the authoritative rule for a posted transaction.
- Protect rule changes with role-based permissions and an immutable audit trail.
- Never expose database service-role credentials to the browser.
- Do not allow an ordinary tenant user to approve tax rules for all tenants.
- Separate rule authorship from approval where practical.

## Important

The presence of a country in the supported-country list does not mean its tax module is production-ready. A jurisdiction should be marked production-ready only after its rules, filings, tests and legal review are complete.
