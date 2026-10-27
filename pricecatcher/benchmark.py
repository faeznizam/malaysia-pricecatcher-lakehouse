"""Benchmark: how should fact_price be laid out on disk?

Copies gold/fact_price into four layouts under <lake>/benchmark/ and times
three typical queries on each:

    unpartitioned     one table, no folders
    by_month          one folder per year_month (what gold uses)
    by_month_zorder   by_month, then OPTIMIZE ZORDER BY item_code, which sorts
                      rows so each file holds a narrow range of items
    by_day            one folder per date (over-partitioned on purpose)

Queries:
    one_month    rows and average price for the latest month
    one_item     daily median price of one item across all months
    full_scan    median price per item per month (what the marts do)

Each query runs once to warm up, then REPEATS times; the median is reported.
Results are printed as a Markdown table, ready to paste into docs.

Usage:
    python -m pricecatcher.benchmark
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

from pricecatcher.bronze import DEFAULT_LAKE

REPEATS = 3
LAYOUTS = ["unpartitioned", "by_month", "by_month_zorder", "by_day"]


def write_layout(spark, fact, path: Path, layout: str) -> float:
    """Write fact in the given layout; return seconds taken."""
    start = time.perf_counter()
    writer = fact.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
    if layout in ("by_month", "by_month_zorder"):
        writer = writer.partitionBy("year_month")
    elif layout == "by_day":
        writer = writer.partitionBy("date")
    writer.save(str(path))
    if layout == "by_month_zorder":
        spark.sql(f"OPTIMIZE delta.`{path.resolve()}` ZORDER BY (item_code)")
    return time.perf_counter() - start


def table_files(spark, path: Path) -> tuple[int, float]:
    """Number of data files and total size in MB in the current table version."""
    detail = spark.sql(f"DESCRIBE DETAIL delta.`{path.resolve()}`").first()
    return detail["numFiles"], detail["sizeInBytes"] / 1_000_000


def queries(spark, path: Path, latest_month: str, item_code: int) -> dict:
    """Each query as a function that runs it to completion."""
    from pyspark.sql import functions as F

    def fact():
        return spark.read.format("delta").load(str(path))

    return {
        "one_month": lambda: fact().filter(F.col("year_month") == latest_month)
        .agg(F.count("*"), F.avg("price")).collect(),
        "one_item": lambda: fact().filter(F.col("item_code") == item_code)
        .groupBy("date").agg(F.median("price")).collect(),
        "full_scan": lambda: fact().groupBy("item_code", "year_month").agg(F.median("price")).collect(),
    }


def run_benchmark(spark, lake: Path, repeats: int = REPEATS) -> list[dict]:
    from pyspark.sql import functions as F

    fact = spark.read.format("delta").load(str(lake / "gold" / "fact_price"))
    latest_month = fact.agg(F.max("year_month")).first()[0]
    # The most-recorded item, so one_item has real work to do.
    item_code = fact.groupBy("item_code").count().orderBy(F.desc("count")).first()["item_code"]

    results, runs = {}, {}
    for layout in LAYOUTS:
        path = lake / "benchmark" / layout
        print(f"Writing {layout} ...", flush=True)
        write_s = write_layout(spark, fact, path, layout)
        files, size_mb = table_files(spark, path)
        results[layout] = {"layout": layout, "files": files, "size_mb": size_mb, "write_s": write_s}
        runs[layout] = queries(spark, path, latest_month, item_code)

    # Round-robin over layouts, so none gains from running later on a warmer JVM.
    # Round 0 is a warm-up and is not counted.
    times = {(layout, name): [] for layout in LAYOUTS for name in runs[layout]}
    for round_no in range(repeats + 1):
        print(f"Query round {round_no}{' (warm-up)' if round_no == 0 else ''} ...", flush=True)
        for layout in LAYOUTS:
            for name, run in runs[layout].items():
                start = time.perf_counter()
                run()
                if round_no:
                    times[(layout, name)].append(time.perf_counter() - start)
    for (layout, name), values in times.items():
        results[layout][name] = statistics.median(values)
    return list(results.values())


def to_markdown(results: list[dict]) -> str:
    lines = [
        "| Layout | Files | Size (MB) | Write (s) | one_month (s) | one_item (s) | full_scan (s) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['layout']} | {r['files']:,} | {r['size_mb']:.1f} | {r['write_s']:.1f} "
            f"| {r['one_month']:.2f} | {r['one_item']:.2f} | {r['full_scan']:.2f} |"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="Lake folder (default: $LAKE_ROOT or lake)")
    parser.add_argument("--repeats", type=int, default=REPEATS, help=f"Timed runs per query (default: {REPEATS})")
    args = parser.parse_args(argv)
    lake = Path(args.lake)
    if not (lake / "gold" / "fact_price" / "_delta_log").exists():
        print(f"No gold tables in {lake}. Run `make gold` first.", file=sys.stderr)
        return 1

    from pricecatcher.spark import get_spark  # imported here so --help works without Java
    spark = get_spark("pricecatcher-benchmark")
    rows = spark.read.format("delta").load(str(lake / "gold" / "fact_price")).count()
    results = run_benchmark(spark, lake, args.repeats)
    print(f"\nfact_price: {rows:,} rows. Median of {args.repeats} runs after one warm-up.\n")
    print(to_markdown(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
