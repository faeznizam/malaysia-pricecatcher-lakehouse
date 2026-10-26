# Learning notes

One short section per step: what it does, why, and questions an interviewer
might ask, with answers in plain words. Written for the end-of-build walkthrough.

## Step 1: Download (landing)

**What it does.** `make download` fetches the monthly price files and the two
lookup files from data.gov.my and saves them, unchanged, in `data/landing/`.

**Why.** The raw files are the source of truth. Keeping an untouched copy means
any later step can be redone from scratch without trusting anything we built.

**How it stays reliable.**
- Writes to a `.part` file and renames only when complete, so a dropped
  connection never leaves a half file that looks finished.
- Checks the file starts and ends with `PAR1`, so an error page is never saved
  as data.
- Skips files already downloaded, except the current and previous month and the lookups,
  which the publisher keeps adding to.

**Interview questions**
1. *Why not just download the files by hand?* A script does it the same way
   every time, for any month, and can later run on a schedule.
2. *What happens if the download fails halfway?* Nothing is left behind: the
   partial `.part` file is deleted and the run reports FAILED.
3. *Why re-download the current month?* data.gov.my appends new days to it
   daily. October grew from 787,229 rows on 21 Oct to 957,594 on 26 Oct.

## Step 2: Profiling

**What it does.** `make profile` reads the landing files with DuckDB (SQL on
files) and reports rows, types, missing values, duplicates, price ranges, odd
prices and codes missing from the lookups. It changes nothing.

**Why.** You can't write good cleaning rules without knowing what's wrong with
the data. Rules based on evidence are easy to defend; guessed rules aren't.

**What we found** (details in `docs/data_profile.md`): structurally clean data,
107 mistyped prices out of 2.5 million (prices 10x or 100x too high, or far too
low), 14 new items not yet in the item lookup, and 11 days with no data.

**Interview questions**
1. *Why profile before building the pipeline?* To set data quality rules from
   evidence. The profile showed the high prices cluster at exactly 10x and 100x
   the usual price, which points to missing decimal points.
2. *Why set bad rows aside instead of deleting them?* If a rule turns out to be
   wrong, the rows can be recovered. Deleting loses that option.
3. *Why DuckDB here and Spark later?* DuckDB is quick for one-off questions on
   files. Spark is the tool the pipeline itself is built on.

## Step 3: Bronze

**What it does.** `make bronze` loads the landing files into Delta tables in
`lake/bronze/`. Prices are stored per month; the lookups are replaced each time.

**Key ideas**
- **Delta table:** Parquet data files plus a transaction log. The log makes
  writes all-or-nothing and keeps history, so a failed write can't leave half a
  table.
- **Idempotent load:** running it twice gives the same result. Loading October
  again replaces only October (`replaceWhere`), so rows never double.
- **Schema contract:** the columns we depend on, with their types. A missing
  column or a value that won't convert stops the load with a clear error. A new
  extra column is ignored.
- **Lineage:** every row records its source file and load time.

**The Brotli problem.** Tests passed, but the first real run failed: data.gov.my
compresses its files with Brotli, which Spark can't read without an extra
codec. The fix re-encodes each file unchanged with DuckDB before Spark reads
it, and the test files now use Brotli so the tests match reality.

**Result on real data (26 Oct 2026):** September 1,742,320 rows, October
957,594 rows (to date), 797 items, 3,929 premises.

**Interview questions**
1. *What does idempotent mean, and why does it matter?* Re-running gives the
   same result. Pipelines get re-run after failures; without it you get
   duplicates.
2. *Why a schema contract in bronze?* So a change by the publisher fails loudly
   at the door instead of quietly corrupting later tables.
3. *Tell me about a problem you hit.* The Brotli failure above: tests passed on
   fake data, real data failed, so I fixed the loader and made the test data
   match the real files.

## Step 4: Silver

