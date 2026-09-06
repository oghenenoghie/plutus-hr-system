<!--
  SYNC NOTE — this file mirrors the identical reference in the `plutus-payroll-platform`
  skill. The statutory rules are the SAME regardless of stack (TypeScript/Supabase or
  Python/FastAPI). If the two ever diverge, reconcile them — they must not drift.
  The true runtime source of truth is the versioned rule set encoded as DATA in the
  compliance engine (see `python-engineering.md` §5), not this document. This document
  is the human-readable specification that the rule set must faithfully encode.
-->

# Nigeria Statutory Payroll Compliance — Rule Reference

**Source of truth for the Plutus compliance engine.** Effective **1 January 2026** under the Nigeria Tax Act 2025 and the existing statutory schemes.

> **Versioning rule:** every figure here is effective-dated and must live in a central rule set, not hardcoded. Bump the rule version centrally when the NRS or an agency issues new guidance. Historical pay runs must remain reproducible against the rules in force at the time.
>
> **Verification rule:** the 2026 reform is recent and guidance is still settling. Before shipping production calculation logic or client-facing tax claims, re-confirm figures against a current primary source (NRS, PenCom, FMBN, NSITF, ITF). Do not treat this file as permanently authoritative.
>
> **Sourcing status:** PAYE bands and reliefs reflect the Nigeria Tax Act 2025 schedule. Remittance deadlines in §10 were re-verified July 2026 against Nigerian tax-practice sources and corrected — see §11 errata. Deadlines are the figures most likely to be stated inconsistently across secondary sources, so treat §10 as the highest-priority section to re-confirm against primary agency guidance before go-live.

## Table of contents
1. Personal Income Tax (PAYE) — bands, reliefs, TIN
2. The reference calculation (how the engine derives PAYE)
3. Pension (PenCom / PFAs)
4. National Housing Fund (NHF)
5. NHIS / NHIA health insurance
6. NSITF (Employee Compensation)
7. Industrial Training Fund (ITF)
8. Withholding Tax on contractors
9. State-level & multi-state PAYE
10. Quick-reference matrix
11. Errata — known errors in the prototype
12. Golden-test cases

---

## 1. Personal Income Tax (PAYE) — Nigeria Tax Act 2025

Replaces the old 7–24% structure. Progressive schedule applied to **annual chargeable income**, computed cumulatively across the year and recalculated when pay changes mid-year.

| Annual chargeable income | Marginal rate |
|---|---|
| First ₦800,000 | 0% |
| Next ₦2,200,000 (₦800,001 – ₦3,000,000) | 15% |
| Next ₦9,000,000 (₦3,000,001 – ₦12,000,000) | 18% |
| Next ₦13,000,000 (₦12,000,001 – ₦25,000,000) | 21% |
| Next ₦25,000,000 (₦25,000,001 – ₦50,000,000) | 23% |
| Above ₦50,000,000 | 25% |

- **Tax-free threshold:** ₦800,000/yr (≈ ₦66,667/month). Earnings at or below the national minimum wage are exempt.
- **These are marginal rates** — the higher rate applies only to income falling within each band. Sum the tax from each applicable band.
- **PAYE base** now includes all forms of remuneration; gratuity is taxable.

### Reliefs
- **Consolidated Relief Allowance (CRA): ABOLISHED.**
- **Rent relief:** 20% of annual rent paid, **capped at ₦500,000**. Applied before computing chargeable income.

### TIN (mandatory — hard gate)
- Every taxable person must hold a valid **Tax Identification Number** (Nigeria Tax Administration Act).
- Engine behaviour: **flag any employee without a valid TIN *before* the payroll run.** Guide them to register with the NRS before the next run. Do not silently process a TIN-less employee.

## 2. The reference calculation (how the engine derives PAYE)

This is the derivation the prototype exposes step-by-step in its PAYE Calculator, and the shape production logic should follow:

```
basic          = annual gross × 50%      ← illustrative split only; see caveat
housing        = annual gross × 30%
transport      = annual gross × 20%

pensionable    = basic + housing + transport
pension (EE)   = pensionable × 8%
pension (ER)   = pensionable × 10%        ← employer cost, NOT a deduction
nhf            = basic × 2.5%
rent relief    = min(annual rent × 20%, ₦500,000)

chargeable     = max(0, annual gross − pension(EE) − nhf − rent relief)

PAYE           = Σ over bands of (income in band × band rate)
monthly PAYE   = annual PAYE ÷ 12
```

