"""Silver: apply the data quality rules to bronze prices.

For each month in bronze:
    <lake>/silver/prices       rows that pass every error rule; price as DECIMAL(10,2);
                               warn rule names in dq_warnings
    <lake>/silver/quarantine   rows that fail an error rule, unchanged, with the
                               names of the rules they failed in dq_errors
    <lake>/meta/dq_run_log     one row per rule per month per run: how many rows it caught

Like bronze, each month is replaced as a whole, so re-running is safe.
Quarantined rows are never deleted: if a rule turns out to be wrong, fix
it and re-run, and the rows come back.

Usage:
    python -m pricecatcher.silver                   # every month in bronze
    python -m pricecatcher.silver --months 2026-10  # just one month
"""

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from pricecatcher.bronze import DEFAULT_LAKE
from pricecatcher.dq import RULES, Rule


def read_delta(spark: SparkSession, path: Path) -> DataFrame:
    return spark.read.format("delta").load(str(path))


def prepare(spark: SparkSession, lake: Path, month: str) -> DataFrame:
    """Bronze rows for one month, plus the helper columns the rules use."""
    prices = read_delta(spark, lake / "bronze" / "prices").filter(F.col("year_month") == month)
    items = read_delta(spark, lake / "bronze" / "lookup_item").select("item_code").distinct()
    premises = read_delta(spark, lake / "bronze" / "lookup_premise").select("premise_code").distinct()

    same_key = Window.partitionBy("date", "premise_code", "item_code").orderBy("_ingested_at", "price")
    return (
        prices
        .withColumn("item_median", F.median("price").over(Window.partitionBy("item_code")))
        .withColumn("key_rank", F.row_number().over(same_key))
        .join(F.broadcast(items.withColumn("known_item", F.lit(True))), "item_code", "left")
        .join(F.broadcast(premises.withColumn("known_premise", F.lit(True))), "premise_code", "left")
        .fillna({"known_item": False, "known_premise": False})
    )


def rule_names_failed(rules: list[Rule]):
    """An array column holding the names of the rules this row fails."""
    return F.array_compact(F.array(*[F.when(rule.fails(), F.lit(rule.name)) for rule in rules]))


def evaluate(df: DataFrame, rules: list[Rule] = RULES) -> DataFrame:
    errors = [r for r in rules if r.severity == "error"]
    warnings = [r for r in rules if r.severity == "warn"]
    return df.withColumn("dq_errors", rule_names_failed(errors)).withColumn("dq_warnings", rule_names_failed(warnings))


def days_without_data(df: DataFrame, month: str) -> int:
    """Days from the 1st of the month to the latest date seen (or month end) with no rows."""
    last = df.agg(F.max("date")).first()[0]
    if last is None:
        return 0
    first = datetime.strptime(month, "%Y-%m").date()
    expected = (last - first).days + 1
    return expected - df.select("date").distinct().count()


def write_month(df: DataFrame, path: Path, month: str) -> None:
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"year_month = '{month}'")
        .partitionBy("year_month")
        .save(str(path))
    )


def process_month(spark: SparkSession, lake: Path, month: str, run_id: str) -> dict:
    checked = evaluate(prepare(spark, lake, month)).cache()
    try:
        clean = (
            checked.filter(F.size("dq_errors") == 0)
            .select(
                "date", "premise_code", "item_code",
                F.col("price").cast("decimal(10,2)").alias("price"),
                "dq_warnings", "year_month", "_source_file", "_ingested_at",
            )
            .withColumn("_processed_at", F.current_timestamp())
        )
        quarantine = (
            checked.filter(F.size("dq_errors") > 0)
            .select(
                "date", "premise_code", "item_code", "price", "item_median",
                "dq_errors", "dq_warnings", "year_month", "_source_file", "_ingested_at",
            )
            .withColumn("_processed_at", F.current_timestamp())
        )
        write_month(clean, lake / "silver" / "prices", month)
        write_month(quarantine, lake / "silver" / "quarantine", month)

        counts = checked.agg(
            F.count("*").alias("rows_checked"),
            *[
                F.sum(F.array_contains("dq_errors" if r.severity == "error" else "dq_warnings", r.name).cast("int"))
                .alias(r.name)
                for r in RULES
            ],
            F.sum((F.size("dq_errors") > 0).cast("int")).alias("rows_quarantined"),
        ).first().asDict()
        counts["days_without_data"] = days_without_data(checked, month)
    finally:
        checked.unpersist()

    log_run(spark, lake, run_id, month, counts)
    return counts


def log_run(spark: SparkSession, lake: Path, run_id: str, month: str, counts: dict) -> None:
    run_at = datetime.now(timezone.utc)
    severities = {r.name: r.severity for r in RULES}
    rows = [
        (run_id, run_at, month, name, severities.get(name, "info"), int(value or 0), int(counts["rows_checked"]))
        for name, value in counts.items()
        if name != "rows_checked"
    ]
    schema = "run_id string, run_at timestamp, year_month string, check_name string, severity string, rows long, rows_checked long"
    spark.createDataFrame(rows, schema).write.format("delta").mode("append").save(str(lake / "meta" / "dq_run_log"))


def print_summary(month: str, counts: dict) -> None:
    checked = counts["rows_checked"] or 1
    print(f"\n{month}: {counts['rows_checked']:,} rows checked, {counts['rows_quarantined']:,} quarantined, "
          f"{counts['days_without_data']} day(s) without data")
    for rule in RULES:
        n = counts[rule.name] or 0
        print(f"  {rule.severity:<5}  {rule.name:<20} {n:>8,}  ({n / checked:.4%})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--months", nargs="+", help="Months to process, e.g. 2026-10 (default: all in bronze)")
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="Lake folder (default: $LAKE_ROOT or lake)")
    args = parser.parse_args(argv)
    lake = Path(args.lake)

    if not (lake / "bronze" / "prices" / "_delta_log").exists():
        print(f"No bronze prices in {lake}. Run `make bronze` first.", file=sys.stderr)
        return 1

    from pricecatcher.spark import get_spark  # imported here so --help works without Java
    spark = get_spark("pricecatcher-silver")

    months = args.months or sorted(
        r["year_month"] for r in read_delta(spark, lake / "bronze" / "prices").select("year_month").distinct().collect()
    )
    run_id = uuid.uuid4().hex[:12]
    print(f"Silver run {run_id}")
    for month in months:
        print_summary(month, process_month(spark, lake, month, run_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
