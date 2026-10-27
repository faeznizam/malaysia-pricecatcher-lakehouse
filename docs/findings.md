# Findings: Malaysia retail prices, September–October 2026

Data: KPDN PriceCatcher via data.gov.my (CC BY 4.0), 1 Sep to 25 Oct 2026,
2,699,801 prices from about 2,150 shops for 343 items. October is a partial
month, and 1–9 October and 16 and 30 September have no data at all.

> **Draft for Faez to review.** The answers below were drafted by Claude from
> the pipeline's numbers. Faez: rewrite anything you'd say differently, so
> you can defend every sentence in an interview. Delete this note when done.

## 1. Which states are most expensive?

October price index on a common basket of 176 items (Malaysia = 100):

| Most expensive | Index | Cheapest | Index |
|---|---:|---|---:|
| W.P. Labuan | 109.6 | Melaka | 97.1 |
| Sarawak | 106.2 | Perak | 97.2 |
| W.P. Putrajaya | 105.8 | Kedah | 97.5 |
| Sabah | 105.5 | Negeri Sembilan | 97.6 |
| W.P. Kuala Lumpur | 105.1 | Johor / Pahang / Pulau Pinang | 98.9 |

**Q1. Why might Labuan, Sarawak and Sabah be the most expensive?**

Most packaged and processed goods are made or imported through Peninsular
Malaysia, so East Malaysia pays for shipping across the South China Sea and
for longer, thinner distribution networks. Labuan, a small island supplied
mainly via Sabah, adds one more hop, which fits it being highest at 109.6.
This is a likely explanation, not something this data proves; the item-level
gaps would show whether shipped goods (dry groceries) differ more than local
fresh produce.

**Q2. Putrajaya and Kuala Lumpur are also near the top. Why might cities cost
more than, say, Melaka or Perak?**

Shops in the big cities pay higher rent and wages and serve customers with
higher incomes, and those costs show up in shelf prices. Melaka and Perak
have lower costs and more traditional markets. Selangor, though urban, sits
just below 100, which suggests strong competition from its many large
supermarkets offsets the cost of being urban.

**Q3. The index doesn't adjust for the mix of shop types (hypermarket vs
small grocer). How could that change the ranking?**

A state with many hypermarkets will look cheaper than one served mostly by
small grocers, even if each type of shop charges the same everywhere. The
"Which types of shop are cheapest?" section of the report measures how big
those differences are. The next step would be to compare states within one
shop type, so like is compared with like.

## 2. Which prices changed most from September to October?

Matched change, September to October (October covers 10–25 Oct only):

| Rose most | Change | Shops | Fell most | Change | Shops |
|---|---:|---:|---|---:|---:|
| Sawi hijau | +45.7% | 1,368 | Betik (papaya) | −20.9% | 264 |
| Sawi pendek / pak choy | +40.6% | 1,319 | Tomato | −18.2% | 1,592 |
| Kailan | +30.5% | 949 | Tembikai susu (honeydew) | −18.1% | 257 |
| Kacang buncis | +30.0% | 1,359 | Tembikai merah tanpa biji | −13.2% | 288 |
| Timun | +21.0% | 1,587 | Terung bulat | −10.2% | 812 |
| Bayam hijau | +20.1% | 1,073 | Ikan selar | −8.6% | 1,058 |

By item group, the typical (median) item barely moved: dry goods
(barangan kering) +0.67% with 15 of 18 items up, fresh goods (barangan segar)
−0.01%, with 47 items up and 49 down.

**Q4. Pick one item that rose or fell a lot. Is there a likely reason
(season, festival, supply, policy)? Or could it be a data issue?**

Leafy vegetables jumped together: sawi hijau +46%, pak choy +41%, kailan
+30% and kacang buncis +30%. This is very unlikely to be a data issue: each
is based on 950 to 1,400 shops that reported in both months, and they all
moved in the same direction. A shared supply shock is the likely cause:
October's heavy inter-monsoon rain can damage leafy crops and disrupt
harvests in growing areas such as Cameron Highlands, and leafy greens can't
be stored, so prices react fast. This explanation is a hypothesis; checking
weather records for those weeks would confirm or rule it out. Meanwhile some
fruit (papaya, honeydew, watermelon) and tomatoes got cheaper, so fresh goods
as a group were flat even though greens rose sharply.

**Q5. Why did we use the "matched" change (same shops in both months)
instead of comparing plain averages? Give an example from the "Why matched
matters" table.**

A plain average moves whenever the set of shops reporting changes, even if
no shop changed its price. Teh Lipton (100 bags) shows this clearly: the
naive change says it fell 7.8%, but in shops that reported in both months it
actually rose 1.0%. The fall came from cheaper shops joining in October, not
from price cuts. Udang putih besar is similar: naive −6.2%, matched +0.8%.
Comparing each shop with itself, as official price indices do, avoids
reporting changes that never happened.

## 3. How clean is the data?

| Month | Rows checked | Quarantined | Too high (≥10× median) | Too low (≤1/10) | Unknown item (kept) |
|---|---:|---:|---:|---:|---:|
| 2026-09 | 1,742,320 | 70 | 20 | 50 | 26,191 |
| 2026-10 | 957,594 | 43 | 8 | 35 | 13,675 |

**Q6. Under 0.01% of rows were quarantined. What does that tell you about
the source, and what kind of errors were they?**

The source is very clean: no missing values, no duplicates and no zero or
negative prices. The 113 quarantined rows were all prices about 10x or 100x
too high (a missing decimal point, e.g. RM3,900 for a RM33.90 item) or far
too low. The bigger issue is completeness, not accuracy: 1.5% of prices use
item codes that aren't in the published item list yet, and 11 days have no
data at all.

## Limitations

- Only about two months of data, so no long-term trends yet.
- State index not adjusted for shop type or item quality.
- 14 new item codes are missing from the published item list; their prices
  are kept but can't be named.
