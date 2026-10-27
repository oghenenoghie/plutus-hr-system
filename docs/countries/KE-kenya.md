# Kenya (KE): draft rules matrix

| | |
|---|---|
| Status | **Payroll active, owner-approved.** Approved by Plutus Technologies on 27 October 2026 without a local tax adviser's review, and encoded as `KE-2026.1` in `app/compliance/engine/countries/ke.py`. Figures below marked conflicting or unknown became Tax Settings each organisation enters, unless an official source settled them; `ke.py` says which. VAT, withholding tax and corporate tax remain draft and are refused. |
| Prepared | 25 October 2026, from web research |
| Reviewer | Kenya tax adviser (to be named) |
| Currency | Kenyan shilling, KES, 2 decimal places (ISO 4217) |

**How to read this.** Each figure gives its source and whether the source is *official* (KRA, NSSF, a gazette or Act) or *secondary* (a Big Four firm, a law firm or a payroll vendor). The primary documents could not be opened from the environment this was prepared in, so the adviser must check every figure against the primary text before approval. **Conflicting** means sources disagree; **Unknown** means no reliable figure was found. The payroll figures were approved as drafted on 27 October 2026 (see Status); the rest still need review.

## 1. Employment income tax (PAYE)

Monthly bands, in force since July 2023 (Finance Act 2023). Secondary sources report that the Finance Act 2026 (assented 23 June 2026) left them unchanged.

| Monthly taxable pay (KES) | Rate |
|---|---|
| First 24,000 | 10% |
| Next 8,333 (to 32,333) | 25% |
| Next 467,667 (to 500,000) | 30% |
| Next 300,000 (to 800,000) | 32.5% |
| Above 800,000 | 35% |

- **Personal relief:** KES 2,400 a month (KES 28,800 a year), a credit against tax, not a deduction from income. *Secondary, consistent.*
- **Deductible before PAYE** (KRA public notice on the Tax Laws (Amendment) Act 2024, effective 27 December 2024, applying from December 2024 payroll; *official*):
  - Affordable Housing Levy contributions;
  - SHIF contributions;
  - pension, provident or retirement fund contributions, up to KES 30,000 a month;
  - post-retirement medical fund contributions, up to KES 15,000 a month;
  - mortgage interest, up to KES 30,000 a month.
- **Reliefs repealed** by that notice: the Affordable Housing Relief and the Post-Retirement Medical Fund Relief.
- **Conflicting on the Housing Levy:** one calculator site (Afrotools) still deducts the Housing Levy from net pay after PAYE. The KRA notice is the more authoritative source.
- **Watch:** a reported Finance Bill 2026 amendment would add a 17.5% band from 1 January 2027 if enacted. *Secondary; not law as found.*
- **Remittance:** by the 9th of the following month. *Secondary, consistent.*

## 2. Statutory contributions

| Scheme | Employee | Employer | Base and limits | Authority | Due | Source |
|---|---|---|---|---|---|---|
| NSSF (NSSF Act 2013, Year 4 rates from February 2026) | 6% | 6% | Tier I up to the Lower Earnings Limit, KES 9,000; Tier II from KES 9,000 to the Upper Earnings Limit, KES 108,000. Maximum KES 6,480 a side a month. | NSSF | 9th of the following month | NSSF notice to employers, 18 February 2026 (*official*, seen via a copy and the KPMG and PwC alerts) |
| Social Health Insurance Fund (SHIF) | 2.75% of gross pay, minimum KES 300 a month, no maximum | None | Gross pay | Social Health Authority | 9th of the following month | Social Health Insurance Act 2023 and regulations of 8 March 2024 (*secondary*) |
| Affordable Housing Levy | 1.5% | 1.5% | Gross pay, no ceiling | Collected by KRA | 9th of the following month | Affordable Housing Act 2024 (*secondary*) |
| Industrial Training Levy (NITA) | None | KES 50 per employee a month, not deducted from pay | Per head, casual employees included | NITA, reportedly KRA since the 2022 amendment | **Conflicting**: last working day of the month (NITA FAQ), the 5th (2022 amendment, reported) or the 10th (older guidance) of the following month | NITA (*official*) and secondary sources |

- **NSSF and PAYE:** whether NSSF contributions fall within the pension deduction cap of KES 30,000 is **unknown**. KRA's notice doesn't name NSSF, although the Finance Committee chair said during the June 2024 debate that NSSF savings would be deductible.
- **NSSF version boundary:** Year 3 rates ended on 31 January 2026 and Year 4 began with February 2026 pay, so 2026 needs two rule versions.
- **NITA scope:** **conflicting.** One source says employers with more than 20 employees must register, another says 100 or more must pay. Hotels and restaurants paying the catering levy are exempt. Late payment costs 5% a month. One source says the levy is declared annually through KRA.
- **NSSF from 2027:** after Year 4, rates are set by Gazette Notice. *Secondary, PwC.*
- **Late SHIF:** 2% of the outstanding amount a month (s.27(6) of the Act). *Secondary.*

## 3. VAT

- **Rates:** standard 16%, zero rate 0%, plus exempt supplies. *Secondary, PwC (last reviewed October 2025).*
- **Registration:** compulsory above KES 5 million of taxable supplies in 12 months; voluntary below that. *Official, KRA VAT brochure.* Non-resident digital service suppliers register regardless (PwC).
- **Filing:** monthly VAT3 return, due on the 20th of the following month. *Secondary.*

