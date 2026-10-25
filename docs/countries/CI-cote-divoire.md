# Côte d'Ivoire (CI): draft rules matrix

| | |
|---|---|
| Status | **Draft.** Not reviewed. Not encoded; Côte d'Ivoire stays refused by the engine. |
| Prepared | 25 October 2026, from web research (mostly French-language sources) |
| Reviewer | Côte d'Ivoire tax adviser (to be named) |
| Currency | West African CFA franc, XOF, **no decimal places** (ISO 4217) |

**How to read this.** Each figure gives its source and whether the source is *official* (DGI, CNPS, the Code général des impôts, an ordonnance or a Finance Law) or *secondary* (a law firm, a news outlet, a payroll vendor or a calculator site). Almost every source found was secondary. The primary documents could not be opened from the environment this was prepared in, so the adviser must check every figure against the primary text before approval. **Conflicting** means sources disagree; **Unknown** means no reliable figure was found. Nothing here may be encoded until approved.

Côte d'Ivoire is the country least like Nigeria. Its salary tax depends on family status, and employers pay several separate levies. It must not be modelled as Nigerian deductions with French labels.

## 1. Salary tax: impôt sur les traitements et salaires (ITS)

Ordonnance No. 2023-719 merged the three former salary taxes into one progressive ITS from 2024. The three were the old ITS, the contribution nationale (CN) and the impôt général sur le revenu (IGR). One source says the tax applies to gross salary with no 20% abatement. *Secondary, consistent.*

Monthly schedule, the one most sources give (CGI article 119 bis, to be confirmed):

| Monthly gross taxable salary (XOF) | Rate |
|---|---|
| 0 to 75,000 | 0% |
| 75,001 to 240,000 | 16% |
| 240,001 to 800,000 | 21% |
| 800,001 to 2,400,000 | 24% |
| 2,400,001 to 8,000,000 | 28% |
| Above 8,000,000 | 32% |

- **Status:** consistent across several 2026 sources. One salary calculator shows a different schedule, which is probably stale.
- **Family reduction (RICF, CGI article 120):** a tax reduction that replaced the family quotient.
  - 5,500 XOF per half-share above one share, up to 5 shares, so at most 44,000 XOF a month.
  - Shares depend on marital status and dependent children. *Secondary (AfricaPaieRH, macalculatriceenligne).*
- **Declaration and payment deadline:** **Unknown**; not captured.

## 2. Employer and employee contributions (CNPS)

| Branch | Employee | Employer | Ceiling | Source |
|---|---|---|---|---|
| Retirement | 6.3% | 7.7% | **Conflicting**: 3,375,000 XOF a month (CLEISS, rates at 1 January 2025; one other site) vs 1,647,315 XOF a month (a 2026 source). One site shows 70,000 XOF, apparently stale. | Several (*secondary*); one site's 3.2% / 4.8% contradicts the rest |
| Family benefits | None | **Conflicting**: 5% (CLEISS 2025) or 5.75% (a 2026 source) | **Unknown** | *Secondary* |
| Maternity | None | 0.75% (CLEISS only) | **Unknown** | *Secondary (public body)* |
| Work accidents | None | 2% to 5%, by risk class; can be revised for the employer's claims record | **Unknown** | *Secondary*, consistent |
| Universal health cover (CMU) | **Unknown** split | **Unknown** split | Flat 1,000 XOF per person a month | CLEISS (*secondary*) |

- **Possible reconciliation:** 5% family benefits plus 0.75% maternity equals 5.75%. That may be the same charge reported two ways. This is a hypothesis for the adviser to check, not a finding.
- **CNPS deadline:** **Unknown.**

## 3. Employer payroll levies

| Levy | Rate | Status |
|---|---|---|
| Apprenticeship tax (FDFP) | 0.4% of gross pay | Africarrières, Deel. **Conflicting**: Rivermate FR gives 0.5%. |
| Continuing-training tax (FDFP) | 0.6% + 0.6% (1.2% in total) | Africarrières, Deel. **Conflicting**: Rivermate FR gives 1.5%. |
| Employer tax on salaries | 2.8% for local staff, 12% for expatriates, on total taxable pay | Rivermate EN (July 2025). **Conflicting**: Rivermate FR gives 1.2% and 10.4%; Deel doesn't list it. |

## 4. VAT

