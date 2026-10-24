# Multi-country tax architecture and implementation notes

Status: **foundation only.** Nigeria is unchanged and is the only country the engine calculates or posts for. The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire are catalogued and marked `configuration_required`. No statutory rate for them is shipped, and any attempt to use one fails closed. The rest of this document is the design target that a country must meet before it is enabled.

## What exists today

| Piece | Where |
|---|---|
| Country catalogue: code, currency, tax authority, readiness status | `COUNTRY_PROFILES` in `app/compliance/multicountry.py` |
| Effective-dated, approved rate (ppm, source reference, approver, half-open `[from, to)` window as `RuleVersion` uses) | `EffectiveRate` in the same module |
| Percentage tax, tax-exclusive and tax-inclusive, integer minor units, half-up rounding (exclusive reuses `apply_rate_ppm`) | `calculate_percentage_tax` |
| Fail-closed guard for any country without approved rules | `require_configured_country` |
| Authenticated read-only catalogue | `GET /api/v1/compliance/countries` in `app/api/v1/compliance.py` |
| Catalogue screen | `/compliance/countries` in `plutus-hr-system-frontend` |
| Tests | `tests/unit/test_multicountry_tax_engine.py`, `tests/integration/test_api_compliance.py` |

Nothing here is persisted yet. There are no new tables or migrations, and no payroll, bill or contractor caller uses these primitives. Those still resolve Nigerian rules through `resolve_rule_version("NG", ...)`.

Known gap before any non-NGN amount is formatted: `app/domain/money.py` knows only the NGN minor-unit exponent. RWF and XOF have no minor units (exponent 0), while GMD, KES and GHS use 2. These must be added there and never assumed.

## Scope
This change introduces a safe foundation, not a complete implementation of six national tax regimes. Nigeria remains on the existing legacy `RuleVersion`/payroll path for compatibility. The five additional countries are catalogued but marked `configuration_required` until their official tax parameters are encoded and reviewed.

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
