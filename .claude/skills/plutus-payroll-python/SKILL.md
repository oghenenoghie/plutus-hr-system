---
name: plutus-payroll-python
description: 'Engineering and domain reference for the Python build of Plutus — a compliance-native HR and payroll platform for Nigeria and Africa, built on FastAPI + PostgreSQL + Railway (async workers, Arq, SQLAlchemy/Alembic) rather than the TypeScript/Supabase stack. Use for any Python-stack Plutus work: the statutory compliance engine (PAYE, pension, NHF, NHIS, NSITF, ITF, WHT), modelling employees/pay-runs/remittances/loans/benefits/final-settlement, building any FastAPI endpoint or SQLAlchemy model or Alembic migration, the versioned rules engine, RLS via session GUC, money-as-minor-units, testing, CI/CD, or Railway deployment. Trigger even without the word "Plutus" — a Python/FastAPI payroll or HR system for Nigeria, Nigerian tax bands, statutory deductions, the 2026 tax reform, TIN gating, cumulative PAYE, or state-level PAYE filing on a Python stack all qualify. The domain is shared with the plutus-payroll-platform skill; this skill is the FastAPI/Railway engineering variant. Always consult the statutory reference before writing calculation logic or quoting a rate — figures are versioned and must be sourced, never invented.'
---

# Plutus — Payroll Platform (Python / FastAPI / Railway build)

Plutus is a cloud HR + payroll platform whose single organising idea is **payroll should be correct by construction**. Compliance is not a feature bolted onto generic payroll software — it *is* the product. The wedge is Nigeria's 2026 tax reform; the ambition is to be the payroll backbone for employers across West and East Africa.

Positioning line: *"The compliance-native payroll platform for Nigeria and Africa."*

**This skill is the Python engineering variant.** It shares its entire domain — the statutory rules, the product thesis, the guardrails — with the `plutus-payroll-platform` skill (the TypeScript/Supabase build). The difference is the stack: **FastAPI + PostgreSQL + Railway**, with SQLAlchemy/Alembic, Arq workers, and RLS enforced via a session GUC. Where the two describe the same thing (rules, entities, non-negotiables), they must agree.

## When to reach for the reference files

- **Any calculation, rate, base, threshold, remittance authority, or deadline** → read `references/nigeria-statutory-compliance.md` **first**. Do not quote a number from memory; that file is the specification the rule set must encode, and it is versioned. It includes an errata section (§11) of prototype errors that must not be ported.
- **Anything touching the build** — FastAPI structure, SQLAlchemy models, Alembic migrations, the rules engine, RLS/session-GUC tenancy, money handling, connection pooling, testing, CI/CD, Railway deployment, security → read `references/python-engineering.md`.
- **Product scope, information architecture, roles, screen inventory, feature map, brand voice, investor/GTM content, design tokens, or the feature backlog / known calculation gaps** → these are stack-agnostic; read them from the `plutus-payroll-platform` skill's `references/` (`product-and-ia.md`, `feature-backlog.md`, `design-system.md`). Don't duplicate them here — that skill is their single source of truth.

## The core thesis (why the product exists)

Nigeria's payroll compliance landscape changed fundamentally on **1 January 2026**. Four Acts signed June 2025 — the **Nigeria Tax Act (NTA)**, **Nigeria Tax Administration Act (NTAA)**, **Nigeria Revenue Service (Establishment) Act**, and **Joint Revenue Board (Establishment) Act** — replaced the Personal Income Tax Act and rewrote how employers calculate, withhold, and remit tax on every employee.

The reform did not simplify payroll — **it raised the cost of getting it wrong**: new progressive PAYE bands and a raised tax-free threshold; the Consolidated Relief Allowance abolished and replaced by a capped rent relief; **mandatory Tax Identification Numbers** for every worker; and a digitally-enabled Nigeria Revenue Service that cross-references payroll against bank records, with expanded audit and penalty powers.

Most employers still run payroll on spreadsheets or tools built for the old code. Plutus is built from the ground up on the new framework: **correct on day one, current for every reform that follows.**

## Product architecture (three pillars)

1. **Payroll Core** — multi-frequency runs, itemised digital payslips, arrears, bonuses, 13th-month handling, full audit trails, cumulative recalculation whenever pay changes mid-year.
2. **Compliance Engine** — automatic PAYE, pension, NHF, NHIS, NSITF, ITF and withholding-tax calculation, filing, and remittance tracking. **This is the differentiator.** It is a *rules engine over a common payroll core*, so rules change centrally as the law changes underneath.
3. **People Operations** — leave, attendance, loans and advances, expenses, benefits, final settlement, employee and manager self-service, in one system of record.

## The single most important engineering principle

**The compliance engine is versioned; rules are data, not code.** Rates, reliefs, thresholds, and band edges live in a central, effective-dated rule set (rows in Postgres, loaded into frozen Pydantic models) that updates the moment a statutory agency issues new guidance — **no hardcoded magic numbers anywhere in calculation logic.** When the law changes, one central version bump corrects every payslip going forward, and historical runs remain reproducible against the rules in force at the time.

