---
name: plutus-transaction-tax-engine
description: Implement, test, review, or extend Plutus's jurisdiction-neutral transaction tax calculation primitives for VAT and other indirect taxes.
---

# Plutus transaction tax engine

Before changing this area, read docs/architecture/multicountry-tax.md and docs/architecture/transaction-tax-engine.md, plus app/compliance/transaction_tax.py and its unit tests.

- Preserve the existing Nigeria payroll RuleVersion path and regression tests.
- Never add unverified statutory rates for The Gambia, Rwanda, Kenya, Ghana, or Côte d’Ivoire.
- Use integer minor units for money and parts-per-million for rates.
- Keep tax components separately itemised and explicitly model compounding.
- Only ACTIVE, effective-dated rule packs may calculate; draft and unapproved packs must fail closed.
- Inclusive multi-component calculations must not guess tax order or rounding. Require a verified country-specific policy first.
- Do not confuse calculation with ledger posting. Integrate through existing invoice/bill posting services and preserve audit history.
- A production-ready country requires primary-source references, effective dates, reviewed test vectors, migration/API/UI coverage, and qualified local tax review.
- Run the relevant unit/integration tests, lint, type checks and builds; report only commands actually run and their real outcomes.
