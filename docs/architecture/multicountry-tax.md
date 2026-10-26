# Multi-country tax architecture and implementation notes

Status: **foundation, drafts and engine core.** Nigeria is unchanged and is the only country Plutus calculates payroll or statutory tax for. Each organisation has a country (Part 1 below): any of the six can be chosen at sign-up and applies at once, while payroll waits for that country's approved rules. The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire are marked `draft`: their rules are drafted, with sources, in [`docs/countries/`](../countries/README.md) and await review by a tax adviser in each country. No statutory rate for them is encoded, and any attempt to use one fails closed. The country-neutral payroll engine (Part 3, stage 1) is built and reproduces Nigeria's payroll to the kobo, but no other country's rules are encoded in it and pay runs don't use it yet. The rest of this document is the design target that a country must meet before it is enabled.

## What exists today

| Piece | Where |
|---|---|
| Country catalogue: code, currency, tax authority, readiness status | `COUNTRY_PROFILES` in `app/compliance/multicountry.py` |
| VAT and other transaction taxes: itemised components (compounding or on the same base), standard, zero-rated, exempt and out-of-scope supplies, tax-exclusive and single-component tax-inclusive prices, integer minor units, rounding by mode and increment | `calculate_indirect_tax` in `app/compliance/engine/indirect_tax.py`, resolved through `resolve_indirect_tax_rule_set`; `REGISTERED_INDIRECT_TAX_RULE_SETS` is empty |
| Fail-closed guard for any country without approved rules | `require_configured_country` |
| The organisation's country, and the rules and currency that follow from it | `organisations.country_code`; `app/services/jurisdiction.py` |
| Authenticated read-only catalogue | `GET /api/v1/compliance/countries` in `app/api/v1/compliance.py` |
| Public list of countries for sign-up, with where payroll runs | `GET /api/v1/organisation/countries` |
| The signed-in organisation's country, currency and payroll availability, for every role | `GET /api/v1/auth/me` |
| Draft rules for the five other countries, with sources | `docs/countries/` |
| Catalogue screen | `/compliance/countries` in `plutus-hr-system-frontend` |
| Country-neutral payroll engine: typed, effective-dated country rule sets, pure calculation, balanced postings, audit snapshot | `app/compliance/engine/` (Part 3) |
| The only way to a country's engine rules: an `active` rule set, reviewed by a tax adviser, approved by someone other than its preparer, every rule citing the law or the authority's own publication | `resolve_rule_set` in `app/compliance/engine/registry.py`; `REGISTERED_RULE_SETS` is empty |
| Tests | `tests/unit/test_multicountry_tax_engine.py`, `tests/unit/test_jurisdiction.py`, `tests/unit/test_tax_engine_calculation.py`, `tests/unit/test_tax_engine_rules.py`, `tests/unit/test_indirect_tax.py`, `tests/golden/test_tax_engine_nigeria_parity.py`, `tests/integration/test_api_compliance.py`, `tests/integration/test_api_organisation_country.py` |

Payroll, simulation, final settlement, bills, contractors and the compliance endpoints resolve rules for the organisation's country through `rules_for_organisation`, which refuses any country that isn't `active`. Only Nigeria has a rule version, so in practice they still compute with Nigeria's rules and refuse every other country. No tax rule is persisted in the database yet; that is Part 3.

`app/domain/money.py` knows the ISO 4217 minor-unit exponents of all six catalogued currencies: NGN, GMD, KES and GHS use 2; RWF and XOF have none (0).

## Scope
This change introduces a safe foundation, not a complete implementation of six national tax regimes. Nigeria remains on the existing legacy `RuleVersion`/payroll path for compatibility. The five additional countries are catalogued and marked `draft` until their official tax parameters are reviewed, approved and encoded.

## Target domain model

Recommended persisted entities (design target; not all are created by this starter change):

- `legal_entities`: tenant-owned entity, registered country, functional currency, fiscal year and status.
- `tax_registrations`: legal entity, tax type, registration identifier encrypted/masked at rest, jurisdiction/region, effective dates and verification status.
- `tax_rule_sets`: country, tax type, version, effective-from/to, status, source publication URL/reference, reviewer, approver, timestamps and content hash.
- `tax_rule_parameters`: typed parameter keys and values or versioned JSON validated against a country/tax-specific schema. Do not store executable code in configuration.
- `tax_calculation_snapshots`: source transaction/pay run, rule-set ID/version, taxable base, tax amount, currency, rounding policy, calculation inputs, timestamp and actor.
- `tax_filing_periods` / `tax_returns`: period, due date, state, submission reference and reconciliation status.
- `tax_audit_events`: immutable actor/action/object/before-after hash/reason records.