**Caveat on the 50/30/20 split.** That split is a demo convenience so the calculator can work from a single gross figure. **Production must read actual pay components per employee** — real Nigerian pay structures vary, and pensionable emoluments are specifically basic + housing + transport as actually constituted, not a derived percentage. Note that under a 50/30/20 split the three components sum to 100% of gross, which makes pensionable pay equal gross; that coincidence will not hold with real component data, so never rely on it.

**Order of operations matters.** Pension and NHF are deducted before chargeable income; PAYE is then applied band-by-band to the result. Applying rent relief after banding, or taxing gross directly, produces materially wrong numbers.

## 3. Pension (Contributory — Pension Reform Act / PenCom)
- **Base:** basic + housing + transport ("pensionable emoluments").
- **Rate:** minimum **8% employee / 10% employer**. An employer may elect to bear the full contribution, in which case it must be at least 20% of monthly pay.
- **Remit to:** each employee's chosen **Pension Fund Administrator (PFA)**, with full contribution schedules for **PenCom** reporting.
- **Deadline:** within **7 working days** after salary payment. Note this is working days from payment, *not* the 7th of the month — a common misstatement.
- **Penalty:** not less than 2% of the unpaid amount.

## 4. National Housing Fund (NHF)
- **Base:** basic salary.
- **Rate:** **2.5%** (employee).
- **Remit to:** **Federal Mortgage Bank of Nigeria (FMBN)**, per employee. Contribution certificates on demand.
- **Deadline:** within **one month** of salary payment.
- **Penalty:** ₦50,000 for late remittance.

## 5. NHIS / NHIA — Health Insurance
- Employer + employee health-scheme contributions per the **applicable state or federal** health insurance scheme (coverage now broadly mandatory under the NHIA Act).
- Deduction receipts feed directly into payslips.
- Rate varies by scheme — resolve per applicable scheme; **do not assume a single national number.**

## 6. NSITF — Employee Compensation (Employees' Compensation Act 2010)
- **Rate:** **1% of total monthly payroll**, **employer-borne**. Not deducted from employee salary.
- **Payroll definition** for this purpose excludes pension contributions, bonuses, overtime, and one-off payments such as 13th-month income. Do not reuse the PAYE gross here.
- **Deadline: monthly**, before the **16th day of the month following salary payment.**
- **Penalty:** 10% of the unremitted amount.
- **Applicability:** every employer with at least one employee. No minimum headcount, no sector exemption. Armed Forces members are exempt from the scheme.
- Tracked as a **company-side statutory cost**, separate from employee deductions.

## 7. Industrial Training Fund (ITF)
- **Rate:** **1% of annual payroll**, for **qualifying employers** (commonly employers with 5+ staff or ≥ ₦50m annual turnover — confirm the current qualification test).
- **Deadline:** annual, on or before **1 April** of the following year.
- Employer-borne. Non-compliance forfeits the right to claim the 50% contribution refund.
- Provide filing reminders well ahead of the deadline.

## 8. Withholding Tax (WHT) on contractors / vendors
- Automatic WHT calculation + **certificate generation** for contractor and vendor payments.
- **Rates applied by service category** (commonly 5% or 10% depending on transaction type — resolve by category; do not apply a flat rate).
- **Deadline:** by the **21st day** of the month following deduction.
- Closes a gap most payroll-only tools ignore. Note the reform's penalty exposure for engaging unregistered contractors — validate vendor TIN too.

## 9. State-level & multi-state PAYE
- PAYE is **collected by each state's Internal Revenue Service (SIRS)**, based on **employee state of residence**.
- Engine must: map every employee to state of residence → generate **state-specific filing schedules** → consolidate remittance evidence across every state the employer operates in.
- **Deadline:** within **10 days** of the following month.
- Context: the Joint Tax Board rebranded to the **Joint Revenue Board**; the shift to a digitally-enabled **Nigeria Revenue Service** means payroll, bank records, and filings are cross-referenced more closely — enforcement is increasingly automated.
- 36 states + FCT each administer PAYE locally. A multi-state workforce means reconciling with multiple authorities every cycle; this fragmentation is a core product problem, not an edge case.

