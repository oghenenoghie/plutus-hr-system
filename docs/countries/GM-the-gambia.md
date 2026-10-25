# The Gambia (GM): draft rules matrix

| | |
|---|---|
| Status | **Draft.** Not reviewed. Not encoded; The Gambia stays refused by the engine. |
| Prepared | 25 October 2026, from web research |
| Reviewer | Gambia tax adviser (to be named) |
| Currency | Gambian dalasi, GMD, 2 decimal places (ISO 4217) |

**How to read this.** Each figure gives its source and whether the source is *official* (GRA, SSHFC, a gazette or Act) or *secondary* (a law firm, a news outlet or a payroll vendor). The primary documents could not be opened from the environment this was prepared in, so the adviser must check every figure against the primary text before approval. **Conflicting** means sources disagree; **Unknown** means no reliable figure was found. Of the five countries, The Gambia has the thinnest published detail, so expect more gaps here. Nothing here may be encoded until approved.

## 1. Employment income tax (PAYE)

- **Tax-free threshold:** GMD 36,000 a year (GMD 3,000 a month), unchanged from 1 January 2026. *Secondary (Rivermate; Afrotools citing GRA), consistent.*
- **Bands:** **conflicting.**
  - Rivermate gives, per year:

    | Annual income (GMD) | Rate |
    |---|---|
    | 0 to 36,000 | 0% |
    | 36,001 to 46,000 | 5% |
    | 46,001 to 56,000 | 10% |
    | 56,001 to 66,000 | 15% |
    | 66,001 to 76,000 | 20% |
    | Above 76,000 | 35% |

  - Afrotools gives bands from 0% to 25%, and says GRA's PAYE brochure labels its schedule as effective from January 2018.

  Neither is a GRA primary document. The schedule must come from the adviser or the Income Tax Act.
- **Fringe benefits tax:** 27% on employer-provided benefits such as housing and vehicles. *Secondary (Afrotools citing GRA).* Whether the employer pays it, and on what valuation, is **unknown**.
- **Remittance:** by the 15th of the following month. *Secondary.*

## 2. Statutory contributions

| Scheme | Employee | Employer | Base and limits | Authority | Due | Source |
|---|---|---|---|---|---|---|
| National Provident Fund (NPF) | 5% | 10% | Basic salary | SSHFC | 15th of the following month | Employer guide citing SSHFC (*secondary*). **Conflicting**: Rivermate gives 10% employee and 10% employer. |
| Industrial Injuries Compensation Fund (IICF) | None | 1%, capped at GMD 15 per employee a month | Total earnings: basic salary plus fixed allowances | SSHFC | **Unknown** | Single employer guide (*secondary*) |

- **Expatriate quota:** GMD 10,000 for an ECOWAS national and GMD 50,000 for a non-ECOWAS national, per non-Gambian employee. *Secondary (Rivermate).* The period it covers (annual is assumed by most guides) and the collecting body are **unknown**.

## 3. VAT

- **Rates:** standard 15%; 0% on exports of goods and services. *Official (GRA FAQ).*
- **Registration:** compulsory at GMD 2 million of taxable supplies in a tax year; voluntary from GMD 1 million. *Official (GRA FAQ)*, corroborated by Afrotools checking GRA in August 2026. TaxAtlas gives GMD 1 million as the threshold; the GRA figure is preferred.
- **Filing deadline:** **Unknown**; not captured.

## 4. Withholding tax

**Unknown.** No rates were found. The GRA document that mentions withholding tax was cut off before the details. The adviser should supply the full schedule.

## 5. Corporate income tax

- **Rate:** the higher of 27% of net profit, or 1% of turnover on audited accounts (2% of turnover if the accounts are unaudited). *Official (GRA FAQ).*

## 6. What Plutus would need

- **Contribution bases:**
  - NPF uses basic salary;
  - IICF uses basic plus fixed allowances, with a flat cap.
  - Plutus would have to know which allowances count as fixed.
- **Fringe benefits:** a separate tax with its own base. Plutus doesn't record benefits in kind on payslips today.
- **Expatriate quota:** a per-employee charge that depends on nationality. Plutus doesn't hold employee nationality today.
- **Minimum turnover tax** in the corporate rate, if Plutus ever prepares corporate tax estimates (not currently in scope).

## 7. Questions for the adviser

1. What is the current PAYE schedule, and from what date?
2. What are the current NPF rates and base: employee 5% or 10%?
3. Are the IICF rate, its GMD 15 cap and its deadline confirmed?
4. How is fringe benefits tax valued, who pays it, and when?
5. How is the expatriate quota charged (period and payee)?
6. What are the withholding tax rates and the VAT return deadline?
7. Are employee NPF contributions deductible before PAYE?

## Sources

- GRA, *Domestic taxes FAQs*: https://www.gra.gm/domestic-faqs
- GRA document returned by the search (withholding tax, cut off): https://gra.gm/download-file/7f65dc7d-48f2-11ef-b086-029254d29bb1
- Afrotools, *Gambia employer payroll compliance 2026*: https://afrotools.com/blog/gambia-employer-payroll-compliance-2026/
- Afrotools, *PAYE calculator, The Gambia*: https://afrotools.com/fr/gambia/gm-paye
- Afrotools, *Gambia VAT filing guide 2026*: https://afrotools.com/blog/gambia-vat-filing-guide-2026/
- Rivermate, *The Gambia taxes*: https://rivermate.com/guides/gambia/taxes (and the Dutch employment cost page: https://rivermate.com/nl/gidsen/gambia/personeelskosten-calculator)
- Africarrières, *The Gambia social security* and *employer obligations*: https://africarrieres.com/gambia/en/guide/droit-du-travail/social-security and https://africarrieres.com/gambia/en/guide/employeur-entreprise/employer-obligations
- Playroll, *Employment cost in The Gambia*: https://www.playroll.com/employment-cost/the-gambia
- TaxAtlas, The Gambia VAT and corporate tax: https://taxatlas.io/country/gambia/vat-sales-tax and https://taxatlas.io/country/gambia/corporate-tax
