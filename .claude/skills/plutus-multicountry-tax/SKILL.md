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
A country's rules are used only once approved, on one of two bases (`ApprovalBasis` in `app/compliance/engine/rules.py`):
- **Adviser-reviewed:** a qualified reviewer approves official source references, test vectors reconcile to expected results, accounting postings and returns are validated, effective-dated history is preserved, and the release checklist is signed off.
- **Owner-approved:** the product owner approves the drafted rules from cited sources, official or secondary, as Plutus Technologies did for The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire payroll on 27 October 2026. Only figures the sources settle are built in; a conflicting or unknown figure becomes a Tax Setting (`SettingSpec`) whose options are values a source gave, and payroll is refused until the organisation enters it. Never fill one in with a guess.

## Where things are in this repository
- Nigeria: `app/compliance/models.py` (`RuleVersion`), `app/compliance/versions/` (one module per approved version) and `app/compliance/resolver.py`. The payroll engine and `GET /api/v1/compliance/current-rules` read rules only through `resolve_rule_version`.
- Other countries: `app/compliance/multicountry.py` holds the country catalogue and the fail-closed `require_configured_country`. `GET /api/v1/compliance/countries` (in `app/api/v1/compliance.py`) exposes the catalogue. All six are `active` for payroll; the five other countries' rules matrices, with sources and the questions still open for an adviser, are in `docs/countries/`. Their VAT and withholding tax aren't approved.
- An organisation's country: `organisations.country_code`. Any catalogued country can be chosen and its currency applies at once; payroll and statutory tax run only where `payroll_available` (status `active` plus an encoded rule version). `app/services/jurisdiction.py` resolves rules and currency (`rules_for_organisation`, `organisation_currency`, `payroll_available`). Never hard-code `"NG"` or `"NGN"` in a caller: PDFs and exports take `organisation.currency`, and `money()` in `app/services/report_export.py` writes any currency's decimal places.
- Country-neutral payroll engine: `app/compliance/engine/`. `rules.py` is the typed `CountryRuleSet` (contributions, income tax, payroll levies, due rules, sources, approval) with `structural_problems` and `activation_problems`; `calculate.py` is the pure `calculate_payslip` and `calculate_payroll_levies`; `postings.py` builds balanced postings; `countries/` holds the five approved rule sets, one module each, as `RuleSetTemplate`s (`settings.py`) that build a `CountryRuleSet` from the organisation's Tax Settings; `registry.py` holds `REGISTERED_RULE_SETS` and `resolve_rule_set(country, date, settings=...)`, the only way a pay run may get a country's rules (it raises `MissingTaxSettingsError` until every setting is entered). `indirect_tax.py` is the one calculator for VAT and other transaction taxes (`calculate_indirect_tax`: itemised components, compounding, zero-rated, exempt and out-of-scope supplies); a transaction gets its rates only through `resolve_indirect_tax_rule_set`, behind the same release gate (`approval_problems`). Don't add a second transaction-tax calculator. Write a country's rule set only from approved figures, cite a source on every rule (an official one on the adviser-reviewed basis), and never register Nigeria: it stays on `RuleVersion` until a deliberate switch-over.
- Tax Settings: `org_tax_settings` (append-only, RLS), `app/services/tax_settings.py` (`settings_on` a period end; `enter_settings` refuses a date a locked pay run covers) and `app/api/v1/tax_settings.py` (`GET` for admin, payroll manager, accountant and auditor; `POST` admin only, audited as `tax_settings.update`). Engine pay runs get their rules through `engine_payroll.rules_and_settings_for` and record the settings in the payslip's derivation.
- Pay runs on the engine (Part 3, stage 2a): `uses_engine` (`app/services/jurisdiction.py`) sends every country but Nigeria to `_process_engine_payslip` in `app/services/payroll.py`, and the engine-specific work is in `app/services/engine_payroll.py`.
  - Lines go to `payslip_statutory_lines`, which is append-only and under RLS.
  - Liabilities use the `country` scheme, with `line_code` and `liability_account`.
  - The year to date is summed from `derivation.engine_period` over locked runs.
  - Keep Nigeria's path untouched.
  - The payslip PDF, payroll reports (including `GET /reports/statutory-summary`), tax certificate, disbursement file and payroll analytics show an engine payslip's lines in the organisation's currency (stage 2b). `is_engine_payslip` tells the two kinds apart.
  - A rule set's id must start with its country code (`KE-2026.1`): analytics finds a country's payslips by that prefix.
- Money helpers: `app/domain/money.py`. `apply_rate_ppm` is the engine's one rounding rule. `minor_units_exponent` knows all six catalogued currencies (RWF and XOF have no minor units).
- Design target, rule lifecycle and release gates: `docs/architecture/multicountry-tax.md`.
- Tests: `tests/unit/test_multicountry_tax_engine.py`, `tests/unit/test_tax_engine_calculation.py` and `tests/unit/test_tax_engine_rules.py`, `tests/unit/test_indirect_tax.py` (fictional figures only, built with `tests/unit/tax_engine_fixtures.py`), `tests/integration/test_api_compliance.py`, `tests/integration/test_engine_pay_runs.py` (pay runs against a fictional rule set registered for the test only), `tests/unit/test_country_rules.py` (each country's rules against hand-worked payslips), `tests/integration/test_api_tax_settings.py`, and the Nigerian golden tests in `tests/golden/`, including `test_tax_engine_nigeria_parity.py`, which proves the engine reproduces Nigeria's payroll to the kobo.
