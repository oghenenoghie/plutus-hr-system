# Transaction Tax Engine — implementation status

Status: initial calculation primitives implemented; this is not yet a complete production tax-compliance system.

## Implemented in this change
- Immutable indirect-tax rule-pack and component models in app/compliance/transaction_tax.py.
- Country and tax-type matching, effective-date checks, and fail-closed handling of draft/unapproved packs.
- Standard, zero-rated, exempt, and out-of-scope treatments.
- Exclusive calculations with separately itemised components and explicitly compounded components.
- Single-component inclusive-price extraction using integer minor-unit arithmetic and half-up rounding.
- Unit tests for calculation, rule status, mismatch, effective-date boundaries, and approval-field validation.

## Country readiness
Plutus currently catalogues NG, GM, RW, KE, GH, and CI. The existing Nigeria payroll implementation is not replaced. The five requested expansion countries remain draft until their rule packs are verified, reviewed, and encoded. Test rates in unit tests are fixtures only, not statutory values.

## Not yet implemented
- Database persistence, migrations, immutable version storage, and admin review workflow.
- API endpoints for creating, reviewing, publishing, or calculating transaction tax.
- Integration with invoice/bill posting and general ledger.
- Official return generation and country-specific statutory rule packs.
- Frontend tax-rule administration.
- Full backend and frontend regression execution.

Inclusive calculations with multiple standard-rated components are deliberately rejected until jurisdiction-specific allocation and rounding rules are verified. Do not activate a country based only on an approver field; require documented primary-source review and authorised approval.

Rates use parts per million (1,000,000 = 100%); money uses integer minor units. Before production, validate currency precision, rounding policy, tax treatment, and accounting mappings for each country with official guidance and a qualified local tax professional.