A `grep -rn` for statutory figures inside `app/domain/` or `app/services/` should return nothing. Changing the law means adding a rule version and an Alembic migration, never editing calculation logic. See `references/python-engineering.md` §5 for the implementation contract.

## Non-negotiable compliance behaviours

Product requirements, not nice-to-haves (identical across both stacks):

- **TIN gating.** Every employee must hold a valid Tax Identification Number. The engine flags unregistered workers **before** a run, not after an audit. Never let a run proceed silently for a TIN-less employee.
- **Cumulative PAYE.** Computed on cumulative annual chargeable income and re-derived whenever pay changes mid-year — not a naïve monthly slice.
- **State-of-residence mapping.** PAYE is collected by each state's Internal Revenue Service. Map every employee to their state of residence; generate state-specific filing schedules; consolidate remittance evidence across every state an employer operates in.
- **Right agency, right deadline.** Each scheme has its own base, rate, remittance authority, and deadline. Conflating them is the single most common error in this domain — the prototype shipped one (see statutory errata §11).
- **Employer-side vs employee-side.** NSITF, ITF and employer pension are company costs, never employee deductions. The type system encodes `borne_by`; employer costs must be structurally unable to land in an employee's deduction total.
- **Audit-ready by default.** Every pay cycle keeps a full trail; statutory liabilities, filing status, and evidence must be reportable by entity, state, or country.
- **Contractor withholding.** WHT on contractor/vendor payments with certificate generation, rates by service category — a gap most payroll-only tools ignore.

## Python-stack essentials (the shape of the build)

Full detail in `references/python-engineering.md`. The load-bearing choices:

- **FastAPI** (async, versioned routers) · **PostgreSQL 16 on Railway** as the sole system of record · **SQLAlchemy 2.0** (typed) + **Alembic** (the only way schema ships) · **Arq** async workers on Railway for batch pay runs, filings and PDF/report generation · **Redis** broker · **Resend** email.
- **Tenancy = PostgreSQL RLS via a session GUC** (`SET LOCAL app.current_org = …` inside a request-scoped transaction; policies read `current_setting(...)`). No handler runs without the GUC set; deny by default. This is the folad_lms pattern.
- **Money = integer minor units in `BIGINT`.** Never `float`; never persist `Decimal`. Rates apply as parts-per-million integers with one documented rounding rule.
- **Append-only** payslips, ledger entries, audit events, statutory liabilities — enforced in the DB (revoked `UPDATE`/`DELETE` or a raising trigger). Corrections are new rows.
- **Pure domain layer.** `app/compliance/` and `app/domain/` import no ORM, no FastAPI — calculators take rule sets in and return numbers out, which keeps golden tests fast and the moat portable to a second country.
- **Golden tests are the highest-priority CI gate** (`nigeria-statutory-compliance.md` §12). A green build with a broken calculation must be impossible.
- Tooling: **uv**, **Ruff**, **mypy --strict**, **pytest** + **Hypothesis**, GitHub Actions with an Alembic migrate-before-deploy check.

## Guardrails when working on Plutus (Python or otherwise)

- **Never invent or approximate a statutory figure.** If a rate, band, or threshold is needed and isn't in `references/nigeria-statutory-compliance.md`, say so and verify against a current primary source (NRS / PenCom / FMBN / NSITF / ITF) before writing logic that depends on it. Wrong payroll numbers cause real financial and legal harm to real employees.
- **Treat the reference as a snapshot, not gospel forever.** The 2026 reform is recent and guidance is still settling. For production calculation logic or client-facing tax claims, confirm figures are still current and flag the date-sensitivity.
- **Prefer flagging a conflict over silently picking a side.** When two sources disagree, surface it — that is how the NSITF deadline error was caught.
- **This is not tax or legal advice.** Plutus encodes rules; it doesn't replace a tax professional. Keep that framing in client-facing copy.
- **Demo data is demo data.** Prototype employees, banks, PFAs and amounts are illustrative fixtures — never real client data or benchmarks.

## Pan-African expansion (direction, not present scope)

Because the compliance engine is a rules layer over a common core, **each new country adds a statutory rule set, not a new platform.** Nigeria is live (PAYE · Pension · NHF · NHIS · NSITF · ITF · WHT); Ghana (PAYE · SSNIT · Tier 2/3) and Kenya (PAYE · NSSF · SHIF) are on the roadmap. Deepen the Nigerian moat first; don't hardcode Nigeria assumptions (currency exponent, scheme count, single-tax-authority, "states" as the only sub-national unit) into the shared core.

## Business model (one line)

Per-employee-per-month SaaS, tiered by feature depth (core payroll + compliance vs. full HR suite). Compliance is the wedge; the encoded-rules moat is the defensibility.