Add foreign keys, unique constraints, effective-date overlap checks, indexes, tenant RLS policies and Alembic migrations. Never allow overlapping active versions for the same legal entity/country/tax type/date.

## Rule lifecycle

`draft → in_review → approved → active → superseded` (with `rejected` and `withdrawn` terminal/controlled states). An author should not self-approve a rule in production. Activation is audited and effective-dated. Rules should be immutable after approval; corrections create a new version. The engine selects exactly one active rule version for a country/tax type and date, otherwise raises a configuration error.

## Calculation contract

A calculation receives a typed jurisdiction, legal entity/registration, tax type, date, currency, base components, tax treatment, and selected approved rule version. It returns tax/base/total, rounding metadata, version identifiers and traceable inputs. Use decimal or integer arithmetic; never binary floating point for money. Country rules should be pure deterministic functions. Do not hide exemptions or eligibility tests in UI code.

## API target

- `GET /compliance/countries`: supported-country catalogue (implemented).
- `GET /organisations/{id}/tax-profile`: read legal entity/country/registration profile.
- `PATCH /organisations/{id}/tax-profile`: permission-gated profile change, validated against posted-history constraints.
- `GET /tax/rules?country=...&type=...&on=...`: active rule metadata and version.
- `POST /tax/rules`: draft creation, source reference required.
- `POST /tax/rules/{id}/review` and `/approve`: maker-checker workflow.
- `POST /tax/rules/{id}/activate`: effective-dated activation, overlap validation.
- `POST /tax/estimates/vat` and `/tax/estimates/wht`: estimates that cannot post ledger entries.
- Transaction posting APIs calculate and snapshot taxes server-side; client-supplied rates are never trusted.

## Country delivery matrix

For each of GM, RW, KE, GH and CI, create an independently reviewed matrix covering VAT scope/rates/exemptions/zero-rating/registration threshold/filing periods; withholding categories and rates; individual employment tax bands and allowances; employer/employee contributions; corporate tax basis; penalties/interest only where in scope; currency precision; rounding; filing formats; source references and effective dates. The matrix must clearly mark unknowns and exclude unsupported calculations.

## Migration and backward compatibility

1. Add legal entity/tax-profile columns and tables as nullable or with safe defaults, backfill existing organisations as `NG` only where that matches verified existing configuration.
2. Do not change the meaning of current Nigerian payroll fields or re-use Nigerian-specific models for other countries.
3. Replace `_COUNTRY = "NG"` only after tenant/legal-entity context is available and integration tests prove all existing calls resolve the correct entity. Current hard-coded callers in payroll/compliance/bills/contractors require individual review.
4. Pin rule IDs and calculation snapshots for posted records. For legacy records without a rule ID, retain original stored figures and label provenance as legacy; do not recompute automatically.
5. Deploy migrations before application code that requires new columns. Maintain rollback and backup plans.

## Release gates

- Official primary source for every statutory parameter, with effective date and capture date.
- Local tax professional approval and maker-checker audit trail.
- Boundary tests for thresholds, effective-date transitions, exempt/zero-rated/out-of-scope items, credits/returns and rounding.
- Golden fixtures independently calculated and signed off.
- Tenant-isolation, permission, concurrency, idempotency, migration-upgrade and rollback tests.
- Parallel run for at least one full filing/payroll cycle where practical.
- No new-country tax posting until readiness state is `active` and server-side rules exist.
- The country's payroll screens, payslips and filings are built and show the organisation's currency.

## Delivery plan for The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire

Approved approach: build the shared foundation once, draft each country's rules from official sources in parallel, and switch a country on only after a qualified tax adviser in that country approves its rules. Nigeria's figures must not change at any step.

### Part 1: a country per organisation (now)

Independent of any country's tax rules, so it can ship before any rules are approved.

