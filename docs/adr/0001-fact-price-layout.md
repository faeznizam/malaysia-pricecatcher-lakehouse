# ADR 0001: Partition fact_price by month, no Z-ordering

**Status:** accepted
**Date:** 27 Oct 2026 (re-measured 28 Oct at 10 million rows)

## Context

`gold/fact_price` holds one row per price observation, about 2.7 million rows
(about 10 MB) for September and October 2026, growing by roughly 1.8 million
rows a month. How the table is laid out on disk decides how much a query has to
read. Three common choices:

- **Partitioning:** one folder per value of a column, so a query that filters
  on that column skips whole folders.
- **Z-ordering** (`OPTIMIZE ... ZORDER BY`): sorts rows so each file covers a
  narrow range of a column, letting Delta skip files using their min/max stats.
- **Neither:** one plain table.

## What was measured

`pricecatcher/benchmark.py` (`make benchmark`) copies fact_price into four
layouts and times three typical queries: one month's total, one item's daily
price across all months, and a median per item per month over everything.
Each figure is the median of 3 runs after a warm-up, round-robin across layouts
so none benefits from running later.

Real data, 27 Oct 2026: 2,699,801 rows (1 Sep to 25 Oct 2026), on a Windows
laptop under WSL2, Spark local mode:

| Layout | Files | Size (MB) | Write (s) | one_month (s) | one_item (s) | full_scan (s) |
|---|---:|---:|---:|---:|---:|---:|
| unpartitioned | 8 | 10.1 | 8.2 | 0.31 | 0.34 | 0.79 |
| by_month | 8 | 10.1 | 4.0 | 0.40 | 0.31 | 0.74 |
| by_month_zorder | 2 | 9.9 | 9.3 | 0.40 | 0.33 | 1.32 |
| by_day | 176 | 12.7 | 2.6 | 0.45 | 0.48 | 1.23 |

(Write times include the first layout paying Spark's start-up costs, so they
are only a rough guide.)

Re-measured on 28 Oct 2026 after extending the data to six months:
10,133,244 rows (May to 26 Oct 2026), same laptop:

| Layout | Files | Size (MB) | Write (s) | one_month (s) | one_item (s) | full_scan (s) |
|---|---:|---:|---:|---:|---:|---:|
| unpartitioned | 11 | 39.2 | 8.9 | 0.38 | 0.46 | 2.12 |
| by_month | 33 | 41.0 | 8.0 | 0.41 | 0.41 | 2.08 |
| by_month_zorder | 6 | 43.2 | 18.4 | 0.40 | 0.45 | 2.79 |
| by_day | 919 | 52.2 | 9.3 | 0.39 | 0.90 | 3.31 |

## Findings

1. **Monthly folders vs no folders still makes no real difference.** At
   2.7 million rows the full scan took 0.74 s vs 0.79 s; at 10.1 million,
   2.08 s vs 2.12 s. Even reading one month wasn't faster with month folders
   (0.41 s vs 0.38 s): at 40 MB, opening the files costs more than the
   reading that pruning saves.
2. **Z-ordering made things worse at both sizes.** Write time doubled
   (18.4 s vs 8.0 s at 10 million rows) and the full scan was 34% slower
   (2.79 s vs 2.08 s), because packing the data into 6 big files leaves Spark
   fewer pieces to work on in parallel. It didn't speed up the one-item
   query either.
3. **Daily folders got worse as the data grew.** At 10 million rows they made
   919 files (vs 33), took 27% more space, and made the one-item query
   2.2x slower (0.90 s vs 0.41 s) and the full scan 59% slower (3.31 s vs
   2.08 s). That's the small-files problem growing with the data: the cost is
   per file, and the file count grows every day.

## Decision

Keep **partitioning by `year_month`**, no Z-ordering.

The deciding reason isn't query speed, it's loading: bronze and silver replace
one month at a time with `replaceWhere`, which is what makes re-runs safe.
Month partitions make that replace touch only that month's folder. Month also
matches how the data arrives (one file per month) and how it's analysed
(month-on-month marts).

## When to revisit

- The table passes roughly 1 GB, or many years are loaded: then pruning starts
  to pay, and Z-ordering by `item_code` may help item-level queries.
- The lake moves to cloud storage (S3/GCS), where every file read is a network
  request and file counts matter more.