## 10. Quick-reference matrix

| Scheme | Base | Rate | Borne by | Authority | Deadline |
|---|---|---|---|---|---|
| PAYE | Annual chargeable income (cumulative) | 0–25% progressive | Employee (withheld) | State IRS (residence) / NRS | 10th of following month + annual returns |
| Pension | Basic + housing + transport | 8% EE / 10% ER (min) | Both | Employee's PFA (→ PenCom) | Within 7 working days of payment |
| NHF | Basic salary | 2.5% | Employee | FMBN | Within 1 month of payment |
| NHIS/NHIA | Per applicable scheme | Scheme-defined | Both | Applicable health scheme | Per scheme |
| NSITF | Total monthly payroll (as defined §6) | 1% | Employer | NSITF | Before 16th of following month |
| ITF | Annual payroll | 1% (qualifying employers) | Employer | ITF | On/before 1 April annually |
| WHT (contractors) | Contractor/vendor payment | By service category (e.g. 5%/10%) | Contractor (withheld) | NRS / State IRS | 21st of following month |

**Engine invariants to enforce:** cumulative-annual PAYE; TIN present before run; correct base per scheme (don't apply pension's base to NHF, or PAYE gross to NSITF); employer-side costs (NSITF, ITF, employer pension) tracked separately from employee deductions; state-of-residence routing for PAYE; every figure resolved from the versioned rule set.

## 11. Errata — known errors in the prototype

The July 2026 design prototype contains statutory errors. **Do not port these into production.**

| Location | Prototype says | Correct | Note |
|---|---|---|---|
| `SCHEMES` → NSITF | `deadline: '31 Mar annually'` | Monthly, before the 16th of the following month | Almost certainly ITF's annual cadence bleeding across. NSITF is a monthly obligation with a 10% late penalty; treating it as annual would leave a client eleven months out of compliance. |
| `SCHEMES` → Pension | `deadline: '7th monthly'` | Within 7 working days of salary payment | "7 working days from payment" ≠ "the 7th of the month". For late-month paydays the prototype's version is materially wrong. |
| `SCHEMES` → NHF | `deadline: '15th monthly'` | Within one month of salary payment | The prototype is stricter than the law; harmless in practice but incorrect as a stated rule. |

Also note the prototype's copy calls the framework both "Nigeria Tax Act 2025" (correct — the Act as named and signed) and "Nigeria Tax Act 2026 framework" (the effective date). Standardise on **"Nigeria Tax Act 2025, effective 1 January 2026"** in client-facing material.

## 12. Golden-test cases

Lock the engine against these. CI must fail if any regress.

**Band boundaries** — run chargeable income at and either side of each edge: ₦800,000 · ₦3,000,000 · ₦12,000,000 · ₦25,000,000 · ₦50,000,000. Verify the marginal rate applies only to the slice in each band.

**Worked example** (validated against a public guide): chargeable income ₦3,162,000 → first ₦800,000 @ 0% = ₦0; next ₦2,200,000 @ 15% = ₦330,000; remaining ₦162,000 @ 18% = ₦29,160; total ₦359,160.

**Other required cases:**
- Rent relief exactly at the ₦500,000 cap, and rent high enough that 20% exceeds it.
- Zero rent paid (relief = 0).
- Chargeable income below ₦800,000 → PAYE = 0, not negative.
- Mid-year pay change → cumulative recompute produces the correct year-to-date position, not a naïve monthly slice.
- Employee with no TIN → run is blocked, not silently processed.
- Each scheme applied to its own base: pension on basic+housing+transport, NHF on basic only, NSITF on total monthly payroll excluding bonuses/overtime/13th month.
- Employer-side costs never appear in the employee deduction total.
- Multi-state workforce → per-state PAYE liability sums to the org total.

**Property tests:** sum of per-band tax ≤ chargeable income; net pay ≤ gross; no negative deduction; monthly figures × 12 reconcile to the annual computation within rounding tolerance.

**Scenarios not yet specified.** Proration (new hire, termination, mid-period salary change), net-to-gross solving, retroactive pay, and payroll reversal all change the numbers and none is covered above. See `feature-backlog.md` §1 — each needs its own golden cases before the engine can be called complete. The retroactive-pay case carries an unresolved statutory question about which rule version applies to arrears, which must be answered before the data model is fixed.