## 4. Withholding tax on payments to residents (selected)

| Payment | Rate | Source |
|---|---|---|
| Management or professional fees | 5% | PwC (*secondary*) |
| Contractual fees | 3% | Calculator only (**unconfirmed**) |
| Interest | 15% | PwC (*secondary*) |
| Dividends, holding under 12.5% | 5% | PwC (*secondary*); LinkedIn posts say 10% (**conflicting**, PwC preferred) |
| Dividends, holding over 12.5% | Exempt | PwC (*secondary*) |

**Watch:** the Finance Bill 2026 proposed widening "management or professional fees" and royalties to cover digital platform and payment-processing charges, and reintroducing 20% WHT on winnings. The Finance Act 2026 was assented on 23 June 2026, but whether these measures survived is unconfirmed. Check the enacted text.

## 5. Corporate income tax

- **Resident company:** 30%. This is a widely published figure, but no source was captured in this research; to be confirmed.

## 6. What Plutus would need

- **Order of deductions:** NSSF tiers with an upper limit, SHIF with a floor, then the Housing Levy, all before PAYE.
- **PAYE:** five bands, then personal relief taken off the tax.
- **Employer-only items:** the per-head NITA levy and the employer halves of NSSF and the Housing Levy.
- **Liabilities and deadlines:** NSSF, SHIF, the Housing Levy, PAYE and NITA, mostly due on the 9th.
- **Effective dating:** NSSF changes with February pay, not January, so a rule version can start mid-year.
- **Employee data:** Plutus already holds enough. Each employee needs a KRA PIN (the TIN field) and NSSF and SHA numbers.

## 7. Questions for the adviser

1. Are NSSF contributions deductible for PAYE, and within which cap?
2. What is the current NITA due date and channel since the Industrial Training (Amendment) Act 2022?
3. Is there a confirmed 2026 resident withholding rate for contractual fees?
4. Has any Finance Act 2026 measure changed PAYE, the Housing Levy or SHIF?
5. Is the 2027 NSSF rate already gazetted?

## Sources

- KRA, *Amendments to PAYE computation pursuant to the Tax Laws (Amendment) Act, 2024*: https://www.kra.go.ke/news-center/public-notices/2157-amendments-to-paye-computation-pursuant-to-the-tax-laws-amendment-act%2C-2024
- NSSF, *Notice to employers: Year 4 (2026) NSSF contribution rates*: https://www.nssf.or.ke/notice-to-employers-year-4-2026-nssf-contribution-rates (copy: https://gaa.go.ke/sites/default/files/2026-02/Notice%20To%20Employers%20%E2%80%94%20Year%204%20%282026%29%20NSSF%20Contribution%20Rates%20.pdf)
- KPMG Kenya, *Phase 4 of NSSF contribution rates*: https://kpmg.com/ke/en/insights/2026/02/phase-4-of-nssf-contribution-rates-effective-february-2026.html
- PwC Kenya, *Tax alert, Year 4 NSSF rates*: https://www.pwc.com/ke/en/assets/pdf/tax-alert-year-4nssf-rates-2026.pdf
- KRA, *VAT brochure*: https://www.kra.go.ke/images/publications/VAT-E-brochure-Final.pdf
- PwC Worldwide Tax Summaries, Kenya (other taxes; withholding taxes): https://taxsummaries.pwc.com/Kenya/Corporate/Other-taxes and https://taxsummaries.pwc.com/kenya/corporate/withholding-taxes
- NITA, levy FAQ: https://www.nita.go.ke/faq-s/99-nita-services
- Capital FM, *NSSF contribution rates jump from February*: https://www.capitalfm.co.ke/news/2026/02/nssf-contribution-rates-jump-from-feb-heres-what-you-must-pay
- Vialto Partners, *Kenya: NSSF changes*: https://vialtopartners.com/regional-alerts/kenya-employment-tax-national-social-security-fund-nssf-changes
- Kenyans.co.ke, *SHA warns of 2% penalties for late remittances*: https://www.kenyans.co.ke/news/125697-sha-warns-2-penalties-employers-late-employee-remittances
- People Daily, *Kenyans to pay higher rates in new health plan*: https://peopledaily.digital/news/kenyans-to-pay-higher-rates-in-new-health-plan
- Business Daily, *Workers gain as KRA grants tax relief on housing levy, SHIF*: https://www.businessdailyafrica.com/bd/economy/workers-gain-as-kra-grants-tax-relief-on-housing-levy-shif-4863782
- NITA, *Levy Inspectorate*: https://nita.go.ke/our-services/levy-inspectorate.html
- PwC Kenya, *National Industrial Training Authority*: https://www.pwc.com/ke/en/pdf/national-industrial-training-authority-kenya.pdf
- EY Global Tax News, Kenya Finance Bill 2026 (13 May 2026): https://globaltaxnews.ey.com/news/2026-1063
- ENSafrica, *Finance Act 2026: tax alert on notable changes*: https://www.ensafrica.com/uploads/newsarticles/0_finance%20act%202026%20-%20tax%20alert%20on%20notable%20changes.pdf
- EY, *Kenya employers to begin making contributions to SHIF*: https://www.ey.com/en_gl/technical/tax-alerts/kenya-employers-to-begin-making-contributions-to-social-health-insurance-fund
- Business Radar (PAYE bands, Finance Act 2026): https://businessradar.co.ke/?p=9779
