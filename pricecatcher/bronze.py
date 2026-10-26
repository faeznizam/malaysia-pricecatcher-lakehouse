"""Bronze: load the raw landing files into Delta tables.

Bronze keeps the data as published (no cleaning, no rows dropped) but
checks it against a schema contract and adds where each row came from:

    <lake>/bronze/prices          partitioned by year_month, one load per month
    <lake>/bronze/lookup_item     full snapshot, replaced on every load
    <lake>/bronze/lookup_premise  full snapshot, replaced on every load

Loads are idempotent: loading a month again replaces that month only,
so re-running never duplicates rows.

data.gov.my compresses its Parquet files with Brotli, which Spark cannot
read without an extra native codec. So each landing file is first
re-encoded unchanged (same rows, same columns) to zstd in
<lake>/_staging/ with DuckDB, and Spark reads that copy.

Usage:
    python -m pricecatcher.bronze                   # every month in landing
    python -m pricecatcher.bronze --months 2026-10  # just one month
"""

import argparse
import os
import re
import sys
from pathlib import Path

import duckdb
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from pricecatcher.download import DEFAULT_LANDING, LOOKUP_FILES, price_filename
from pricecatcher.profile import sql_string

DEFAULT_LAKE = os.environ.get("LAKE_ROOT", "lake")

# Columns we rely on downstream, with the Spark type each must have.
PRICE_CONTRACT = {"date": "date", "premise_code": "bigint", "item_code": "bigint", "price": "double"}
LOOKUP_CONTRACTS = {
    "lookup_item": {
        "item_code": "bigint", "item": "string", "unit": "string",
        "item_group": "string", "item_category": "string",
    },
    "lookup_premise": {
        "premise_code": "bigint", "premise": "string", "address": "string",
        "premise_type": "string", "state": "string", "district": "string",
    },
}


class SchemaContractError(Exception):
    """A landing file is missing a column we depend on."""


def apply_contract(df: DataFrame, contract: dict, source: str) -> DataFrame:
    """Keep the contract's columns, cast to the contract's types.

    A missing column fails the load. A value that cannot be cast also
    fails (Spark 4 casts strictly), instead of silently becoming null.
    New extra columns are ignored, so the publisher adding a column
    doesn't break the pipeline.
    """
    missing = sorted(set(contract) - set(df.columns))
    if missing:
        raise SchemaContractError(f"{source} is missing column(s) {missing}; found {df.columns}")
    return df.select([F.col(name).cast(dtype).alias(name) for name, dtype in contract.items()])


def read_landing(spark: SparkSession, source: Path, lake: Path) -> DataFrame:
    """Read a landing Parquet file via a zstd copy Spark can decode."""
    staged = lake / "_staging" / source.name
    staged.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    con.execute(
        f"COPY (SELECT * FROM read_parquet({sql_string(source)})) "
        f"TO {sql_string(staged)} (FORMAT parquet, COMPRESSION zstd)"
    )
    return spark.read.parquet(str(staged))


def with_lineage(df: DataFrame, source: Path) -> DataFrame:
    return df.withColumn("_source_file", F.lit(source.name)).withColumn("_ingested_at", F.current_timestamp())


def load_prices(spark: SparkSession, source: Path, lake: Path) -> int:
    """Load one month's price file, replacing that month in bronze."""
    month = re.search(r"(\d{4}-\d{2})", source.name).group(1)
    df = apply_contract(read_landing(spark, source, lake), PRICE_CONTRACT, source.name)

    outside = df.filter(F.date_format("date", "yyyy-MM") != month).count()
    if outside:
        raise ValueError(f"{source.name} has {outside:,} rows dated outside {month}")

    df = with_lineage(df, source).withColumn("year_month", F.lit(month))
    rows = df.count()
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"year_month = '{month}'")
        .partitionBy("year_month")
        .save(str(lake / "bronze" / "prices"))
    )
    return rows


def load_lookup(spark: SparkSession, source: Path, lake: Path) -> int:
    """Replace a lookup table with the latest snapshot."""
    name = source.stem
    raw = read_landing(spark, source, lake)
    df = with_lineage(apply_contract(raw, LOOKUP_CONTRACTS[name], source.name), source)
    rows = df.count()
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(str(lake / "bronze" / name))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--months", nargs="+", help="Months to load, e.g. 2026-10 (default: all in landing)")
    parser.add_argument("--landing", default=DEFAULT_LANDING, help="Landing folder (default: $LANDING_DIR or data/landing)")
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="Lake folder (default: $LAKE_ROOT or lake)")
    args = parser.parse_args(argv)

    landing, lake = Path(args.landing), Path(args.lake)
    if args.months:
        price_files = [landing / "prices" / price_filename(m) for m in args.months]
    else:
        price_files = sorted((landing / "prices").glob("pricecatcher_*.parquet"))
    lookup_files = [landing / "lookups" / name for name in LOOKUP_FILES]

    missing = [p for p in price_files + lookup_files if not p.exists()]
    if missing or not price_files:
        print("Missing landing files (run `make download` first):", file=sys.stderr)
        for p in missing or [landing / "prices"]:
            print(f"  {p}", file=sys.stderr)
        return 1

    from pricecatcher.spark import get_spark  # imported here so --help works without Java
    spark = get_spark("pricecatcher-bronze")

    for source in price_files:
        print(f"prices  {source.name:<32} {load_prices(spark, source, lake):>10,} rows")
    for source in lookup_files:
        print(f"lookup  {source.name:<32} {load_lookup(spark, source, lake):>10,} rows")

    print("\nBronze tables now hold:")
    prices = spark.read.format("delta").load(str(lake / "bronze" / "prices"))
    for row in prices.groupBy("year_month").count().orderBy("year_month").collect():
        print(f"  prices {row['year_month']}  {row['count']:>10,} rows")
    for name in LOOKUP_CONTRACTS:
        print(f"  {name:<20}{spark.read.format('delta').load(str(lake / 'bronze' / name)).count():>10,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
