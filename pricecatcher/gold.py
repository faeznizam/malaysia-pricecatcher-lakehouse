"""Gold: a star schema and analysis tables built from silver.

Star schema (the shape Power BI expects):
    <lake>/gold/fact_price    one row per price observation (date, premise, item)
    <lake>/gold/dim_item      item names, units and groups
    <lake>/gold/dim_premise   premise names, types and locations
    <lake>/gold/dim_date      one row per calendar day

Codes missing from the lookups point to the -1 "unknown" row that
data.gov.my already includes in each lookup, so every fact row joins.

Analysis tables ("marts"):
    <lake>/gold/mart_item_month          price level and spread per item per month
    <lake>/gold/mart_item_mom            month-on-month change per item, naive and matched
    <lake>/gold/mart_item_group_mom      month-on-month change per item group (matched)
    <lake>/gold/mart_state_index         price level per state on a common basket (Malaysia = 100)
    <lake>/gold/mart_premise_type_index  price level per type of shop, same method

Gold is small, so it is rebuilt in full on every run.

Usage:
    python -m pricecatcher.gold
"""

import argparse
import sys
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from pricecatcher.bronze import DEFAULT_LAKE

UNKNOWN = -1
# A month-on-month change based on fewer premises than this is too noisy to report.
MIN_MATCHED_PREMISES = 20


def read_delta(spark: SparkSession, path: Path) -> DataFrame:
    return spark.read.format("delta").load(str(path))


def write(df: DataFrame, path: Path, partition_by: str | None = None) -> int:
    writer = df.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
    if partition_by:
        writer = writer.partitionBy(partition_by)
    writer.save(str(path))
    return read_delta(df.sparkSession, path).count()


# --- star schema ---------------------------------------------------------------

def build_dim_item(items: DataFrame) -> DataFrame:
    return items.select(
        "item_code",
        F.coalesce("item", F.lit("Unknown item")).alias("item"),
        "unit",
        F.coalesce("item_group", F.lit("UNKNOWN")).alias("item_group"),
        F.coalesce("item_category", F.lit("UNKNOWN")).alias("item_category"),
    )


def build_dim_premise(premises: DataFrame) -> DataFrame:
    return premises.select(
        "premise_code", "premise", "address",
        F.coalesce("premise_type", F.lit("Unknown")).alias("premise_type"),
        F.coalesce("state", F.lit("Unknown")).alias("state"),
        F.coalesce("district", F.lit("Unknown")).alias("district"),
    )


def build_fact_price(prices: DataFrame, dim_item: DataFrame, dim_premise: DataFrame) -> DataFrame:
    """Silver prices with codes mapped onto the dimensions (unknown -> -1)."""
    known_items = dim_item.select(F.col("item_code").alias("_item"))
    known_premises = dim_premise.select(F.col("premise_code").alias("_premise"))
    return (
        prices
        .join(F.broadcast(known_items), prices.item_code == F.col("_item"), "left")
        .join(F.broadcast(known_premises), prices.premise_code == F.col("_premise"), "left")
        .select(
            "date",
            F.coalesce("_premise", F.lit(UNKNOWN)).cast("bigint").alias("premise_code"),
            F.coalesce("_item", F.lit(UNKNOWN)).cast("bigint").alias("item_code"),
            "price",
            F.col("premise_code").alias("source_premise_code"),
            F.col("item_code").alias("source_item_code"),
            "year_month",
        )
    )


def build_dim_date(prices: DataFrame) -> DataFrame:
    bounds = prices.agg(F.min("date").alias("first"), F.max("date").alias("last"))
    days = bounds.select(F.explode(F.sequence("first", "last")).alias("date"))
    return days.select(
        "date",
        F.year("date").alias("year"),
        F.month("date").alias("month"),
        F.date_format("date", "yyyy-MM").alias("year_month"),
        F.dayofmonth("date").alias("day"),
        F.date_format("date", "EEEE").alias("day_name"),
        F.dayofweek("date").isin(1, 7).alias("is_weekend"),
    )


# --- marts -----------------------------------------------------------------------

