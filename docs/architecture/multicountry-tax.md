# Multi-country tax architecture and implementation notes

Status: **foundation and drafts.** Nigeria is unchanged and is the only country the engine calculates or posts for. Each organisation now has a country (Part 1 below). The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire are marked `draft`: their rules are drafted, with sources, in [`docs/countries/`](../countries/README.md) and await review by a tax adviser in each country. No statutory rate for them is encoded, and any attempt to use one fails closed. The rest of this document is the design target that a country must meet before it is enabled.

## What exists today

| Piece | Where |
|---|---|
| Country catalogue: code, currency, tax authority, readiness status | `COUNTRY_PROFILES` in `app/compliance/multicountry.py` |
| Effective-dated, approved rate (ppm, source reference, approver, half-open `[from, to)` window as `RuleVersion` uses) | `EffectiveRate` in the same module |
| Percentage tax, tax-exclusive and tax-inclusive, integer minor units, half-up rounding (exclusive reuses `apply_rate_ppm`) | `calculate_percentage_tax` |
| Fail-closed guard for any country without approved rules | `require_configured_country` |
| The organisation's country, and the rules and currency that follow from it | `organisations.country_code`; `app/services/jurisdiction.py` |
| Authenticated read-only catalogue | `GET /api/v1/compliance/countries` in `app/api/v1/compliance.py` |
| Public list of countries an organisation can choose at sign-up | `GET /api/v1/organisation/countries` |
| Draft rules for the five other countries, with sources | `docs/countries/` |
| Catalogue screen | `/compliance/countries` in `plutus-hr-system-frontend` |
| Tests | `tests/unit/test_multicountry_tax_engine.py`, `tests/unit/test_jurisdiction.py`, `tests/integration/test_api_compliance.py`, `tests/integration/test_api_organisation_country.py` |

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

## Delivery plan for The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire

Approved approach: build the shared foundation once, draft each country's rules from official sources in parallel, and switch a country on only after a qualified tax adviser in that country approves its rules. Nigeria's figures must not change at any step.

### Part 1: a country per organisation (now)

Independent of any country's tax rules, so it can ship before any rules are approved.

- **`organisations.country_code`**: ISO 3166-1 alpha-2, `NOT NULL DEFAULT 'NG'`. Every existing organisation is backfilled as `NG`, which matches what it has always run: payroll resolved only Nigerian rules.
- **Currency** follows the country (`CountryProfile.currency`); it is not stored separately, so the two can't disagree.
- **Choosing it.** Sign-up takes an optional `country_code` (default `NG`). An organisation may choose a country only when its profile is `active` and a rule version exists for it; any other is refused with a message saying its rules aren't approved yet. An admin may change it later only while the organisation has no pay run and no posted journal, and only to such a country.
- **Using it.** Every caller that hard-coded `_COUNTRY = "NG"` (payroll, simulation, final settlement, bills, contractors, the current-rules endpoint) resolves the organisation's country instead. A country without an approved rule version fails closed with a clear error; it never falls back to Nigeria.
- **Currency precision.** `app/domain/money.py` gains the ISO 4217 minor-unit exponents of the six catalogued currencies (NGN, GMD, KES and GHS: 2; RWF and XOF: 0). Journals and disbursements take the organisation's currency instead of a hard-coded `NGN`. The frontend formats amounts in the organisation's currency.
- **Readiness states.** `TaxStatus` gains `draft` (rules drafted with their sources, not yet reviewed) and `in_review` (with the country's adviser) between `configuration_required` and `active`. Everything except `active` is still refused.

### Part 2: draft rules matrices (now, in parallel)

One document per country under `docs/countries/`, following the country delivery matrix above. Every figure carries its source and effective date; anything unconfirmed is marked unknown rather than guessed. Each matrix is marked `draft`, pending review by that country's adviser, and nothing in it is encoded as an active rule.

Done for all five (see [`docs/countries/README.md`](../countries/README.md)). Most figures come from secondary sources, because the tax authorities' own sites couldn't be opened from the environment the drafts were prepared in. Each figure says whether its source is official or secondary, and the adviser checks every one against the primary text.

### Part 3: country-neutral payroll engine (after the drafts)

Designed from what the drafts show the five countries need, not before. It will replace the Nigeria-shaped `RuleVersion` and payslip columns with:

- a per-country rule module behind one typed interface (pure functions over effective-dated rules);
- payslip statutory lines with a code, kind (employee deduction, employer contribution, income tax), authority, due date and ledger account, while Nigeria's existing columns stay readable for history;
- liability schemes keyed by country rather than the fixed Nigerian enum.

Nigeria moves onto the same interface only behind the golden and pay-run regression tests, with identical figures. Any employee data a country needs that Plutus doesn't hold today (for example family status, if a country's income tax depends on it) is identified in the drafts first.
