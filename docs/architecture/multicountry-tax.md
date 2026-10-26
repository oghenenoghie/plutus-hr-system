# Multi-country tax architecture and implementation notes

Status: **foundation, drafts and engine core.** Nigeria is unchanged and is the only country Plutus calculates payroll or statutory tax for. Each organisation has a country (Part 1 below): any of the six can be chosen at sign-up and applies at once, while payroll waits for that country's approved rules. The Gambia, Rwanda, Kenya, Ghana and Côte d'Ivoire are marked `draft`: their rules are drafted, with sources, in [`docs/countries/`](../countries/README.md) and await review by a tax adviser in each country. No statutory rate for them is encoded, and any attempt to use one fails closed. The country-neutral payroll engine (Part 3, stage 1) is built and reproduces Nigeria's payroll to the kobo. Pay runs for every other country now go through it, and payslips, reports, analytics and the disbursement file show its lines in its currency (stages 2a and 2b). But no country's rules are encoded in it, so none of them runs. The rest of this document is the design target that a country must meet before it is enabled.

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
| Pay runs for a country on the engine: statutory lines per payslip, postings, liabilities and levies, the year to date | `app/services/engine_payroll.py`, called from `app/services/payroll.py`; `payslip_statutory_lines` (Part 3, stage 2a) |
| Tests | `tests/unit/test_multicountry_tax_engine.py`, `tests/unit/test_jurisdiction.py`, `tests/unit/test_tax_engine_calculation.py`, `tests/unit/test_tax_engine_rules.py`, `tests/unit/test_indirect_tax.py`, `tests/golden/test_tax_engine_nigeria_parity.py`, `tests/integration/test_api_compliance.py`, `tests/integration/test_api_organisation_country.py`, `tests/unit/test_engine_payroll.py`, `tests/integration/test_engine_pay_runs.py`, `tests/integration/test_engine_payroll_outputs.py` |

Payroll and final settlement take Nigeria's path or the engine's by the organisation's country (`uses_engine`). Simulation, bills, contractors and the compliance endpoints resolve rules through `rules_for_organisation`, which refuses any country that isn't `active` and, for now, any country on the engine. Only Nigeria has approved rules, so in practice everything still computes with Nigeria's rules and refuses every other country. No tax rule is persisted in the database yet; that is Part 3.

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

#### Stage 2: pay runs

Stage 2 connects the engine to pay runs in parts. Each part is merged on its own and changes nothing for any organisation until a country is approved: `REGISTERED_RULE_SETS` is still empty, and no country but Nigeria is `active` in the catalogue.

##### Stage 2a: the pay run (built, 26 October 2026)

- **Which path.** `uses_engine` in `app/services/jurisdiction.py` is true for every country but Nigeria. `process_employee_payslip` (`app/services/payroll.py`) sends an engine country's payslip to `_process_engine_payslip`; Nigeria's path is unchanged. What both paths share (proration, overtime, leave encashment, the loan installment, benefits, union dues) is gathered once in `_gather_period`. The engine-specific work is in `app/services/engine_payroll.py`.
- **The payslip.** Its earnings go to the engine by category: basic, housing and transport as themselves, the recurring "other earnings" as fixed allowances, overtime as variable pay, and leave payouts and settlement amounts as other earnings. Each rule set decides which categories each base includes. After the statutory lines, the loan installment, benefits and union dues come off net pay in Nigeria's order and with its "skip what doesn't fit" rule.
- **What is stored.**
  - Each statutory line is written to `payslip_statutory_lines`, in calculation order. Like payslips, the table is tenant-isolated (RLS) and append-only. A line records its code, kind, authority, base, rate, amount, accounts, due date, cited source and rule set id.
  - The payslip keeps the engine's full snapshot (`derivation.engine`), plus this period's taxable pay, deductions and income tax (`derivation.engine_period`). Later periods sum those for the year to date, counting locked runs only, so a reversed run drops out as it does for Nigeria.
  - Nigeria's pension and NHF columns are 0 on an engine payslip, and `paye_minor` holds its income tax. `rule_version_id` holds the rule set id.
  - `GET /pay-runs/{id}/payslips` returns the lines as `statutory_lines`.
- **Postings.**
  - The rule set's payable and expense accounts are added to the organisation's chart before the first posting, and every posting is checked against the chart.
  - The payslip's journal debits gross pay and the employer contributions. It credits each payable, the loan receivable, recovered benefits, union dues and net pay.
  - Payroll levies are charged once per run on the run's total, with their own journal.
- **Liabilities.**
  - Liabilities use the `country` scheme. There is one per payable account, authority and due date across the run, so an employee's and the employer's share of the same contribution are one payment.
  - `line_code` names the lines a liability covers, and `liability_account` names the account its remittance clears.
  - The base counts each payslip's pay once, as Nigeria's pension liability does.
  - Remitting one posts Dr payable, Cr cash. Filing, remitting, reversal and the compliance calendar handle them like Nigeria's.
