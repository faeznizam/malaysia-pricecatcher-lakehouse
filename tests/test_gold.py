from datetime import date
from decimal import Decimal

import pytest
from pyspark.sql import functions as F

from pricecatcher import gold

SILVER_SCHEMA = "date date, premise_code bigint, item_code bigint, price decimal(10,2), year_month string"

# Two states, two premises each. Item 10 is sold everywhere; item 20 only in Johor.
# In October premise 4 (a pricier Selangor shop) stops reporting item 10 and premise 5
# (a cheap new one) starts: the naive average falls, but every matched shop got dearer.
SILVER = [
    # September
    (date(2026, 9, 1), 1, 10, "5.00", "2026-09"),   # Johor
    (date(2026, 9, 1), 2, 10, "5.00", "2026-09"),   # Johor
    (date(2026, 9, 1), 3, 10, "6.00", "2026-09"),   # Selangor
    (date(2026, 9, 1), 4, 10, "8.00", "2026-09"),   # Selangor
    (date(2026, 9, 1), 1, 20, "3.00", "2026-09"),
    # October
    (date(2026, 10, 1), 1, 10, "5.50", "2026-10"),
    (date(2026, 10, 1), 2, 10, "5.50", "2026-10"),
    (date(2026, 10, 1), 3, 10, "6.60", "2026-10"),
    (date(2026, 10, 1), 5, 10, "3.00", "2026-10"),  # new cheap premise
    (date(2026, 10, 3), 1, 99, "2.00", "2026-10"),  # item 99 not in the lookup
]


@pytest.fixture(scope="module")
def lake(spark, tmp_path_factory):
    lake = tmp_path_factory.mktemp("lake")
    spark.createDataFrame([(d, p, i, Decimal(v), m) for d, p, i, v, m in SILVER],
                          SILVER_SCHEMA).write.format("delta").partitionBy("year_month").save(
        str(lake / "silver" / "prices"))
    spark.createDataFrame(
        [(-1, None, None, None, None), (10, "Beras", "kg", "BARANGAN KERING", "BERAS"),
         (20, "Gula", "kg", "BARANGAN KERING", "GULA")],
        "item_code bigint, item string, unit string, item_group string, item_category string",
    ).write.format("delta").save(str(lake / "bronze" / "lookup_item"))
    spark.createDataFrame(
        [(-1, "Unknown Premise", "Unknown Address", None, None, None),
         (1, "A", "a", "Pasar Raya", "Johor", "JB"), (2, "B", "b", "Pasar Raya", "Johor", "JB"),
         (3, "C", "c", "Kedai Runcit", "Selangor", "Petaling"), (4, "D", "d", "Pasar Raya", "Selangor", "Petaling"),
         (5, "E", "e", "Kedai Runcit", "Selangor", "Klang")],
        "premise_code bigint, premise string, address string, premise_type string, state string, district string",
    ).write.format("delta").save(str(lake / "bronze" / "lookup_premise"))
    # The fixture is tiny, so lower the minimum sample for matched changes.
    minimum, gold.MIN_MATCHED_PREMISES = gold.MIN_MATCHED_PREMISES, 3
    try:
        assert gold.main(["--lake", str(lake)]) == 0
    finally:
        gold.MIN_MATCHED_PREMISES = minimum
    return lake


def read(spark, lake, table):
    return spark.read.format("delta").load(str(lake / "gold" / table))


def test_unknown_item_points_to_minus_one_and_keeps_source_code(spark, lake):
    row = read(spark, lake, "fact_price").filter("source_item_code = 99").first()
    assert row["item_code"] == -1
    assert read(spark, lake, "dim_item").filter("item_code = -1").first()["item"] == "Unknown item"


def test_every_fact_row_joins_to_its_dimensions(spark, lake):
    fact = read(spark, lake, "fact_price")
    assert fact.count() == len(SILVER)
    assert fact.join(read(spark, lake, "dim_item"), "item_code").count() == len(SILVER)
    assert fact.join(read(spark, lake, "dim_premise"), "premise_code").count() == len(SILVER)
    assert fact.join(read(spark, lake, "dim_date"), "date").count() == len(SILVER)


def test_dim_date_covers_every_day(spark, lake):
    assert read(spark, lake, "dim_date").count() == 33  # 1 Sept to 3 Oct, no gaps


