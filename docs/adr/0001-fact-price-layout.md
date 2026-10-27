# ADR 0001: Partition fact_price by month, no Z-ordering

**Status:** accepted
**Date:** 27 Oct 2026

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

## Findings

1. **At this size, partitioning by month vs not at all makes no real
   difference.** Every query on both finishes in under a second, and gaps of
   0.1 s are noise. Partition pruning saves reading files, and with 10 MB
   there's almost nothing to save.
2. **Z-ordering made things worse.** It took over twice as long to write as
   by_month and squeezed the table into 2 files. Fewer files means fewer
   pieces to process in parallel, so the full scan was 78% slower
   (1.32 s vs 0.74 s).
3. **Partitioning by day is the classic small-files mistake.** It made
   176 files instead of 8 and used 26% more storage, and the full scan was 66%
   slower (1.23 s vs 0.74 s). That overhead grows as more days are loaded.

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
