# Ghana (GH): draft rules matrix

| | |
|---|---|
| Status | **Payroll active, owner-approved.** Approved by Plutus Technologies on 27 October 2026 without a local tax adviser's review, and encoded as `GH-2026.2` in `app/compliance/engine/countries/gh.py`. Figures below marked conflicting or unknown became Tax Settings each organisation enters, unless an official source settled them; `gh.py` says which. VAT, withholding tax and corporate tax remain draft and are refused. |
| Prepared | 25 October 2026, from web research |
| Reviewer | Ghana tax adviser (to be named) |
| Currency | Ghanaian cedi, GHS, 2 decimal places (ISO 4217) |

**How to read this.** Each figure gives its source and whether the source is *official* (GRA, SSNIT, a gazette or Act) or *secondary* (a Big Four firm, a law firm, a news outlet or a payroll vendor). The primary documents could not be opened from the environment this was prepared in, so the adviser must check every figure against the primary text before approval. **Conflicting** means sources disagree; **Unknown** means no reliable figure was found. The payroll figures were approved as drafted on 27 October 2026 (see Status); the rest still need review.

## 1. Employment income tax (PAYE)

The Income Tax (Amendment) Act 2026 (Act 1178) changed the resident individual bands. Assented 26 August 2026; GRA announced on 24 September 2026 that the new rates apply **from 1 September 2026**. *Official (GRA notice), corroborated by secondary sources.*

A pay period before 1 September 2026 uses the previous schedule (annual tax-free band GHS 5,880). That schedule wasn't captured in this research and must be supplied by the adviser if Plutus is to handle any 2026 period before September.

Annual bands from 1 September 2026, as reported:

| Annual chargeable income (GHS) | Rate | Status |
|---|---|---|
| First 7,056 | 0% | Consistent; GRA notice |
| Next 960 | 5% | Consistent, secondary |
| Next 1,200 | 10% | Consistent, secondary |
| Next 34,800 | 17.5% | Consistent, secondary |
| Next 192,000 | 25% | Consistent, secondary |
| From the end of the 25% band to 600,000 | 30% | **Conflicting.** Most sources go straight from 25% to 30%, but Regfollower reproduces a GRA-style table with 30% starting at GHS 408,000. TaxLawGH notes its band widths add up to GHS 605,000, not 600,000. |
| Above 600,000 | 35% | Secondary, consistent |

- **Monthly tax-free threshold:** GHS 588, described as the rounded monthly equivalent of the 2026 national minimum wage. *Secondary.*
- **Monthly table:** **Unknown.** GRA publishes PAYE in monthly bands; the monthly widths other than the threshold weren't found. Dividing the annual bands by 12 is not a substitute for the published table.
- **Deductions before tax:** **Unknown.** Whether the employee's SSNIT contribution is deductible, and any reliefs, weren't captured.
- **Remittance:** by the 15th of the following month. *Secondary, consistent.* Annual PAYE return by 31 March of the following year. *Secondary.*
- **Presumptive tax** (not payroll): Act 1178 also raises the turnover threshold from GHS 500,000 to GHS 750,000. *Secondary.*

## 2. Statutory contributions

| Scheme | Employee | Employer | Base and limits | Authority | Due | Source |
|---|---|---|---|---|---|---|
| Social security and pensions, 18.5% in total (National Pensions Act 2008, Act 766) | 5.5% | 13% | Basic salary. Ceiling **conflicting**: GHS 61,000 a year in one source, GHS 69,000 a month in another. | SSNIT (Tier 1) and a licensed corporate trustee (Tier 2) | 15th of the following month (*secondary*); one vendor says the 14th for SSNIT (**unverified**) | Several secondary sources; SSNIT Omnibus worked example (*official*, not a rate schedule) |

How the 18.5% is paid out is **conflicting**. The SSNIT Omnibus worked example, the most authoritative source found, pays:

- 13.5% of basic salary to SSNIT for Tier 1, of which SSNIT passes 2.5% to the National Health Insurance Authority;
- 5% of basic salary to the Tier 2 corporate trustee.

Other sources split it differently (for example 10% and 3%, or 10.5% and 2.5%), and one gives employer 8%. The Tier 2 deadline is **unknown**.

## 3. VAT

The VAT Act 2025 (Act 1151) took effect on **1 January 2026**. *Secondary (EY, Crowe), consistent.*

- **Rates:** VAT 15%, plus the NHIL and GETFund levies of 5% in total. The split between them, reported elsewhere as 2.5% each, is to be confirmed. GRA's own announcement (as reported by Graphic) describes the combined burden as "20 percent". *Secondary.*
- **Changes from 1 January 2026:**
  - the NHIL and GETFund levies are now deductible as input tax and no longer cascade;
  - the 1% COVID-19 levy is abolished;
  - the VAT Flat Rate Scheme is abolished.
- **Registration threshold:** GHS 750,000 for suppliers of goods, from a single secondary source (Kintsugi). The services threshold is **unknown**.
- **Filing deadline:** **Unknown**; not captured.

## 4. Withholding tax

