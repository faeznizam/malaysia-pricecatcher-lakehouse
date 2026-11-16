# Plan: adding Databricks (and closing five gaps)

Status: **draft plan, nothing built yet** (16 Nov 2026). Written for the
Databricks Certified Data Engineer Associate exam and the 31 Dec 2026
portfolio deadline.

The rule throughout: **the local pipeline keeps working as it is.** The
Databricks version is added next to it, in a new `databricks/` folder, and
reuses the same rules and logic where it can.

## Where the repo is today (audit)

| Gap | What the code does now | Verdict |
|---|---|---|
| Cloud | Terraform in `infra/` for ADLS Gen2 + US$5 budget. CI checks it (`fmt`, `validate`) but it was never applied: waiting on your Azure account. | Not run |
| Incremental load | **Download is already partly incremental:** `download.py` skips files it has, except the current month, last month and the two lookups (the publisher keeps changing those). The Actions cache keeps old files between runs. **Processing is not:** the daily run calls `make bronze silver gold` with no `--months`, so all 6+ months are reloaded every day, and gold is rebuilt in full. Re-runs are safe (bronze and silver replace one month at a time with `replaceWhere`), just wasteful. | Half done |
| Orchestration | GitHub Actions: one daily job (06:00 UTC = 2pm MYT) that runs the steps in order, stops before the report if a check fails, and opens a GitHub issue on failure. No orchestrator. | Works, basic |
| Data contracts | A schema contract exists in code (`PRICE_CONTRACT`, `LOOKUP_CONTRACTS` in `bronze.py`: required columns and types; a missing column fails the load). Row rules in `dq.py` (7 rules, error = quarantine, warn = keep and tag). 7 publish checks in `checks.py`. Missing: the contract is not a readable file of its own, and there is no promise about freshness, keys or ranges written down for consumers. | Mostly there, not visible |
| Lineage | Each bronze row has `_source_file` and `_ingested_at`. No lineage diagram or table-level lineage. | Row level only |
| Orphan rows (~160k) | Already handled: codes missing from the lookups map to the `-1` "unknown" row (a standard data warehouse pattern), the original code is kept in `source_item_code` / `source_premise_code`, and `checks.py` fails the run if unknowns pass a limit. Almost all are **14 new item codes** that appeared on 7 Sep 2026 before the item lookup was updated (`docs/data_profile.md`). Because gold is rebuilt daily, they re-map on their own once the lookup catches up. | Handled, but the story isn't told, and it breaks if gold becomes incremental |

So the honest pitch today is: "solid local lakehouse, cloud not run yet,
incremental only at download." The plan below fixes that.

## The exam in one table

Databricks Certified Data Engineer Associate, current guide (August 2026):
45 scored questions, 90 minutes, US$200, no aids, valid 2 years.

| # | Exam section | Weight | Where this plan covers it |
|---|---|---|---|
| 1 | Databricks Intelligence Platform | 6% | Step 1 |
| 2 | Data Ingestion and Loading (Auto Loader, COPY INTO, incremental) | 21% | Step 2 |
| 3 | Data Transformation and Modeling (bronze to silver, gold, data quality) | 22% | Steps 3, 5, 6 |
| 4 | Lakeflow Jobs (tasks, DAGs, retries, triggers) | 16% | Step 4 |
| 5 | CI/CD (Git folders, Declarative Automation Bundles, CLI) | 10% | Step 7 |
| 6 | Troubleshooting, Monitoring, Optimization (Spark UI, Liquid Clustering) | 10% | Step 8 |
| 7 | Governance and Security (Unity Catalog, GRANT, masks, row filters) | 15% | Step 5 |

