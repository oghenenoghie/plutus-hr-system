---
name: plutus-multicountry-tax
description: Design, implement, review, and test Plutus jurisdiction-aware tax and statutory compliance across Nigeria, The Gambia, Rwanda, Kenya, Ghana, and Côte d’Ivoire. Use for VAT, PAYE, withholding tax, corporate tax, statutory contributions, country settings, tax-rule versioning, tax migrations, or compliance reporting.
---

# Plutus multi-country tax engineering

## Non-negotiable principles
- Read the existing compliance engine and related tests before changing it. Preserve Nigeria behaviour and API compatibility unless an explicit migration plan says otherwise.
- Never invent tax rates, thresholds, filing deadlines, exemptions, statutory contributions, tax authority names, or country-specific account mappings. Verify each statutory parameter against current primary authority guidance and record the source reference and effective dates.
- A supported country profile is not proof that its rules are production-ready. Fail closed when an approved rule set is missing.
- Resolve rules by legal entity, country, tax type, and transaction/pay-period date. Persist rule-version identifiers and calculation snapshots on posted transactions/pay runs.
- Posted/locked historical periods must not be recalculated silently when settings or rates change. Use reversals and adjustments.
- Use integer minor units for money and explicit rate units (ppm or decimal); document rounding mode and inclusive/exclusive tax behaviour.
- Separate VAT, WHT, payroll taxes, employer contributions, corporate income tax, and filing/reporting rules. Do not model all jurisdictions as Nigerian deductions with renamed labels.
- Enforce tenant isolation, authorisation, audit logging, idempotency and least privilege for every mutation.

## Required workflow
1. Map the current implementation, models, endpoints, migrations, frontend screens and tests.
2. Write a country-by-country rules matrix with official sources, effective dates, calculation bases, thresholds, exclusions, rounding, deadlines, and review status.
3. Design typed jurisdiction-neutral interfaces plus country-specific rule modules; avoid country conditionals scattered through business logic.
4. Implement database migrations and backfills that are safe for existing Nigerian tenants.
5. Implement calculations as pure functions with explicit inputs and immutable effective-dated rule versions.
6. Add unit, boundary, property, golden, API, tenant-isolation, migration and regression tests.
7. Add UI states for configured, draft, pending review, active, superseded and blocked/unconfigured rules.
8. Run formatting, static analysis, tests and frontend lint/type checks; report anything not run.

## Release gate
A country may not be labelled production-ready until a qualified reviewer approves official source references, test vectors reconcile to expected results, accounting postings and returns are validated, effective-dated history is preserved, and the release checklist is signed off.

## Where things are in this repository
- Nigeria: `app/compliance/models.py` (`RuleVersion`), `app/compliance/versions/` (one module per approved version) and `app/compliance/resolver.py`. The payroll engine and `GET /api/v1/compliance/current-rules` read rules only through `resolve_rule_version`.
- Other countries: `app/compliance/multicountry.py` holds the country catalogue, `EffectiveRate`, `calculate_percentage_tax` and the fail-closed `require_configured_country`. `GET /api/v1/compliance/countries` (in `app/api/v1/compliance.py`) exposes the catalogue. The five other countries are `draft`; their draft rules matrices, with sources and open questions, are in `docs/countries/`.
- An organisation's country: `organisations.country_code`. `app/services/jurisdiction.py` resolves rules and currency from it (`rules_for_organisation`, `organisation_currency`) and decides which countries can be chosen. Never hard-code `"NG"` in a caller.
- Money helpers: `app/domain/money.py`. `apply_rate_ppm` is the engine's one rounding rule. `minor_units_exponent` knows all six catalogued currencies (RWF and XOF have no minor units).
- Design target, rule lifecycle and release gates: `docs/architecture/multicountry-tax.md`.
- Tests: `tests/unit/test_multicountry_tax_engine.py`, `tests/integration/test_api_compliance.py`, and the Nigerian golden tests in `tests/golden/`.