- **Standard rate:** 18%. Several exemptions were removed by the 2026 Finance Law. *Secondary (Bloomberg Tax).*
- **Reduced rate:** 9% for certain agricultural and livestock products and inputs that were previously exempt. *Secondary (Deloitte).*
- **Legal basis and date:** the tax annex to Finance Law No. 2025-987 of 19 December 2025, effective **5 January 2026**. *Secondary (HILI Conseil via AllAfrica).*
- **Registration threshold:** **Unknown.** A 500 million XOF turnover figure appears only as the line between monthly and quarterly returns (PayPro Global), not as a registration threshold.
- **Foreign online platforms:** 30% tax on a deemed profit of 10% of annual turnover, when Ivorian turnover is at least 50 million XOF. *Secondary (Deloitte).*

## 5. Withholding tax

- **Non-commercial profits:** the 2026 Finance Law extends the 7.5% rate on non-commercial profits paid to certain non-salaried participants. *Secondary (Bloomberg Tax).*
- **Other rates:** **unknown**; not captured.

## 6. Corporate income tax

- **Rate:** about 25%, from a single consultancy blog. **Unverified.**

## 7. What Plutus would need

- **Currency:** XOF has no minor unit; every amount and rounding step works in whole francs. The foundation already records XOF's exponent as 0.
- **Employee data:**
  - marital status and the number of dependent children, to compute shares for the family reduction. Plutus doesn't hold these today, so they need new, audited employee fields before ITS can be calculated;
  - an expatriate flag, for the employer tax on salaries.
- **Employer-only lines:** family, maternity, work accidents (with a rate per employer), training levies and the salary tax. None of them maps onto Nigeria's NSITF or ITF.
- **Flat per-head charge:** CMU, alongside percentage contributions.
- **Ceilings:** different per CNPS branch; the engine needs a ceiling for each line.

## 8. Questions for the adviser

1. Is the six-band ITS schedule current, and what is the exact base (gross, or after any deduction)?
2. How are shares counted for the RICF, and which employee records prove them?
3. What are the 2026 CNPS ceilings for each branch?
4. Are family benefits 5% plus 0.75% maternity, or 5.75% in total?
5. How is CMU split between employer and employee?
6. What are the current FDFP training levy rates and the employer salary tax rates?
7. What are the ITS, CNPS and VAT deadlines?
8. What are the VAT registration rules and the withholding tax schedule?
9. How are ITS and contributions rounded?

## Sources

- AfricaPaieRH, *Calcul de l'ITS en Côte d'Ivoire 2026* and *Cotisations sociales et impôts en Côte d'Ivoire*: https://africapaierh.com/blog/calcul-its-cote-divoire-2026/ and https://africapaierh.com/juridique/cotisations-sociales-et-impots-en-cote-divoire/
- Kabomal, *Impôt sur salaire en Côte d'Ivoire 2026: barème ITS et déclaration DGI*: https://kabomal.com/guide/impot-salaire-cote-divoire-bareme-its-declaration-dgi/
- macalculatriceenligne, ITS and CNPS calculators: https://macalculatriceenligne.com/afrique/calcul-ir-cote-ivoire/ and https://macalculatriceenligne.com/afrique/calcul-cnps-cote-ivoire/
- CLEISS, *Les cotisations en Côte d'Ivoire*: https://www.cleiss.fr/docs/cotisations/cotedivoire.html
- Afrotools, *Cotisations CNPS Côte d'Ivoire*: https://afrotools.com/blog/cotisations-cnps-cote-divoire/
- iambeezy, *CNPS cotisations 2026*: https://blog.iambeezy.app/fr/cnps-cotisations-2026/
- Rivermate, *Côte d'Ivoire employment cost calculator* (English and French): https://rivermate.com/guides/cote-divoire/employment-cost-calculator and https://rivermate.com/fr/guides/cote-divoire/calculateur-cout-employe
- Africarrières, *Charges employeur*: https://africarrieres.com/cote-divoire/fr/guide/employeur-entreprise/charges-employeur
- Deel, *Hire and pay employees in Côte d'Ivoire*: https://www.deel.com/employees/ivory-coast
- Bloomberg Tax, *Côte d'Ivoire tax agency posts 2026 Finance Law tax annex*: https://news.bloombergtax.com/daily-tax-report-international/cote-divoire-tax-agency-posts-2026-finance-law-tax-annex
- Deloitte Société d'Avocats, *Côte d'Ivoire: les principales mesures de la loi de finances pour 2026*: https://blog.avocats.deloitte.fr/cote-divoire-les-principales-mesures-de-la-loi-de-finances-pour-2026/
- HILI Conseil via AllAfrica, *Fiscalité 2026*: https://fr.allafrica.com/stories/202601160291.html
- PayPro Global, *Côte d'Ivoire*: https://payproglobal.com/fr/taxe-de-vente-saas/cote-divoire/
- Kolonell, *Fiscalité entreprise Côte d'Ivoire 2026*: https://kolonell.com/fr/blog/fiscalite-entreprise-cote-ivoire-tva-impots-2026
