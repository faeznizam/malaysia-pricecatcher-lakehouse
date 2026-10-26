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
- Skips files already downloaded, except the current month and the lookups,
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