- **Employees.** `tax_half_shares` (family shares, in halves) and `is_expatriate` are on the employee record and the employee API. Changes go to the audit log like any other field. Like rent paid, they are hidden from roles that don't see pay. Both stay null until recorded. A rule that needs one refuses the run, naming the employee (HTTP 422), and the run goes through once the record is completed.
- **Refusals up front.** Validating a run resolves the rule set for its period and frequency. So a country with no approved rule set in force is refused at validation, not only at lock. `payroll_available` now also needs an `active` engine rule set for the country.
- **Evidence.** `tests/integration/test_engine_pay_runs.py` runs pay runs through the API against a rule set of fictional figures, registered for the test only. It checks:
  - the lines, net pay, balanced postings and liabilities, worked out by hand, with a loan, a benefit and union dues;
  - remitting a country liability;
  - the cumulative year to date across three runs with one reversed;
  - refusals for missing employee data, a missing rule set and a rule set not yet in force;
  - tenant isolation.

  The Nigerian payroll, settlement, statutory and reporting suites pass unchanged.

##### Stage 2b: what an engine country's people see (built, 26 October 2026)

Everything that read only Nigeria's payslip columns or assumed naira now shows an engine country's own lines in its currency. Nigeria's output is unchanged, and its queries are the same SQL as before.

- **Payslip PDF** (`payslip_pdf.py`) shows:
  - the amounts in the organisation's currency;
  - gross pay, then each employee line in calculation order (contributions and income tax), then the loan, benefits and union dues, then net pay;
  - the employer's contributions beneath, and the rule set id.

  It leaves out the state of residence, which only Nigerian PAYE needs.
- **Payroll reports** (`payroll_reports.py`, `GET /reports/...`):
  - the payroll register carries each payslip's lines (`statutory_lines`);
  - the new statutory summary (`GET /reports/statutory-summary`) totals the lines by code over locked runs. It is an engine country's schedule, empty for Nigeria;
  - PAYE by state refuses an engine country (422), because its income tax isn't owed to a Nigerian state;
  - the annual reconciliation carries each employee's line totals for the year (`statutory_totals`).
- **Tax certificate** (`tax_certificate_pdf.py`): lists what was withheld, line by line, in the organisation's currency. The employer's contributions aren't listed, because they weren't withheld.
- **Disbursement file** (`disbursement.py`): amounts in the organisation's currency and decimal places. Nigeria's column stays `amount_naira`; another country's is `amount_<currency>`, for example `amount_kes`.
- **Payroll analytics** (`analytics/payroll.py`, `analytics/records.py`):
  - an engine country's employer contributions come from its lines, so payroll cost is gross pay plus them;
  - its employee contributions count as statutory deductions;
  - the deduction chart reads "Income tax" and "Employee contributions";
  - the new `statutory_lines` dataset lists every line;
  - a country liability is named by its line codes.

  Analytics finds a country's payslips by the rule id's prefix, so a rule set's id must start with its country code (`KE-2026.1`). `structural_problems` enforces this.
- **Frontend** (`plutus-hr-system-frontend`):
  - the pay run detail, payroll reports, self-service payslip, liabilities and analytics reports show the lines;
  - the employee form and record show family shares and expatriate status, for a non-Nigerian organisation only, and only to someone who can see the employee's pay;
  - `e2e/countries.spec.ts` checks the employee fields both ways.
- **Evidence:** `tests/integration/test_engine_payroll_outputs.py`. Against the fictional rule set, it checks:
  - the PDFs' text;
  - every report;
  - the disbursement header;
  - the analytics figures, worked out by hand.

  It also checks Nigeria's PDF, certificate, register and disbursement file as before.

**Still Nigeria-only.** These use Nigeria's `RuleVersion` only and refuse an engine country (`rules_for_organisation`) until each is moved onto the engine:
- simulation;
- gross-up;
- contractor and bill withholding;
- `GET /compliance/current-rules`.

**Calendar tax year.** The annual reconciliation covers January to December. A country whose tax year starts in another month needs its own window before going live. None of the five drafts says otherwise, but each adviser should confirm it.

##### Stage 2c: the desktop edition

The desktop backend and frontend get the engine (Stage 1), indirect tax and Stages 2a and 2b.

Nigeria moves onto the engine only as a separate, deliberate step, behind the golden, parity and pay-run regression tests, with identical figures.

#### How a country's rules get encoded

1. The country's tax adviser completes the review in `docs/countries/` and signs off worked examples (`docs/countries/README.md`).
2. Its rule set is written in `app/compliance/engine/` from the approved figures only. Every rule cites its primary source, and the approval record names the preparer, the adviser and a different approver.
3. The signed-off examples become golden tests for it, alongside property tests that its payslips balance.
4. It is added to `REGISTERED_RULE_SETS` as `active`, and the country's catalogue status becomes `active`, only after the release gates above pass and Stage 2c is in place.