def test_matched_change_ignores_the_shop_mix(spark, lake):
    mom = read(spark, lake, "mart_item_mom").filter("item_code = 10").first()
    # naive: Sept average 6.00 -> Oct average 5.15 looks like a 14% fall
    assert mom["naive_change_pct"] == pytest.approx(-14.17, abs=0.01)
    # matched: premises 1-3 reported both months and each rose 10%
    assert mom["matched_premises"] == 3
    assert mom["matched_change_pct"] == pytest.approx(10.0, abs=0.01)


def test_small_samples_get_no_matched_change(spark, lake):
    # With the real minimum (20 premises), 3 matched premises is too few to report.
    mom = gold.build_mart_item_mom(read(spark, lake, "fact_price"), read(spark, lake, "dim_item"))
    row = mom.filter("item_code = 10").first()
    assert row["enough_sample"] is False
    assert row["matched_change_pct"] is None


def test_state_index_uses_the_common_basket(spark, lake):
    rows = {r["state"]: r for r in read(spark, lake, "mart_state_index").filter("year_month = '2026-09'").collect()}
    assert rows["Johor"]["basket_items"] == 1  # item 20 isn't sold in Selangor
    # item 10 national median 5.50; Johor median 5.00 -> 90.9, Selangor median 7.00 -> 127.3
    assert rows["Johor"]["price_index"] == pytest.approx(90.9)
    assert rows["Selangor"]["price_index"] == pytest.approx(127.3)
    assert rows["Selangor"]["rank_most_expensive"] == 1


def test_no_silver_is_an_error(tmp_path):
    assert gold.main(["--lake", str(tmp_path)]) == 1


def test_premise_type_index_compares_shop_types(spark, lake):
    rows = {r["premise_type"]: r for r in
            read(spark, lake, "mart_premise_type_index").filter("year_month = '2026-09'").collect()}
    # Sept item 10: Pasar Raya 5.00, 5.00, 8.00 -> median 5.00; Kedai Runcit 6.00; national 5.50
    assert rows["Pasar Raya"]["price_index"] == pytest.approx(90.9)
    assert rows["Kedai Runcit"]["price_index"] == pytest.approx(109.1)
    assert rows["Kedai Runcit"]["basket_items"] == 1  # item 20 only at a Pasar Raya


def test_item_group_change_uses_matched_items(spark, lake):
    row = read(spark, lake, "mart_item_group_mom").filter("item_group = 'BARANGAN KERING'").first()
    assert row["items"] == 1  # only item 10 has both months with enough shops (fixture minimum 3)
    assert row["median_change_pct"] == pytest.approx(10.0)
    assert (row["items_up"], row["items_down"]) == (1, 0)


def test_premise_labels_are_tidied(spark):
    raw = spark.createDataFrame(
        [(1, "Pasar Basah", "Johor"), (2, "Pasar Basah ", " Johor"), (3, "Pasar Basah", None),
         (4, "Pasar Basah​", "")],
        "premise_code bigint, premise_type string, state string",
    ).withColumn("premise", F.lit("x")).withColumn("address", F.lit("x")).withColumn("district", F.lit("x"))
    dim = gold.build_dim_premise(raw)
    assert {r["premise_type"] for r in dim.collect()} == {"Pasar Basah"}
    assert sorted(r["state"] for r in dim.collect()) == ["Johor", "Johor", "Unknown", "Unknown"]


def test_price_trend_chains_from_a_base_of_100(spark, lake):
    rows = {r["year_month"]: r for r in
            read(spark, lake, "mart_price_trend").filter("item_group = 'ALL ITEMS'").collect()}
    assert rows["2026-09"]["price_index"] == 100.0
    # item 10, the only item with enough matched shops, rose 10%
    assert rows["2026-10"]["price_index"] == pytest.approx(110.0)
    assert rows["2026-10"]["change_pct"] == pytest.approx(10.0)
    assert rows["2026-10"]["items"] == 1


def test_price_trend_handles_one_month(spark):
    empty = spark.createDataFrame([], "item_code bigint, year_month string, prev_month string, "
                                      "matched_change_pct double, enough_sample boolean, item_group string")
    assert gold.build_mart_price_trend(empty).count() == 0