Source: [exam guide PDF](https://www.databricks.com/sites/default/files/2026-10/Databricks-Certified-Data-Engineer-Associate-Exam-Guide-August-2026.pdf).
Building the project covers the hands-on part; you will still need the free
Databricks Academy course and practice exams for the theory.

---

## Step 1: Pick where Databricks runs (gap 1, cloud)

**Concept.** Databricks is a managed Spark platform. You write the same
PySpark and Delta code, but Databricks runs the machines, stores the tables in
**Unity Catalog** (a catalog of all tables, files and permissions), and adds
scheduling, data quality and lineage on top.

**Two options**

| | Databricks Free Edition | Azure Databricks |
|---|---|---|
| Cost | Free, no credit card | Pay per use: Azure VM + Databricks units. Rough estimate for a 10-minute daily run on the smallest cluster: a few US$ a month (**not verified**; the US$5 budget alert in `infra/` would catch it) |
| Account | Sign up with email or Google | Needs your Azure account (still pending) |
| Compute | Serverless only, small, daily fair-use quota (compute pauses for the day if you go over) | Any cluster size |
| Internet from Databricks | Only a list of trusted domains; **data.gov.my probably not reachable** (to test) | Open |
| Storage | Databricks-managed only; cannot point at your own ADLS | Your ADLS from `infra/` |
| Exam features | Unity Catalog, Lakeflow pipelines (1 active per type), Jobs (max 5 tasks at once), bundles, SQL warehouse (2X-Small) | All |
| CV line | "Databricks" | "Azure Databricks", the phrase in Malaysian bank and corporate ads |

Source: [Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations).

**Recommendation: build on Free Edition now, then do one Azure Databricks run
in December** (the "one-off Databricks run" already in the Azure plan). Free
Edition has every exam feature, costs nothing, and doesn't wait on the Azure
account. The same code is deployed to Azure later with a bundle target
(Step 7), which is itself an exam topic.

**Steps**
1. You: sign up for Free Edition (databricks.com/learn/free-edition).
2. Smoke test in a notebook (15 min): can it read a PriceCatcher file directly
   from data.gov.my? Can Spark there read the Brotli-compressed Parquet? (Locally
   it can't, which is why bronze re-encodes with DuckDB.) The answers decide
   Step 2's landing design.
3. Create catalog `pricecatcher` with schemas `landing`, `bronze`, `silver`,
   `gold`, `meta`, and a **volume** `landing.raw` (a Unity Catalog folder for
   plain files).

**Learning note to add:** workspace, catalog > schema > table, managed vs
external table, volume, serverless vs classic compute.

## Step 2: Incremental load (gap 2)

**Concept.** *Incremental* means each run handles only what's new. Two parts:
download only new data, and process only new data.

**The twist in this data.** data.gov.my does not publish a new file per day.
It **rewrites the same monthly file** (`pricecatcher_2026-11.parquet`) every
day with more rows. So "new file" logic alone isn't enough: the current month's
file changes under the same name.

**2a. Download only what changed (local and cloud)**
1. Before downloading, send an HTTP `HEAD` request and compare the file's
   `ETag` / `Last-Modified` / size with what we saved last time (a small
   `landing/_manifest.json`). Skip if unchanged. (To test: does
   storage.data.gov.my return these headers? Can't check from here.)
2. `download.py` prints which months actually changed; the daily workflow
   passes those to `bronze --months` and `silver --months`, so a normal day
   processes one month, not seven.
3. Measure before and after (run time in Actions) and put both numbers in the
   README.

**2b. On Databricks: Auto Loader into bronze**
1. Landing: GitHub Actions keeps doing the download (it has internet, Free
   Edition may not) and copies each changed file into the volume with the
   Databricks CLI, under a dated name so every version is a new file:
   `/Volumes/pricecatcher/landing/raw/prices/2026-11/pricecatcher_2026-11__2026-11-16.parquet`.
2. Bronze is a **streaming table** fed by **Auto Loader** (`cloudFiles`): it
   remembers which files it has already read (in a checkpoint) and reads only
   new ones. Each row gets `_metadata.file_path` (lineage) and the load time.
3. Silver then needs to keep only the **latest version of each price**:
   a `MERGE INTO` (or Lakeflow `AUTO CDC`) keyed on
   `(date, premise_code, item_code)`. New rows are inserted, re-sent rows are
   updated, nothing is duplicated. This replaces the month-by-month
   `replaceWhere` used locally.
4. Lookups: small full snapshots, so a plain overwrite stays fine (say why in
   the learning note: not everything should be incremental).

**Exam topics:** Auto Loader, COPY INTO vs Auto Loader (when to choose which),
streaming tables, checkpoints, MERGE, deduplication (sections 2 and 3).

## Step 3: Data contracts and expectations (gap 4, part 1)

**Concept.** A *data contract* is a written promise about a dataset: which
columns, which types, what keys are unique, how fresh it is. *Expectations*
are Databricks' way of enforcing row rules inside a pipeline.

**Steps**
1. Move the contract out of `bronze.py` into `contracts/prices.yml`,
   `contracts/lookup_item.yml`, `contracts/lookup_premise.yml`: columns, types,
   required or not, unique key, expected freshness, owner (data.gov.my) and
   licence. `bronze.py` reads the YAML instead of the dicts, so the local
   behaviour and tests stay the same.
2. Write each rule in `dq.py` as a **SQL string** (e.g. `price > 0`) instead of a
   Python lambda. Locally, `F.expr()` turns it into the same filter. On
   Databricks, the same strings become **expectations**, so the rules live in
   one place.
3. Map severities to expectation actions:
   - `error` rules: `EXPECT ... ON VIOLATION DROP ROW` in silver, plus a
     quarantine table that keeps the failing rows (the inverse filter), same as
     now.
   - `warn` rules: `EXPECT` (keep the row, count it in the pipeline's event log).
   - A broken contract in bronze (missing column): `ON VIOLATION FAIL UPDATE`.
4. Show expectation pass/fail counts from the pipeline event log in a small
   `meta` view, the cloud twin of `meta/dq_run_log`.

**Exam topics:** data quality checks in pipelines, bronze to silver cleaning
(section 3).

## Step 4: Orchestration (gap 3)

**Is it free?** Yes: Airflow and Dagster are both open source and free to run
on your laptop. Lakeflow Jobs is included in Databricks (also on Free Edition).

| | Lakeflow Jobs | Dagster (local) |
|---|---|---|
| Runs | Databricks pipeline | Local pipeline |
| Exam value | **High: 16% of the exam** | None |
| New skill on the CV | Yes | Yes, but Airflow is already on Olist |
| Work | Small (YAML in the bundle) | Medium (new tool, Docker or a daemon) |

**Recommendation: Lakeflow Jobs now, Dagster only if December has spare
time.** GitHub Actions stays as the scheduler for the local version and as the
downloader for the cloud version.

**Steps**
1. One job with tasks: `land_files` (or GitHub Actions does it) ->
   `lakeflow_pipeline` (bronze, silver, gold) -> `checks` -> `refresh_report`.
   Each task waits for the one before it (a DAG).
2. Add **retries** (2 tries, 10 minutes apart) on the pipeline task and a
   **condition** task: run `checks`, and only publish if it passed (same rule
   as `make check` today).
3. Trigger: try a **file arrival trigger** on the landing volume (the job
   starts when a new file lands), with a daily schedule as fallback. Being able
   to explain time-based vs data-driven triggers is an exam question.
4. Email on failure (the cloud twin of the GitHub issue).
5. Optional, December: a small Dagster project that wraps the local `make`
   steps as assets, to say "I've used both".

**Exam topics:** task types, dependencies, retries, conditional tasks,
schedules and triggers (section 4).

## Step 5: Unity Catalog lineage and governance (gap 4, part 2)

**Concept.** Unity Catalog records which tables (and columns) were built
from which, automatically, whenever Databricks runs the code. You don't write
lineage, you get it, and can show it as a graph in Catalog Explorer.

**Steps**
1. After the first pipeline run, open `gold.fact_price` in Catalog Explorer >
   Lineage and screenshot the graph from the volume file to the marts, down to
   column level (e.g. `fact_price.price` back to the raw `price`). Add it to the
   README.
2. Also add `docs/lineage.md` with a simple diagram for the local pipeline,
   since that has no automatic lineage. Same tables, so both match.
3. Governance exercise (small, but 15% of the exam):
   - Create an `analysts` group; `GRANT USE CATALOG`, `USE SCHEMA`, `SELECT` on
     `gold` only; check they can't see bronze or quarantine.
   - Add a **row filter** (e.g. a group sees only one state) and a **column
     mask** on `dim_premise.address`.
   - (To test: Free Edition has no account console, so groups may be limited to
     the workspace. If it can't be done there, do it during the Azure run.)

**Exam topics:** managed vs external tables, GRANT/REVOKE, row filters,
column masks (section 7); Unity Catalog (section 1).

## Step 6: The orphan rows story (gap 5)

**What they are.** About 160k fact rows (1.6%) carry an item or premise code
that the lookup doesn't have yet. Almost all are 14 new items added on 7 Sep
2026. The prices look normal; only the name is missing. This is a classic
**late-arriving dimension**: the fact arrives before its description.

**Options**

| Option | What it means | Good | Bad |
|---|---|---|---|
| A. Unknown member `-1` (today) | Fact points to one shared "Unknown" row; real code kept in `source_item_code` | Every join works, no rows lost, simple | All 14 items blur into one "Unknown item" in reports; only fixes itself because gold is fully rebuilt |
| B. **Inferred members** | Add a dimension row per missing code, e.g. `2090, "Item 2090 (pending lookup)", is_inferred = true`. When the lookup adds it, a `MERGE` fills in the name and flips the flag | Each item stays separate, history kept, self-heals even when gold is incremental, a textbook Kimball pattern and a natural MERGE example | A bit more code |
| C. Quarantine them | Treat as errors | Reports only show known items | Throws away 1.6% of valid prices; wrong for this data |
| D. Drop them | | | Silent data loss; never |

**Recommendation: B, inferred members**, built as a `MERGE` into
`dim_item` / `dim_premise` in both versions, plus:
1. A mart or check that lists codes still pending and how many days they've
   waited (if a code waits more than, say, 60 days, the check warns).
2. A short "orphan rows" section in `docs/findings.md` and the README with the
   numbers, so you can tell the story in 30 seconds.

**Exam topics:** MERGE, joins, gold modelling (section 3).

## Step 7: Deploy with a bundle (CI/CD)

**Concept.** A **Declarative Automation Bundle** (`databricks.yml`) describes
the pipeline, the job and their settings in YAML, so Databricks resources are
deployed from git like code, the same idea as Terraform for Azure.

**Steps**
1. `databricks/databricks.yml` with two targets: `dev` (your Free Edition) and
   `azure` (the Azure workspace later). Variables for catalog name and paths.
2. GitHub Actions: on every push, `databricks bundle validate`; on main,
   `databricks bundle deploy -t dev`. Token stored as a GitHub secret.
3. Link the repo as a **Git folder** in the workspace so notebooks match git.

**Exam topics:** bundles, variables and overrides, deploying across targets,
Databricks CLI, Git folders (section 5).

## Step 8: Optimize and compare

1. Re-run the ADR 0001 benchmark on Databricks, adding **Liquid Clustering**
   (Databricks' newer alternative to partitioning and Z-order). Add the result
   to the ADR: does the "monthly partitions" decision still hold there?
2. Open the Spark UI for the slowest stage and write down what you see
   (shuffle, skew, spill) in the learning notes.
3. Reconcile: row counts and the headline numbers (state index, price trend)
   must match between local and Databricks. Add this as a check.

**Exam topics:** Spark UI, Liquid Clustering, predictive optimization,
job run history (section 6).

## Step 9 (December): one Azure Databricks run

Once the Azure account exists: `terraform apply` (storage, budget), add an
Azure Databricks workspace to Terraform, `databricks bundle deploy -t azure`,
run once, screenshot, reconcile counts, then stop or destroy to keep the cost
at cents. This finishes the cloud story for the CV.

---

## Order and timing

| Week | Work | Needs from you |
|---|---|---|
| 17 to 23 Nov | Step 6 (inferred members, local), Step 2a (download/process only changes), Step 3 step 1-2 (contract YAML, SQL rules). All local, all testable now. | Run tests and the pipeline on your laptop |
| 24 to 30 Nov | Step 1 (Free Edition + smoke test), Step 2b (Auto Loader + MERGE), Step 3 expectations | Free Edition sign-up |
| 1 to 7 Dec | Step 4 (Lakeflow Job), Step 5 (lineage, grants), Step 7 (bundle + CI) | A Databricks token as a GitHub secret |
| 8 to 14 Dec | Step 8 (Liquid Clustering, reconcile), README + deck update | |
| 15 to 21 Dec | Step 9 (Azure run) if the account exists; otherwise optional Dagster | Azure account |
| 22 to 31 Dec | Walkthrough, interview practice, exam booking | |

Learning notes: each step adds its own section to `docs/learning_notes.md`
(what, why, interview questions), as before. Nothing in this plan has been
run yet; each step will be marked verified only after it runs on your laptop,
Databricks or GitHub.

## Decisions for you

1. **Where to run Databricks:** Free Edition now + one Azure run in December
   (recommended), Free Edition only, or wait for Azure.
2. **Orchestrator:** Lakeflow Jobs now, Dagster only if time (recommended), or
   Dagster as well from the start.
3. **Orphan rows:** inferred members (recommended) or keep `-1` and just
   document it.
4. **Azure scope:** the earlier Azure plan also had Synapse serverless +
   Power BI. With Databricks added, keep that or drop it to save time?
   (Recommended: drop Synapse; Power BI should be able to read the Databricks SQL warehouse, to test.)
5. **Exam date:** booking a date (e.g. mid-January) helps keep the pace;
   the build finishes in December either way.