**What it does.** `make silver` checks every bronze row against the data
quality rules in `pricecatcher/dq.py`. Rows that fail a serious (error) rule go
to `silver/quarantine` with the names of the rules they broke. Rows with a minor
(warn) issue stay in `silver/prices` with a label. Clean prices are stored as
`DECIMAL(10,2)`, an exact money type. Every run adds per-rule counts to
`meta/dq_run_log`.

**The rules** (evidence in `docs/data_profile.md`)

| Rule | Severity | Catches |
|---|---|---|
| null_field | error | a missing date, code or price |
| duplicate_key | error | a repeat of the same date + premise + item |
| price_not_positive | error | zero or negative prices |
| price_too_high | error | 10x or more the item's median that month |
| price_too_low | error | 1/10 or less of the item's median that month |
| unknown_item | warn | item code not in the item lookup yet |
| unknown_premise | warn | premise code not in the premise lookup yet |

**Result on real data (26 Oct 2026)**

| Month | Rows checked | Quarantined | Too high | Too low | Unknown item (kept) |
|---|---|---|---|---|---|
| 2026-09 | 1,742,320 | 70 | 20 | 50 | 26,191 |
| 2026-10 | 957,594 | 43 | 8 | 35 | 13,675 |

Under 0.01% of rows are quarantined, close to what the profile predicted.

**Interview questions**
1. *Why quarantine instead of deleting bad rows?* Nothing is lost. If a rule is
   wrong, fix it and re-run silver, and the rows return.
2. *Why compare each price to its item's median, not a fixed limit?* A fixed
   limit can't work across items: RM50 is normal for one item and a typo for
   another. The median is also not pulled around by the outliers themselves,
   unlike the average.
3. *What's the difference between error and warn?* Error means the value is
   wrong and would distort analysis. Warn means the row is valid but something
   is incomplete, like a new item whose name isn't published yet.
4. *Why DECIMAL for prices?* Floating-point numbers can't store most decimal
   amounts exactly, so sums of money drift. DECIMAL stores RM8.99 exactly.

## Step 5: Gold

**What it does.** `make gold` rebuilds the analysis layer from silver:

- **Star schema:** `fact_price` (one row per price) linked to `dim_item`,
  `dim_premise` and `dim_date`. This is the shape Power BI and most BI tools
  expect. Codes missing from the lookups point to the `-1` "unknown" row, and
  the original code is kept in `source_item_code` / `source_premise_code`.
- **mart_item_month:** typical price (median), average, and spread between
  cheap and dear shops (p90 / p10) per item per month.
- **mart_item_mom:** month-on-month change per item, two ways (below).
- **mart_state_index:** how expensive each state is on the same basket of
  items, Malaysia = 100.

**Naive vs matched change.** The naive change compares this month's average
price with last month's. If a cheap shop starts reporting, the average falls
even though no shop cut its price. The matched change uses only shops that
reported the item in both months, each compared with itself, which is how
official price indices handle it. It is only reported when at least 20 shops
match, because a handful of shops is too noisy.

**Result on real data (26 Oct 2026):** 2,699,801 fact rows (bronze minus the
113 quarantined), 39,878 pointing to an unknown item or premise, 55 days,
32 state-month index rows. October's state index on a 176-item basket ranged
from 109.6 (W.P. Labuan) to 97.1 (Melaka); the five most expensive were
Labuan, Sarawak, Putrajaya, Sabah and Kuala Lumpur.

**Interview questions**
1. *Why a star schema?* It separates what happened (facts: prices) from
   descriptions (dimensions: items, shops, dates). Queries and BI models stay
   simple and fast, and a name change touches one row in a dimension.
2. *Why map unknown codes to -1 instead of dropping them?* Dropping them
   would quietly remove 1.5% of real prices. The -1 row keeps every fact
   joinable and makes the gap visible.
3. *Why compare states on a common basket?* If one state's shops sell more
   expensive items, a plain average makes the state look dearer. Using only
   items sold in every state compares like with like.
4. *What doesn't the state index control for?* Shop mix: a state with more
   hypermarkets may look cheaper than one with more small shops. That's a
   caveat to state when presenting it.
