# Country rules: drafts awaiting review

These are the draft rules matrices for the five countries Plutus plans to support after Nigeria. **None of them is approved, and the engine refuses payroll and statutory tax for every one of these countries** (`TaxStatus.DRAFT` in `app/compliance/multicountry.py`). An organisation can already choose any of them and run in its currency; only payroll waits. Nothing in these files is encoded as a rule.

| Country | File | Reviewer | Status |
|---|---|---|---|
| The Gambia | [GM-the-gambia.md](GM-the-gambia.md) | Gambia tax adviser (to be named) | Draft |
| Rwanda | [RW-rwanda.md](RW-rwanda.md) | Rwanda tax adviser (to be named) | Draft |
| Kenya | [KE-kenya.md](KE-kenya.md) | Kenya tax adviser (to be named) | Draft |
| Ghana | [GH-ghana.md](GH-ghana.md) | Ghana tax adviser (to be named) | Draft |
| Côte d'Ivoire | [CI-cote-divoire.md](CI-cote-divoire.md) | Côte d'Ivoire tax adviser (to be named) | Draft |

## How these were prepared

- Researched on 25 October 2026 by web search.
- The tax authorities' own sites (KRA, GRA Ghana, RRA, GRA Gambia, DGI) and PwC's tax summaries couldn't be opened from the environment the drafts were prepared in. Most figures therefore come from secondary sources: Big Four alerts, law firms, payroll vendors and news reports.
- Each figure says whether its source is **official** or **secondary**.
- Where sources disagree, the figure is marked **conflicting** and every version is shown. Where nothing reliable was found, it's marked **unknown**. Nothing was filled in by guesswork.

## How a country goes live

1. **Review.** The country's adviser checks every figure against the primary text (the Act, gazette, regulations or authority notice):
   - correcting it, or confirming it, with the primary reference and its effective date;
   - answering the questions at the end of the file;
   - supplying missing schedules (for example withholding tax for The Gambia).

   The country moves to `in_review` while this happens.
2. **Test vectors.** The adviser signs off worked examples, in the country's currency, covering each band edge, each ceiling and floor, and each effective-date change.
3. **Engine.** The country's rule set is written for the country-neutral payroll engine (`app/compliance/engine/`, Part 3 of `docs/architecture/multicountry-tax.md`) from the approved figures only, each rule citing its primary source. The signed-off examples become its golden tests. The engine refuses the rule set unless it is `active`, reviewed by the adviser, approved by someone other than its preparer, and every source it cites is the law or the authority's own publication.
4. **Release gate.** The checks in `docs/architecture/multicountry-tax.md` must pass, including posting and filing validation and a parallel run where practical. Only then does the country become `active`.
5. **Payroll switches on.** Organisations already in that country get payroll the moment it becomes `active`; nothing else changes for them.

## What the drafts show the engine needs

The engine (stage 1 of Part 3) now supports these as mechanisms, tested with fictional figures; none of the countries' figures is encoded. It takes family shares and expatriate status as inputs, but Plutus doesn't record them for employees yet (stage 2). Not yet supported: benefits in kind (Gambia fringe benefits tax), annual per-person charges (Gambia expatriate quota), and a cumulative table that changes mid-year.

- **Currencies without minor units.** RWF and XOF have none. The foundation already handles this in `app/domain/money.py`.
- **Contribution bases differ by country and by line:**
  - gross pay (Kenya SHIF and Housing Levy, Rwanda pension);
  - basic salary (Ghana SSNIT, Gambia NPF);
  - basic plus fixed allowances (Gambia IICF);
  - net pay (Rwanda CBHI);
  - tiered bands between a lower and an upper limit (Kenya NSSF).
- **Floors, caps and flat amounts:**
  - a minimum (Kenya SHIF, KES 300);
  - per-line ceilings (Côte d'Ivoire CNPS);
  - a flat cap (Gambia IICF, GMD 15);
  - per-head charges (Kenya NITA, Côte d'Ivoire CMU).
- **Tax credits as well as deductions:** Kenya's personal relief and Côte d'Ivoire's family reduction (RICF) reduce tax, not income.
- **Mid-year rule changes:** Kenya NSSF changes with February pay, Ghana PAYE from 1 September 2026, and Rwanda pension every January from 2027 to 2030.
- **One contribution, two payees:** Ghana's SSNIT Tier 1 and the Tier 2 trustee.
- **Employee data Plutus doesn't hold today:**
  - marital status and dependent children (Côte d'Ivoire ITS);
  - nationality or expatriate status (Gambia expatriate quota, Côte d'Ivoire employer salary tax);
  - benefits in kind (Gambia fringe benefits tax).
