# Findings: Malaysia retail prices, May–October 2026

Data: KPDN PriceCatcher via data.gov.my (CC BY 4.0), May to 26 Oct 2026,
from about 2,150 shops for 343 items. October is a partial month, and
1–9 October and 16 and 30 September have no data at all. Sections 1–3 look at
September and October; section 4 covers all six months.

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
same index by type of shop shows the gap is large (October, Malaysia = 100):

| Type of shop | Index |
|---|---:|
| Kedai Runcit (grocer) | 105.0 |
| Pasar Basah (wet market) | 104.9 |
| Pasar Mini (mini market) | 102.1 |
| Pasar Raya / Supermarket | 98.5 |
| Hypermarket | 95.7 |

Grocers and wet markets are about 10% dearer than hypermarkets on the same
items. That's bigger than the gap between most states, so shop mix could
move a state several places in the ranking. The next step would be to
compare states within one shop type, so like is compared with like.

## 2. Which prices changed most from September to October?

Matched change, September to October (October covers 10–26 Oct only):

| Rose most | Change | Shops | Fell most | Change | Shops |
|---|---:|---:|---|---:|---:|
| Sawi hijau | +46.4% | 1,389 | Betik (papaya) | −20.6% | 273 |
| Sawi pendek / pak choy | +41.4% | 1,342 | Tomato | −18.7% | 1,604 |
| Kailan | +31.2% | 962 | Tembikai susu (honeydew) | −17.6% | 266 |
| Kacang buncis | +28.3% | 1,375 | Tembikai merah tanpa biji | −12.0% | 293 |
| Timun | +21.0% | 1,598 | Terung bulat | −10.1% | 823 |
| Bayam hijau | +20.0% | 1,087 | Ikan selar | −8.9% | 1,067 |

By item group, the typical (median) item barely moved: dry goods
(barangan kering) +0.62% with 16 of 18 items up, fresh goods (barangan segar)
−0.10%, with 43 items up and 55 down.

**Q4. Pick one item that rose or fell a lot. Is there a likely reason
(season, festival, supply, policy)? Or could it be a data issue?**

Leafy vegetables jumped together: sawi hijau +46%, pak choy +41%, kailan
+31% and kacang buncis +28%. This is very unlikely to be a data issue: each
is based on 960 to 1,400 shops that reported in both months, and they all
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
no shop changed its price. Udang putih besar (large white prawns) shows this
clearly: the naive change says it fell 3.4%, but in shops that reported in
both months it actually rose 1.6%. The fall came from cheaper shops joining
in October, not from price cuts. Imported red shallots (bawang kecil merah)
go the other way: naive +10.5%, matched only +3.2%, because the mix shifted
towards dearer shops.
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

## 4. How have prices moved since May?

Price index, May 2026 = 100, built from matched item changes (geometric mean,
chained month to month; every item counts equally):

| Group | Jun | Jul | Aug | Sep | Oct |
|---|---:|---:|---:|---:|---:|
| **All items** | 100.1 | 100.3 | 100.7 | 100.7 | **101.2** |
| Barangan kering (dry goods) | 100.9 | 101.9 | 102.8 | 106.7 | **108.8** |
| Barangan segar (fresh) | 100.2 | 100.4 | 101.8 | 100.9 | 101.8 |
| Susu dan barangan bayi (milk, baby) | 100.1 | 100.1 | 100.1 | 100.6 | 100.9 |
| Minuman (drinks) | 100.0 | 100.2 | 100.3 | 100.5 | 100.7 |
| Barangan berbungkus (packaged) | 100.0 | 100.0 | 99.9 | 99.9 | 99.9 |
| Produk kebersihan (hygiene) | 99.8 | 99.6 | 99.8 | 99.9 | 99.7 |

**Q7. What stands out over the six months?**

Overall, prices rose only 1.2% in five months, about 2.9% a year if it
continued, which is in the range of normal inflation. The exception is dry
goods (barangan kering, the group that holds dry staples): up 8.8%, rising
every month, with the biggest jump in September (+3.8%). That steady climb
looks like a cost or policy change working through, not a weather shock like
the leafy vegetables in Q4. Packaged and hygiene products barely moved,
likely because big brands change prices rarely. The next step is to find
which dry-goods items drove the rise; that would tell whether it's one
staple (for example rice) or a broad increase.

## Limitations

- Six months of data: enough for a trend, not for seasonal patterns across years.
- State index not adjusted for shop type or item quality.
- 14 new item codes are missing from the published item list; their prices
  are kept but can't be named.
