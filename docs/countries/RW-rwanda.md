# Rwanda (RW): draft rules matrix

| | |
|---|---|
| Status | **Payroll active, owner-approved.** Approved by Plutus Technologies on 27 October 2026 without a local tax adviser's review, and encoded as `RW-2026.1` and `RW-2027.1` in `app/compliance/engine/countries/rw.py`. Figures below marked conflicting or unknown became Tax Settings each organisation enters, unless an official source settled them; `rw.py` says which. VAT, withholding tax and corporate tax remain draft and are refused. |
| Prepared | 25 October 2026, from web research |
| Reviewer | Rwanda tax adviser (to be named) |
| Currency | Rwandan franc, RWF, **no decimal places** (ISO 4217) |

**How to read this.** Each figure gives its source and whether the source is *official* (RRA, RSSB, the Official Gazette or a Law) or *secondary* (a Big Four firm, a law firm, a news outlet or a payroll vendor). The primary documents could not be opened from the environment this was prepared in, so the adviser must check every figure against the primary text before approval. **Conflicting** means sources disagree; **Unknown** means no reliable figure was found. The payroll figures were approved as drafted on 27 October 2026 (see Status); the rest still need review.

## 1. Employment income tax (PAYE)

Law No. 027/2022 of 20 October 2022 establishing taxes on income set new brackets: three in its first year, then four. Orbitax reports the four-bracket schedule as effective from November 2023. *Secondary.*

| Monthly employment income (RWF) | Rate |
|---|---|
| 0 to 60,000 | 0% |
| 60,001 to 100,000 | 10% |
| 100,001 to 200,000 | 20% |
| Above 200,000 | 30% |

- **Status: conflicting.**
  - The RWF 60,000 threshold and the 30% top rate are consistent. PwC lists 30% from RWF 200,001 a month.
  - Some 2026 calculator guides still show the transitional three-band schedule (0% / 20% / 30%, with 30% from RWF 100,000).
  - Older guides show the pre-2023 RWF 30,000 threshold.
- **Law No. 051/2023** (5 September 2023) amended Law 027/2022 to cut the corporate rate. No source says it changed the personal brackets. *Official (RRA notice).*
- **Deductions before PAYE:** **Unknown.** One payroll vendor computes PAYE on gross pay and deducts pension and maternity contributions afterwards. That is the vendor's method, not a statutory statement.
- **Remittance:** PAYE and RSSB contributions, by the 15th of the following month, reportedly on a single declaration to RRA. *Secondary, consistent.*

## 2. Statutory contributions

| Scheme | Employee | Employer | Base and limits | Due | Source |
|---|---|---|---|---|---|
| RSSB pension | 6% | 6% | Gross pay including transport allowance, from January 2025 | 15th of the following month | Sage, PaySpace, New Times (*secondary*, consistent) |
| RSSB maternity leave | 0.3% | 0.3% | **Unknown** base | 15th | **Conflicting**: one source gives 0.3% employer and 0% employee |
| Community-based health insurance (CBHI) | 0.5% of **net** pay | None | Net pay; definition **unknown** | 15th of the following month, to RSSB (EY, *secondary*, checked 27 October 2026) | RRA's CBHI page (*official*, checked 27 October 2026), citing Prime Minister's Order No. 034/01 of 13/01/2020: 0.5% of net salary, deducted and paid by the employer |
| Occupational hazards | None | **Conflicting**: 2%, 1% or 0.5% | **Unknown** | **Unknown** | Secondary sources disagree |

**Pension rate schedule (scheduled increases).**

| Year | Total rate | Split |
|---|---|---|
| 2025 and 2026 | 12% | 6% employee, 6% employer |
| From January 2027 | 14% | Presidential Order No. 086/01 of 12 December 2024 (*official*, checked 31 October 2026). The order doesn't divide it; RSSB's FAQ (*official*) says employer and employee contribute equally. Encoded as `RW-2027.1`, with the employee's share a Tax Setting. |
| From January 2028 | 16% | Presidential Order No. 086/01 (*official*); split as above. Not encoded yet. |
| From January 2029 | 18% | Presidential Order No. 086/01 (*official*); split as above. Not encoded yet. |
| From January 2030 | 20% | Sage schedule, EY and Orbitax (*secondary*); split as above. Not encoded yet. |

An employer may choose to pay the employee's increase. Each year's increase needs its own rule version from 1 January; 2027's is `RW-2027.1`.

## 3. VAT

- **Rate:** standard 18%. *Secondary, consistent.*
- **Registration:** compulsory above RWF 20 million of taxable turnover in a year, or RWF 5 million in a calendar quarter (PwC, *secondary*). Registration is due within seven days after the period in which the threshold is passed (Afrotools, summarising RRA guidance; *secondary*).
- **Digital services:** RRA confirmed on 29 April 2026 that 18% VAT applies to non-resident business-to-consumer streaming, gaming and software providers (VATcalc, *secondary*). Whether the RWF 20 million test applies to them is unresolved.
- **Filing deadline:** **Unknown**; not captured.

## 4. Withholding tax

- **Outbound payments:** 15% on certain payments to foreign entities, including dividends, interest, royalties and service or management fees (Chambers, *secondary*).
- **Domestic rates:** **Unknown**; not captured. A May 2025 amendment to the income tax law reportedly changed withholding tax (HLB guide, *secondary*). The adviser should supply the current domestic schedule.

## 5. Corporate income tax

- **Standard rate:** 28%, cut from 30% by Law No. 051/2023 (published 5 September 2023). *Official (RRA notice).*

