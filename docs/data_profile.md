# Data profile: PriceCatcher, September and October 2026

Profiled on 21 Oct 2026 with `make profile` (`pricecatcher/profile.py`) against
`pricecatcher_2026-09.parquet`, `pricecatcher_2026-10.parquet` (data up to 21 Oct)
and both lookups, as downloaded from data.gov.my that day.

**Summary:** 2,529,549 price rows from 2,153 premises covering 343 items. The data
is structurally clean (no nulls, no duplicate keys, no zero or negative prices).
The problems are a handful of mistyped prices (107 rows, 0.004%), 14 item codes
not yet in the item lookup (39,382 rows, 1.6%), and 11 days with no data.

## What we found

### Volume

| File | Rows | First date | Last date | Days with data |
|---|---|---|---|---|
| pricecatcher_2026-09 | 1,742,320 | 2026-09-01 | 2026-09-29 | 28 |
| pricecatcher_2026-10 | 787,229 | 2026-10-10 | 2026-10-21 | 12 |

Roughly 60,000-65,000 rows per day. `lookup_item` has 797 items and
`lookup_premise` 3,929 premises, so the lookups also describe items and premises
not priced in these two months.

### Schema

| Column | Type | Nulls |
|---|---|---|
| date | DATE | 0 |
| premise_code | BIGINT | 0 |
| item_code | BIGINT | 0 |
| price | DOUBLE | 0 |

`price` is a floating-point number, which cannot represent money exactly
(e.g. 0.1 + 0.2 is not 0.3). Silver will store it as `DECIMAL(10,2)`.

### Missing days

| File | Missing days |
|---|---|
| September | 16, 30 |
| October (to 21st) | 1-9 |

16 September is Malaysia Day, a public holiday, so no collection is plausible.
30 September and 1-9 October have no obvious explanation; they may be a
publishing gap. **Open question:** re-download later to see if they are
backfilled.

### Duplicates

None. Every (date, premise_code, item_code) appears once.

### Mistyped prices

Prices were compared with the median price of the same item across both months.

| Check | Rows | Items | Share of rows |
|---|---|---|---|
| Price >= 10x item median | 26 | 26 | 0.001% |
| ...of which 80x-120x (two decimal places lost) | 11 | 11 | |
| Price <= 1/10 of item median | 81 | 57 | 0.003% |

The high prices cluster at almost exactly 10x or 100x the median, for example
item 1555 at RM3,900 against a median of RM33.90, and item 918 at RM25.00
against RM2.50. This is the signature of a missing decimal point, not a real
price. Each high outlier is a single row for its item, so they are one-off
typing errors rather than a different product size.

The low prices look like the reverse mistake or a placeholder entry, for
example item 109 at RM0.01 against a median of RM3.80, and item 845 at RM3.00
against RM36.00. No item has more than 4 such rows.

### Codes not in the lookups

| Lookup | Unknown codes | Rows affected |
|---|---|---|
| lookup_item | 14 | 39,382 (1.6%) |
| lookup_premise | 1 | 13 |

All 14 unknown item codes (2023, 2035, 2048, 2053, 2057, 2059, 2089-2096) first
appear on 7 September 2026 and have normal-looking prices (RM2.49-RM18.10
median). They look like new items added to the survey before the lookup was
updated, so the rows are valid and only their description is missing.

### Lookup placeholder rows

Each lookup has one row with code `-1` and empty fields (`Unknown Premise`,
`Unknown Address` in the premise lookup). These are deliberate "unknown member"
rows, a common data-warehouse convention, not errors.

## Data quality rules (proposed for silver)

Severity follows the project convention: **error** rows go to quarantine and are
excluded from analysis; **warn** rows are kept and tagged; **info** is recorded
per run.

| Rule | Severity | Basis |
|---|---|---|
| date, premise_code, item_code or price is null | error | None today; guard against future files |
| Duplicate (date, premise_code, item_code) | error | None today; guard |
| price <= 0 | error | None today; guard |
| price >= 10x item median | error | 26 rows, all at ~10x or ~100x: missing decimal point |
| price <= 1/10 of item median | error | 81 rows, e.g. RM0.01 vs median RM3.80 |
| item_code not in lookup_item | warn | 39,382 valid rows for 14 new items; map to `-1` until the lookup catches up |
| premise_code not in lookup_premise | warn | 13 rows; map to `-1` |
| Days with no data in a month | info | 11 days in Sept-Oct 2026 |
| Rows per day | info | baseline ~60-65k per day |

Quarantined rows are kept, never deleted, so a wrong rule can be fixed and the
rows recovered. Thresholds should be re-checked once three months of data are
loaded.
