# ADR 0001: Partition fact_price by month, no Z-ordering

**Status:** accepted (to re-check with real-data numbers from `make benchmark`)
**Date:** 26 Oct 2026

## Context

`gold/fact_price` holds one row per price observation, about 2.7 million rows
(around 11 MB) for September and October 2026, growing by roughly 1.8 million
rows a month. How the table is laid out on disk decides how much a query has to
read. Three common choices:

- **Partitioning:** one folder per value of a column, so a query that filters
  on that column skips whole folders.
- **Z-ordering** (`OPTIMIZE ... ZORDER BY`): sorts rows so each file covers a
  narrow range of a column, letting Delta skip files using their min/max stats.
- **Neither:** one plain table.

## What was measured

`pricecatcher/benchmark.py` copies fact_price into four layouts and times three
typical queries (median of 3 runs after a warm-up, round-robin across layouts
so none benefits from running later).

Test run in the development sandbox on full-size *synthetic* data
(2,403,667 rows, 4 CPU cores, Spark local mode):

| Layout | Files | Size (MB) | Write (s) | one_month (s) | one_item (s) | full_scan (s) |
|---|---:|---:|---:|---:|---:|---:|
| unpartitioned | 4 | 11.2 | 13.6 | 0.92 | 0.68 | 6.17 |
| by_month | 4 | 11.2 | 10.7 | 0.96 | 0.82 | 6.67 |
| by_month_zorder | 2 | 11.3 | 25.8 | 0.81 | 0.75 | 8.85 |
| by_day | 82 | 14.5 | 10.3 | 0.90 | 0.79 | 6.17 |

*Real-data results: to be added after running `make benchmark` on the laptop.*

## Findings

1. **At this size, layout barely changes query speed.** Every query reads the
   whole 11 MB in well under a second; differences of 0.1-0.2 s are noise.
   Partition pruning saves reading files, and there's almost nothing to save.
2. **Z-ordering cost more than it saved.** It doubled the write time and
   compacted the table into fewer files, which left fewer pieces to process in
   parallel, so the full scan got slower.
3. **Partitioning by day is the classic small-files mistake.** 82 files instead
   of 4 and 30% more storage, for no speed gain. At larger scale, the cost of
   listing and opening thousands of tiny files grows.

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