Resident payer (other than an individual) paying a resident, on payments above GHS 2,000:

| Payment | Rate | Source |
|---|---|---|
| Supply of goods | 3% | PwC, UKGCC (*secondary*) |
| Supply of works | 5% | PwC, UKGCC (*secondary*) |
| Supply of services | 7.5% | PwC (*secondary*); PwC (December 2024) also lists 7.5% for services by individuals |

Payments to non-residents:

| Payment | Rate | Source |
|---|---|---|
| Goods, works or services | 20% | GRA table (*official*, via search summary) |
| Dividends | 8% | GRA table (*official*, via search summary) |
| Royalties, natural resource payments and rents | 15% | GRA table (*official*, via search summary) |

- **Remittance:** within 15 days after the end of the month. *Secondary.*
- **Watch:** the Ministry of Finance said it would review the GHS 2,000 threshold. No change was found.

## 5. Corporate income tax

- **Standard rate:** 25% is widely quoted, but none of the sources captured states it. **Unverified.**

## 6. What Plutus would need

- **Contribution base:** basic salary, not gross. Plutus already stores basic separately.
- **Two payees for one contribution:** SSNIT (Tier 1) and a trustee chosen by the employer (Tier 2), each a separate liability with its own deadline.
- **Effective dating:** a version boundary at 1 September 2026, inside a tax year. Any cumulative or annualised PAYE method must handle the change mid-year; the adviser should say how GRA expects September to December 2026 to be computed.
- **VAT levies:** a separate line from VAT on every invoice, for both sales and purchases.
- **WHT:** the GHS 2,000 per-payment threshold and the goods / works / services classification must be recorded on each bill.
- **Employee data:** a TIN and SSNIT number for each employee, plus the Tier 2 trustee for the organisation. Confirm which identifiers GRA and SSNIT require.

## 7. Questions for the adviser

1. What is the full monthly PAYE table from 1 September 2026, and where does the 30% band start?
2. What was the schedule from 1 January to 31 August 2026?
3. Is the employee's 5.5% SSNIT contribution deductible before PAYE? Are there other reliefs?
4. What is the current SSNIT ceiling, and the exact Tier 1 / NHIA / Tier 2 split?
5. What is the Tier 2 remittance deadline?
6. What are the VAT registration threshold for services and the VAT return deadline under Act 1151?
7. Is the 25% corporate rate current?

## Sources

- GRA, *Amendments: Income Tax (Amendment) Act, 2026 (Act 1178)*: https://gra.gov.gh/news/portfolio/amendments-income-tax-act-2026-act-1178/
- Mercans, *Ghana revised personal income tax (PAYE) rates, 1 September 2026*: https://mercans.com/resources/statutory-alerts/ghana-revised-personal-income-tax-paye-rates-1st-september-2026/
- Regfollower, *Ghana revises individual income tax rates*: https://regfollower.com/ghana-revises-individual-income-tax-rates/
- GhanaWeb, *Review of the Income Tax (Amendment) Act, 2026 (Act 1178)*: https://www.ghanaweb.com/GhanaHomePage/features/Review-of-the-Income-Tax-Amendment-Act-2026-Act-1178-and-its-impact-on-taxpayers-2053492
- TaxLawGH (MSL Business School), *Ghana tax rates* and *deadline calculator*: https://www.taxlawgh.com/ghana-tax-rates and https://www.taxlawgh.com/ghana-tax-deadline-calculator
- SSNIT, *Omnibus*: https://www.ssnit.org.gh/wp-content/uploads/2023/08/SSNIT-Omnibus.pdf
- EY, *Ghana's Parliament enacts several indirect tax-related laws effective 1 January 2026*: https://taxnews.ey.com/news/2026-0163-ghanas-parliament-enacts-several-indirect-tax-related-laws-effective-1-january-2026
- Crowe Ghana, *VAT reform 2026*: https://www.crowe.com/gh/news/ghana-vat-reform-2026
- Graphic Online, *GRA announces overhaul: VAT rate cut, flat rate scheme scrapped, COVID levy abolished*: https://www.graphic.com.gh/business/business-news/gra-announces-overhaul-vat-rate-cut-flat-rate-scheme-scrapped-covid-levy-abolished-from-jan-1.html
- US Trade.gov, *Ghana finance: value added tax changes*: https://www.trade.gov/market-intelligence/ghana-finance-value-added-tax-changes
- Kintsugi, *Ghana VAT guide*: https://trykintsugi.com/sales-tax-guides/africa/ghana
- PwC Worldwide Tax Summaries, Ghana withholding taxes: https://taxsummaries.pwc.com/ghana/corporate/withholding-taxes
- GRA withholding tax pages returned by the search: https://gra.gov.gh/?p=8844 and https://gra.gov.gh/?p=6194
- UKGCC, *Withholding tax in Ghana*: https://ukgcc.com.gh/bfd_download/withholding-tax-in-ghana-what-businesses-need-to-know
- Rivermate, *Ghana taxes* (deadlines): https://rivermate.com/fr/guides/ghana/impots
