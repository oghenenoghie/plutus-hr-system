# Country rules: the drafts behind each country's payroll

These are the rules matrices for the five countries Plutus supports after Nigeria. **On 27 October 2026 Plutus Technologies approved their payroll rules as drafted, without a local tax adviser's review**, and they are encoded in `app/compliance/engine/countries/` (Stage 3 of Part 3 in `docs/architecture/multicountry-tax.md`). Every figure the drafts found consistent, or that an official source settled, is built in. A figure marked **conflicting** or **unknown** is a Tax Setting, unless an official source or the law's own timetable settled it (each module says which): each organisation enters it, choosing among the values the sources give where there are any, and its payroll is refused until it has. VAT, withholding tax and corporate tax for these countries remain drafts and are still refused.

| Country | File | Payroll | Rule set |
|---|---|---|---|
| The Gambia | [GM-the-gambia.md](GM-the-gambia.md) | Active, owner-approved | `GM-2026.1`, `app/compliance/engine/countries/gm.py` |
| Rwanda | [RW-rwanda.md](RW-rwanda.md) | Active for 2026 and 2027, owner-approved | `RW-2026.1` and `RW-2027.1`, `app/compliance/engine/countries/rw.py` |
| Kenya | [KE-kenya.md](KE-kenya.md) | Active from February 2026, owner-approved | `KE-2026.1`, `app/compliance/engine/countries/ke.py` |
| Ghana | [GH-ghana.md](GH-ghana.md) | Active from 1 September 2026, owner-approved | `GH-2026.2`, `app/compliance/engine/countries/gh.py` |
| Côte d'Ivoire | [CI-cote-divoire.md](CI-cote-divoire.md) | Active, owner-approved | `CI-2026.1`, `app/compliance/engine/countries/ci.py` |

The questions for the adviser at the end of each file are still open. An adviser's answer can replace a Tax Setting with a built-in figure in a new rule set version, from a date; payslips already locked keep what they used.

## How these were prepared

- Researched on 25 October 2026 by web search.
- The tax authorities' own sites (KRA, GRA Ghana, RRA, GRA Gambia, DGI) and PwC's tax summaries couldn't be opened from the environment the drafts were prepared in. Most figures therefore come from secondary sources: Big Four alerts, law firms, payroll vendors and news reports.
- Each figure says whether its source is **official** or **secondary**.
- Where sources disagree, the figure is marked **conflicting** and every version is shown. Where nothing reliable was found, it's marked **unknown**. Nothing was filled in by guesswork.

## How a country goes live

There are two routes, and both end in a rule set registered in `app/compliance/engine/countries/` and the country `active` in the catalogue.

**Adviser-reviewed** (`ApprovalBasis.ADVISER_REVIEWED`):

1. **Review.** The country's adviser checks every figure against the primary text (the Act, gazette, regulations or authority notice):
   - correcting it, or confirming it, with the primary reference and its effective date;
   - answering the questions at the end of the file;
   - supplying missing schedules (for example withholding tax for The Gambia).

   The country moves to `in_review` while this happens.
2. **Test vectors.** The adviser signs off worked examples, in the country's currency, covering each band edge, each ceiling and floor, and each effective-date change.
3. **Engine.** The rule set is written from the approved figures only, each rule citing its primary source. The signed-off examples become its golden tests. The engine refuses it unless it is `active`, reviewed by the adviser, approved by someone other than its preparer, and every source it cites is the law or the authority's own publication.
4. **Release gate.** The checks in `docs/architecture/multicountry-tax.md` must pass, including posting and filing validation and a parallel run where practical.

**Owner-approved** (`ApprovalBasis.OWNER_APPROVED`), the route the five countries took:

1. **Approval.** The product owner approves the draft as it stands. Sources may be secondary; each says whether it is official.
2. **Engine.** Consistent figures are built in, citing their sources. Conflicting and unknown figures become Tax Settings, offering only values a source gave. Hand-worked payslips test the rule set (`tests/unit/test_country_rules.py`).
3. **Payroll switches on.** Organisations in the country get payroll once an admin has entered its Tax Settings.

## What the drafts show the engine needs

The engine supports these, and the five countries' rule sets use them. Employees' family shares and expatriate status are recorded on their records (Stage 2a). Not yet supported: benefits in kind (Gambia fringe benefits tax), annual per-person charges (Gambia expatriate quota), and a cumulative table that changes mid-year.

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