def build_mart_item_month(fact: DataFrame, dim_item: DataFrame) -> DataFrame:
    """Price level and spread across premises, per item per month."""
    stats = fact.withColumn("price", F.col("price").cast("double")).groupBy("item_code", "year_month").agg(
        F.count("*").alias("observations"),
        F.countDistinct("premise_code").alias("premises"),
        F.round(F.median("price"), 2).alias("median_price"),
        F.round(F.avg("price"), 2).alias("avg_price"),
        F.min("price").alias("min_price"),
        F.max("price").alias("max_price"),
        F.round(F.percentile("price", 0.1), 2).alias("p10_price"),
        F.round(F.percentile("price", 0.9), 2).alias("p90_price"),
    )
    return (
        stats.withColumn("p90_p10_ratio", F.round(F.col("p90_price") / F.col("p10_price"), 2))
        .join(dim_item.select("item_code", "item", "unit", "item_group"), "item_code", "left")
    )


def build_mart_item_mom(fact: DataFrame, dim_item: DataFrame) -> DataFrame:
    """Month-on-month price change per item, two ways.

    naive:   average price this month vs last month, over whichever premises
             reported. Moves when the MIX of premises changes, even if no
             price did.
    matched: only premises that reported the item in both months, each
             compared with itself. This is how official price indices
             avoid the mix problem.
    """
    fact = fact.withColumn("price", F.col("price").cast("double"))
    per_premise = fact.groupBy("item_code", "premise_code", "year_month").agg(F.avg("price").alias("price"))
    months = sorted(r["year_month"] for r in fact.select("year_month").distinct().collect())
    pairs = fact.sparkSession.createDataFrame(list(zip(months[1:], months[:-1])), "year_month string, prev_month string")

    cur = per_premise.join(pairs, "year_month")
    prev = per_premise.select(
        "item_code", "premise_code",
        F.col("year_month").alias("prev_month"), F.col("price").alias("prev_price"),
    )
    matched = (
        cur.join(prev, ["item_code", "premise_code", "prev_month"])
        .groupBy("item_code", "year_month", "prev_month")
        .agg(
            F.count("*").alias("matched_premises"),
            ((F.sum("price") / F.sum("prev_price") - 1) * 100).alias("matched_change_pct"),
        )
    )
    monthly_avg = fact.groupBy("item_code", "year_month").agg(F.avg("price").alias("avg_price"))
    naive = (
        monthly_avg.join(pairs, "year_month")
        .join(monthly_avg.select("item_code", F.col("year_month").alias("prev_month"),
                                 F.col("avg_price").alias("prev_avg_price")),
              ["item_code", "prev_month"])
        .select("item_code", "year_month", "prev_month",
                ((F.col("avg_price") / F.col("prev_avg_price") - 1) * 100).alias("naive_change_pct"))
    )
    return (
        naive.join(matched, ["item_code", "year_month", "prev_month"], "left")
        .fillna({"matched_premises": 0})
        .withColumn("enough_sample", F.col("matched_premises") >= MIN_MATCHED_PREMISES)
        .withColumn("naive_change_pct", F.round("naive_change_pct", 2))
        .withColumn("matched_change_pct",
                    F.when(F.col("enough_sample"), F.round("matched_change_pct", 2)))
        .join(dim_item.select("item_code", "item", "unit", "item_group"), "item_code", "left")
    )


def build_price_index(fact: DataFrame, dim_premise: DataFrame, by: str) -> DataFrame:
    """How expensive each group of premises is, on the same basket of items.

    `by` is a dim_premise column, e.g. state or premise_type. For each month,
    the basket is the items sold in every group. For each item, a group's
    median price is divided by the national median; the group's index is the
    average of those ratios x 100. Malaysia = 100.
    """
    with_group = (
        fact.withColumn("price", F.col("price").cast("double"))
        .join(dim_premise.select("premise_code", by), "premise_code")
        .filter(F.col(by) != "Unknown")
    )
    group_item = with_group.groupBy("year_month", by, "item_code").agg(F.median("price").alias("group_median"))
    national = with_group.groupBy("year_month", "item_code").agg(F.median("price").alias("national_median"))
    groups_per_month = with_group.groupBy("year_month").agg(F.countDistinct(by).alias("n_groups"))
    basket = (
        group_item.groupBy("year_month", "item_code").agg(F.countDistinct(by).alias("groups_selling"))
        .join(groups_per_month, "year_month")
        .filter(F.col("groups_selling") == F.col("n_groups"))
        .select("year_month", "item_code")
    )
    return (
        group_item.join(basket, ["year_month", "item_code"])
        .join(national, ["year_month", "item_code"])
        .groupBy("year_month", by)
        .agg(
            F.count("*").alias("basket_items"),
            F.round(F.avg(F.col("group_median") / F.col("national_median")) * 100, 1).alias("price_index"),
        )
        .withColumn("rank_most_expensive",
                    F.rank().over(Window.partitionBy("year_month").orderBy(F.desc("price_index"))))
    )