- **`organisations.country_code`**: ISO 3166-1 alpha-2, `NOT NULL DEFAULT 'NG'`. Every existing organisation is backfilled as `NG`, which matches what it has always run: payroll resolved only Nigerian rules.
- **Currency** follows the country (`CountryProfile.currency`); it is not stored separately, so the two can't disagree.
- **Choosing it.** Sign-up takes an optional `country_code` (default `NG`), and any catalogued country can be chosen; an unknown code is refused. An admin may change it later only while the organisation has no pay run and no posted ledger line (journals, bills, invoices).
- **What applies at once, and what waits.** The organisation runs in its country's currency straight away: every screen, PDF and export, and the ledger. Payroll, PAYE estimates, final settlement, simulation and withholding tax refuse a country whose rules aren't approved (`payroll_available` is false); the frontend hides those screens and explains why. Nigerian-only defaults (federal public holidays, the NHF and NSITF accounts, Nigerian states and PFA fields) aren't offered elsewhere. *Decision (25 October 2026): the product owner chose this over keeping unapproved countries unselectable.*
- **Using it.** Every caller that hard-coded `_COUNTRY = "NG"` (payroll, simulation, final settlement, bills, contractors, the current-rules endpoint) resolves the organisation's country instead. A country without an approved rule version fails closed with a clear error; it never falls back to Nigeria.
- **Currency precision.** `app/domain/money.py` gains the ISO 4217 minor-unit exponents of the six catalogued currencies (NGN, GMD, KES and GHS: 2; RWF and XOF: 0). Journals and disbursements take the organisation's currency instead of a hard-coded `NGN`. The frontend formats amounts in the organisation's currency.
- **Readiness states.** `TaxStatus` gains `draft` (rules drafted with their sources, not yet reviewed) and `in_review` (with the country's adviser) between `configuration_required` and `active`. Everything except `active` is still refused.

### Part 2: draft rules matrices (now, in parallel)

One document per country under `docs/countries/`, following the country delivery matrix above. Every figure carries its source and effective date; anything unconfirmed is marked unknown rather than guessed. Each matrix is marked `draft`, pending review by that country's adviser, and nothing in it is encoded as an active rule.

Done for all five (see [`docs/countries/README.md`](../countries/README.md)). Most figures come from secondary sources, because the tax authorities' own sites couldn't be opened from the environment the drafts were prepared in. Each figure says whether its source is official or secondary, and the adviser checks every one against the primary text.

### Part 3: country-neutral payroll engine

Designed from what the five drafts show the countries need. Built in two stages so that nothing reaches a payslip before a country is approved.

#### Stage 1: the engine (built, 26 October 2026)

`app/compliance/engine/`, pure functions with no database and no country conditionals:

- **`rules.py`: a country's rules as data.** A `CountryRuleSet` covers one country for one effective-dated window (`[effective_from, effective_to)`, like `RuleVersion`) and one pay frequency whenever it has per-period amounts. It holds:
  - **contributions**, employee or employer: a rate on a base, or a flat per-head amount. The base is a set of earnings categories (basic, housing, transport, fixed allowances, variable pay, other) or net pay. A contribution can have a lower and an upper earnings limit (tiers), a minimum and a cap, can apply to expatriates or local staff only, and can be deductible before income tax within a capped group;
  - **income tax**, per period or cumulative over the tax year: progressive bands, rounded per band or once on the total; deductible contributions; annual reliefs spread over the year (cumulative only); and tax credits, fixed or by family shares (per period only);
  - **payroll levies**, charged once on the pay run's total;
  - for every line, the authority, the due rule (a day of the following month, days or working days after the period), the ledger accounts, the rounding (mode and increment, so RWF and XOF can round to whole francs or hundreds), and the **source it cites**;
  - its **status and approval**: who prepared it, which tax adviser reviewed it, who approved it and when.

  `structural_problems` rejects anything ambiguous: bands that don't rise, a contribution on net pay that claims to be tax-deductible, a cumulative table that starts mid-year, per-period amounts across several pay frequencies, a cited source that isn't listed, and so on. `activation_problems` is the release gate as far as code can check it: status `active`, a reviewer, an approver who isn't the preparer, and every cited source the law or the authority's own publication.
- **`calculate.py`: the calculation.** `calculate_payslip` works in a fixed order: contributions on earnings, then income tax, then contributions on net pay. It returns every statutory line (code, kind, authority, base, rate, amount, accounts, due date, source), the income tax working, the net pay and the employee's year-to-date totals. `snapshot()` records all of it with the inputs and the rule set's id, ready to persist with a posted payslip. A rule that needs an employee figure Plutus doesn't hold (family shares, expatriate status) refuses to run rather than assume one, and so does a minimum contribution larger than the pay. `calculate_payroll_levies` charges each levy once on the run's total.
- **`postings.py`**: balanced postings for a payslip and for levies, in the same shape as Nigeria's.
- **`indirect_tax.py`: VAT and other transaction taxes** (26 October 2026, reworked from PR #62). An `IndirectTaxRuleSet` holds one country's components for one tax type and window, each citing its source, with the same status and approval record as a payroll rule set. `calculate_indirect_tax` itemises each component, charged on the net amount or compounding on the earlier ones. A zero-rated, exempt or out-of-scope supply carries no tax and reports a 0% rate. A tax-inclusive price with more than one component is refused, because how the components share it is a country rule that isn't modelled. It replaces `EffectiveRate` and `calculate_percentage_tax`, which only their tests used, so there is one transaction-tax calculator; its inclusive arithmetic is unchanged, and a property test compares the two. Whether a supply is taxable, and how, stays the caller's decision.
- **`registry.py`**: `REGISTERED_RULE_SETS`, empty, and `resolve_rule_set`, the only way a pay run may get a country's rules. It refuses a country the catalogue doesn't mark `active`, a date no `active` rule set covers, two rule sets in force at once, and any rule set that fails the release gate. Nigeria can't be registered while it runs on `RuleVersion`. `REGISTERED_INDIRECT_TAX_RULE_SETS`, also empty, and `resolve_indirect_tax_rule_set` do the same for transaction taxes, by country, tax type and date, through the same release gate (`approval_problems` in `rules.py`).

**Evidence.** `tests/golden/test_tax_engine_nigeria_parity.py` restates NG-2026.1 in the engine's terms, reading every figure from the `RuleVersion`. On the hand-verified golden payslip and on 300 generated pay histories across all three pay frequencies, the engine's PAYE, pension, NHF, rent relief, chargeable income, net pay, postings and due dates equal the existing Nigerian functions' to the kobo, and its NSITF equals the pay-run liability's. Every other mechanism is tested with fictional figures (`tests/unit/test_tax_engine_calculation.py`, `tests/unit/test_tax_engine_rules.py`); no real rate for any of the five countries is in the code.

**Not supported yet**, because no draft confirms how it works: benefits in kind and the Gambian fringe benefits tax; annual per-person charges such as the Gambian expatriate quota; annual levies with a qualification test (Nigeria's ITF stays on its own path); a cumulative table that changes mid-year; voluntary pre-tax deductions (Kenya's mortgage interest and post-retirement medical fund).

#### Stage 2: pay runs (next, before any country goes live)

- Payslip statutory lines persisted per payslip (code, kind, authority, base, rate, amount, due date, rule set id and the calculation snapshot), while Nigeria's existing columns stay readable for history.
- The pay run calls `resolve_rule_set` and `calculate_payslip` for an engine country, and keeps Nigeria on its current path.
- Liabilities keyed by country and line code, rather than the fixed Nigerian `LiabilityScheme` enum, and the ledger accounts each line names added to that organisation's chart.
- Employee fields a country needs that Plutus doesn't hold (family shares, expatriate status), added with an audit trail.
- Payslip PDFs, payroll reports and screens that show the country's lines in its currency.
- `payroll_available` then also requires an `active` engine rule set for the country.

Nigeria moves onto the engine only as a separate, deliberate step, behind the golden, parity and pay-run regression tests, with identical figures.

#### How a country's rules get encoded

1. The country's tax adviser completes the review in `docs/countries/` and signs off worked examples (`docs/countries/README.md`).
2. Its rule set is written in `app/compliance/engine/` from the approved figures only. Every rule cites its primary source, and the approval record names the preparer, the adviser and a different approver.
3. The signed-off examples become golden tests for it, alongside property tests that its payslips balance.
4. It is added to `REGISTERED_RULE_SETS` as `active`, and the country's catalogue status becomes `active`, only after the release gates above pass and stage 2 is in place.