## 6. What Plutus would need

- **Currency:** RWF has no minor unit. Every amount, rounding step and journal line works in whole francs. The foundation already records RWF's exponent as 0.
- **Schedules by year:** the pension rate changes every January from 2027 to 2030, so each year needs its own effective-dated rule version.
- **Contribution bases:**
  - gross pay including transport, for pension;
  - net pay, for CBHI.
  - CBHI therefore has to run after PAYE and pension, which is a different order from Nigeria's.
- **Liabilities:** one combined RRA declaration (PAYE and RSSB) in place of Nigeria's separate payees. Whether CBHI is part of it is to be confirmed.
- **Employee data:** a TIN and RSSB number for each employee. Confirm which identifiers RRA requires.

## 7. Questions for the adviser

1. Is the four-band schedule (0 / 10 / 20 / 30%, cut-offs 60,000 / 100,000 / 200,000) in force for 2026?
2. Are the employee's pension and maternity contributions deductible before PAYE?
3. What are the current maternity, CBHI and occupational hazard rates, bases and deadlines?
4. How is "net pay" defined for CBHI?
5. How will the 2027–2030 pension increases split between employer and employee?
6. What are the domestic withholding tax rates after the May 2025 amendment, and the VAT return deadline?
7. How does RRA round PAYE: to the franc, and at which step?

## Sources

- Presidential Order No. 086/01 of 12 December 2024 on the pension scheme, official text (ILO NATLEX copy): https://natlex.ilo.org/dyn/natlex2/natlex2/files/download/117567/RWA-117567.pdf (checked 31 October 2026)
- RSSB, *Frequently asked questions*: https://www.rssb.rw/uploads/RSSB_FAQS_All_languages_2_760b75b195.pdf (checked 31 October 2026)
- RRA, *CBHI contribution*: https://www.rra.gov.rw/en/domestic-tax-services/rssb-contributions/cbhi-contribution (checked 27 October 2026)
- EY, *Rwanda establishes subsidy contributions from employees for community-based health insurance scheme*: https://globaltaxnews.ey.com/news/2020-5351-rwanda-establishes-subsidy-contributions-from-employees-for-community-based-health-insurance-scheme (checked 27 October 2026)
- RRA, notices on the 2023 annual income tax declaration and Law No. 051/2023: https://www.rra.gov.rw/en/details?tx_news_pi1%5Baction%5D=detail&tx_news_pi1%5Bcontroller%5D=News&tx_news_pi1%5Bnews%5D=1731&cHash=d42a800abccbda53ef5e9c5b5018f83d and https://www.rra.gov.rw/en/details?tx_news_pi1%5Baction%5D=detail&tx_news_pi1%5Bcontroller%5D=News&tx_news_pi1%5Bnews%5D=1758&cHash=d60ebaef49cf4238f9b93787c04274a0
- Orbitax, *Rwanda's new personal income tax brackets/rates effective November 2023*: https://orbitax.com/news/archive.php/Rwandas-New-Personal-Income-T-54125
- Orbitax, *Rwanda's new income tax law includes several new and revised measures*: https://orbitax.com/news/archive.php/Rwandas-New-Income-Tax-Law-In-51298
- UNU-WIDER, *Evaluating the impact of the 2023–2024 personal income tax reform in Rwanda*: https://www.wider.unu.edu/sites/default/files/Publications/Working-paper/PDF/wp2023-73-evaluating-impact-personal-income-tax-reform-Rwanda.pdf
- PwC Worldwide Tax Summaries, Rwanda (personal income; other taxes): https://taxsummaries.pwc.com/rwanda/individual/taxes-on-personal-income and https://taxsummaries.pwc.com/rwanda/corporate/other-taxes
- Open Accountants, *RW income tax*: https://www.openaccountants.com/skills/rw-income-tax
- HLB Rwanda, *Tax guide 2025/2026*: https://www.hlbrwanda.com/wp-content/uploads/2026/02/HLB-Rwanda-Tax-Guide-20252026.pdf
- Sage, *Rwanda 2025 pension reforms*: https://communityhub.sage.com/za/sage-payroll-professional/f/announcements/238486/rwanda-2025-pension-reforms
- PaySpace, *Rwanda pension reforms effective January 2025*: https://support.payspace.com/portal/en/kb/articles/rwanda-pension-reforms-effective-january-2025
- The New Times, *Your pension doubled and that smaller pay slip is good news*: https://www.newtimes.co.rw/article/37752/opinions/your-pension-doubled-and-that-smaller-pay-slip-is-good-news/amp
- Playroll, *Payroll and employment taxes in Rwanda*: https://www.playroll.com/payroll/rwanda
- Rivermate, *Rwanda taxes*: https://www.rivermate.com/guides/rwanda/taxes
- Africarrières, *Rwanda employer charges*: https://africarrieres.com/rwanda/en/guide/employeur-entreprise/charges-employeur
- Afrotools, *Rwanda VAT guide 2026*: https://afrotools.com/blog/rwanda-vat-guide-2026/
- VATcalc, Rwanda: https://www.vatcalc.com/tag/rwanda/
- AllAfrica, *Rwanda's online VAT regime raises compliance questions early*: https://allafrica.com/stories/202609150024.html
- Chambers, *Mining 2026: Rwanda*: https://gpg-pdf.chambers.com/mining-2026/325/
- EY, *Rwanda introduces numerous tax changes*: https://www.ey.com/en_gl/technical/tax-alerts/rwanda-introduces-numerous-tax-changes
