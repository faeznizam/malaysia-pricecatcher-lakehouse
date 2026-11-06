"""Checks: is today's output safe to publish?

Runs after gold, before the report. Each check looks at the real tables
(the unit tests only cover small sample data) and returns one of:

    ok     nothing to report
    warn   worth a look, but the report is still published
    fail   stop: the report is not rebuilt, so the live website keeps
           yesterday's numbers instead of showing bad ones

Checks:
    freshness      the newest price is at most MAX_AGE_DAYS old
    volume         no recent day has far fewer rows than a normal day
    quarantine     each month's latest silver run quarantined at most MAX_QUARANTINE_PCT
    unknown_codes  at most MAX_UNKNOWN_PCT of prices use codes missing from the lookups
    unique_key     one fact row per (date, premise, item)
    joins          every fact row joins to dim_item, dim_premise and dim_date
    price_index    every state and shop-type index is between INDEX_RANGE

Every run is appended to <lake>/meta/check_log.

Usage:
    python -m pricecatcher.checks
    python -m pricecatcher.checks --max-age-days 30   # e.g. on an old local copy
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from pricecatcher.bronze import DEFAULT_LAKE
from pricecatcher.gold import UNKNOWN

MAX_AGE_DAYS = 3            # data.gov.my is normally one day behind
VOLUME_DAYS = 14            # recent days checked for volume
MIN_DAY_SHARE = 0.5         # a day with under half the usual rows is suspicious
MAX_QUARANTINE_PCT = 0.1    # real runs quarantine under 0.01%
MAX_UNKNOWN_PCT = 5.0       # real data is about 1.6%
INDEX_RANGE = (50.0, 200.0)  # real indexes sit between about 95 and 110


@dataclass
class Result:
    name: str
    status: str  # ok | warn | fail
    detail: str


def read(spark: SparkSession, lake: Path, table: str) -> DataFrame:
    return spark.read.format("delta").load(str(lake / table))


def today_in_malaysia() -> date:
    return datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date()


def check_freshness(fact: DataFrame, today: date, max_age_days: int = MAX_AGE_DAYS) -> Result:
    newest = fact.agg(F.max("date")).first()[0]
    age = (today - newest).days
    status = "ok" if age <= max_age_days else "fail"
    return Result("freshness", status, f"newest price {newest}, {age} day(s) old (limit {max_age_days})")


def check_volume(fact: DataFrame) -> Result:
    per_day = fact.groupBy("date").count()
    usual = per_day.agg(F.median("count")).first()[0]
    newest = per_day.agg(F.max("date")).first()[0]
    recent = per_day.filter(F.col("date") > F.date_sub(F.lit(newest), VOLUME_DAYS))
    low = [r["date"] for r in recent.filter(F.col("count") < usual * MIN_DAY_SHARE).orderBy("date").collect()]
    if not low:
        return Result("volume", "ok", f"last {VOLUME_DAYS} days all near the usual {usual:,.0f} rows a day")
    days = ", ".join(str(d) for d in low)
    return Result("volume", "warn", f"under {MIN_DAY_SHARE:.0%} of the usual {usual:,.0f} rows a day on: {days}")


def check_quarantine(run_log: DataFrame, max_pct: float = MAX_QUARANTINE_PCT) -> Result:
    latest = run_log.groupBy("year_month").agg(F.max("run_at").alias("run_at"))
    rates = (
        run_log.join(latest, ["year_month", "run_at"])
        .filter(F.col("check_name") == "rows_quarantined")
        .select("year_month", (F.col("rows") / F.col("rows_checked") * 100).alias("pct"))
        .orderBy("year_month")
        .collect()
    )
    worst = max(rates, key=lambda r: r["pct"])
    status = "fail" if worst["pct"] > max_pct else "ok"
    return Result("quarantine", status,
                  f"highest {worst['pct']:.3f}% in {worst['year_month']} (limit {max_pct}%)")


def check_unknown_codes(fact: DataFrame, max_pct: float = MAX_UNKNOWN_PCT) -> Result:
    row = fact.agg(
        F.count("*").alias("rows"),
        F.sum(((F.col("item_code") == UNKNOWN) | (F.col("premise_code") == UNKNOWN)).cast("int")).alias("unknown"),
    ).first()
    pct = row["unknown"] / row["rows"] * 100
    status = "warn" if pct > max_pct else "ok"
    return Result("unknown_codes", status, f"{row['unknown']:,} of {row['rows']:,} prices ({pct:.2f}%, limit {max_pct}%)")


def check_unique_key(fact: DataFrame) -> Result:
    key = ["date", "source_premise_code", "source_item_code"]
    dupes = fact.groupBy(key).count().filter(F.col("count") > 1).count()
    return Result("unique_key", "fail" if dupes else "ok", f"{dupes:,} duplicated (date, premise, item) keys")


def check_joins(fact: DataFrame, dim_item: DataFrame, dim_premise: DataFrame, dim_date: DataFrame) -> Result:
    missing = {
        "dim_item": fact.join(dim_item, "item_code", "left_anti").count(),
        "dim_premise": fact.join(dim_premise, "premise_code", "left_anti").count(),
        "dim_date": fact.join(dim_date, "date", "left_anti").count(),
    }
    broken = {dim: n for dim, n in missing.items() if n}
    if not broken:
        return Result("joins", "ok", "every fact row joins to dim_item, dim_premise and dim_date")
    return Result("joins", "fail", "fact rows with no match: " + ", ".join(f"{d} {n:,}" for d, n in broken.items()))


def check_price_index(*indexes: DataFrame) -> Result:
    low, high = INDEX_RANGE
    values = indexes[0].select("price_index")
    for index in indexes[1:]:
        values = values.unionByName(index.select("price_index"))
    row = values.agg(
        F.min("price_index").alias("lowest"), F.max("price_index").alias("highest"),
        F.sum((F.col("price_index").isNull() | (F.col("price_index") < low) | (F.col("price_index") > high))
              .cast("int")).alias("bad"),
    ).first()
    status = "fail" if row["bad"] else "ok"
    return Result("price_index", status,
                  f"{row['bad']} value(s) outside {low:g}-{high:g} (range {row['lowest']} to {row['highest']})")


def run_checks(spark: SparkSession, lake: Path, today: date, max_age_days: int = MAX_AGE_DAYS) -> list[Result]:
    fact = read(spark, lake, "gold/fact_price")
    return [
        check_freshness(fact, today, max_age_days),
        check_volume(fact),
        check_quarantine(read(spark, lake, "meta/dq_run_log")),
        check_unknown_codes(fact),
        check_unique_key(fact),
        check_joins(fact, read(spark, lake, "gold/dim_item"), read(spark, lake, "gold/dim_premise"),
                    read(spark, lake, "gold/dim_date")),
        check_price_index(read(spark, lake, "gold/mart_state_index"),
                          read(spark, lake, "gold/mart_premise_type_index")),
    ]


def log_checks(spark: SparkSession, lake: Path, results: list[Result]) -> None:
    run_at = datetime.now()
    rows = [(run_at, r.name, r.status, r.detail) for r in results]
    spark.createDataFrame(rows, "run_at timestamp, check_name string, status string, detail string") \
        .write.format("delta").mode("append").save(str(lake / "meta" / "check_log"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="Lake folder (default: $LAKE_ROOT or lake)")
    parser.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS,
                        help=f"Oldest acceptable newest price, in days (default: {MAX_AGE_DAYS})")
    args = parser.parse_args(argv)
    lake = Path(args.lake)
    if not (lake / "gold" / "fact_price" / "_delta_log").exists():
        print(f"No gold tables in {lake}. Run `make gold` first.", file=sys.stderr)
        return 1

    from pricecatcher.spark import get_spark  # imported here so --help works without Java
    spark = get_spark("pricecatcher-checks")
    results = run_checks(spark, lake, today_in_malaysia(), args.max_age_days)
    log_checks(spark, lake, results)

    for r in results:
        print(f"{r.status.upper():<5} {r.name:<14} {r.detail}")
    failed = [r.name for r in results if r.status == "fail"]
    if failed:
        print(f"\nStopped: {', '.join(failed)} failed, so the report is not rebuilt.", file=sys.stderr)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