def build_mart_state_index(fact: DataFrame, dim_premise: DataFrame) -> DataFrame:
    """Price level per state on a common basket (Malaysia = 100)."""
    return build_price_index(fact, dim_premise, "state")


def build_mart_premise_type_index(fact: DataFrame, dim_premise: DataFrame) -> DataFrame:
    """Price level per type of shop (hypermarket, grocer, wet market...) on a common basket."""
    return build_price_index(fact, dim_premise, "premise_type")


def build_mart_item_group_mom(item_mom: DataFrame) -> DataFrame:
    """Month-on-month change per item group, from the matched item changes.

    Uses the median item, so one item with a big swing can't dominate its group.
    Only items with enough matched premises count.
    """
    return (
        item_mom.filter(F.col("enough_sample"))
        .groupBy("item_group", "year_month", "prev_month")
        .agg(
            F.count("*").alias("items"),
            F.round(F.median("matched_change_pct"), 2).alias("median_change_pct"),
            F.sum((F.col("matched_change_pct") > 0).cast("int")).alias("items_up"),
            F.sum((F.col("matched_change_pct") < 0).cast("int")).alias("items_down"),
        )
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="Lake folder (default: $LAKE_ROOT or lake)")
    args = parser.parse_args(argv)
    lake = Path(args.lake)

    if not (lake / "silver" / "prices" / "_delta_log").exists():
        print(f"No silver prices in {lake}. Run `make silver` first.", file=sys.stderr)
        return 1

    from pricecatcher.spark import get_spark  # imported here so --help works without Java
    spark = get_spark("pricecatcher-gold")
    gold = lake / "gold"

    dim_item = build_dim_item(read_delta(spark, lake / "bronze" / "lookup_item"))
    dim_premise = build_dim_premise(read_delta(spark, lake / "bronze" / "lookup_premise"))
    fact = build_fact_price(read_delta(spark, lake / "silver" / "prices"), dim_item, dim_premise)

    counts = {
        "dim_item": write(dim_item, gold / "dim_item"),
        "dim_premise": write(dim_premise, gold / "dim_premise"),
        "fact_price": write(fact, gold / "fact_price", partition_by="year_month"),
    }
    fact = read_delta(spark, gold / "fact_price")
    counts["dim_date"] = write(build_dim_date(fact), gold / "dim_date")
    counts["mart_item_month"] = write(build_mart_item_month(fact, dim_item), gold / "mart_item_month")
    counts["mart_item_mom"] = write(build_mart_item_mom(fact, dim_item), gold / "mart_item_mom")
    counts["mart_item_group_mom"] = write(build_mart_item_group_mom(read_delta(spark, gold / "mart_item_mom")),
                                          gold / "mart_item_group_mom")
    counts["mart_state_index"] = write(build_mart_state_index(fact, dim_premise), gold / "mart_state_index")
    counts["mart_premise_type_index"] = write(build_mart_premise_type_index(fact, dim_premise),
                                              gold / "mart_premise_type_index")

    print("Gold tables:")
    for name, n in counts.items():
        print(f"  {name:<24} {n:>10,} rows")

    unknown = fact.filter((F.col("item_code") == UNKNOWN) | (F.col("premise_code") == UNKNOWN)).count()
    print(f"\nFact rows pointing to an unknown item or premise: {unknown:,}")

    print("\nState price index, latest month (Malaysia = 100):")
    index = read_delta(spark, gold / "mart_state_index")
    latest = index.agg(F.max("year_month")).first()[0]
    for r in index.filter(F.col("year_month") == latest).orderBy("rank_most_expensive").collect():
        print(f"  {r['rank_most_expensive']:>2}. {r['state']:<20} {r['price_index']:>6}  ({r['basket_items']} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
