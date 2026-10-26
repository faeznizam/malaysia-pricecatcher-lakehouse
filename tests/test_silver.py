from datetime import date, datetime

import pytest

from pricecatcher import silver

PRICE_SCHEMA = "date date, premise_code bigint, item_code bigint, price double, year_month string, _source_file string, _ingested_at timestamp"
LOADED = datetime(2026, 9, 30, 12, 0)

# Item 10 normally costs RM5-6 (median 5.0), so 10x the median is RM50 and 1/10 is RM0.50.
SEPTEMBER = [
    (date(2026, 9, 1), 1, 10, 5.0),
    (date(2026, 9, 1), 1, 10, 5.0),    # duplicate of the row above
    (date(2026, 9, 1), 2, 10, 5.0),
    (date(2026, 9, 2), 1, 10, 6.0),
    (date(2026, 9, 2), 2, 10, 6.0),
    (date(2026, 9, 2), 3, 10, 60.0),   # 12x the median: missing decimal point
    (date(2026, 9, 3), 1, 10, 0.4),    # 1/12 of the median: too low
    (date(2026, 9, 3), 2, 10, 0.0),    # zero (also too low)
    (date(2026, 9, 3), 3, 10, None),   # missing price
    (date(2026, 9, 3), 7, 10, 5.5),    # premise 7 is not in the lookup: warn only
    (date(2026, 9, 5), 1, 99, 3.0),    # item 99 is not in the lookup: warn only; 4 Sept has no data
]


@pytest.fixture(scope="module")
def lake(spark, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("lake")
    rows = [(*r, "2026-09", "pricecatcher_2026-09.parquet", LOADED) for r in SEPTEMBER]
    spark.createDataFrame(rows, PRICE_SCHEMA).write.format("delta").partitionBy("year_month").save(
        str(tmp_path / "bronze" / "prices"))
    spark.createDataFrame([(10, "Beras")], "item_code bigint, item string").write.format("delta").save(
        str(tmp_path / "bronze" / "lookup_item"))
    spark.createDataFrame([(1, "A"), (2, "B"), (3, "C")], "premise_code bigint, premise string").write.format(
        "delta").save(str(tmp_path / "bronze" / "lookup_premise"))
    return tmp_path


def read(spark, lake, table):
    return spark.read.format("delta").load(str(lake / table))


def errors_by_row(spark, lake):
    rows = read(spark, lake, "silver/quarantine").collect()
    return {(r["date"].day, r["premise_code"], r["price"]): sorted(r["dq_errors"]) for r in rows}


@pytest.fixture(scope="module")
def run(spark, lake):
    """Silver runs once for the module; the tests below read its output."""
    assert silver.main(["--lake", str(lake)]) == 0
    return lake


def test_every_row_ends_up_in_silver_or_quarantine(spark, run):
    clean = read(spark, run, "silver/prices").count()
    quarantined = read(spark, run, "silver/quarantine").count()
    assert clean + quarantined == len(SEPTEMBER)
    assert clean >= 6  # the 5 normal item-10 rows plus item 99 (premise 7 too, warn only)


def test_clean_prices_are_exact_money(spark, run):
    assert dict(read(spark, run, "silver/prices").dtypes)["price"] == "decimal(10,2)"


def test_duplicates_nulls_and_zero_prices_are_quarantined(spark, run):
    errors = errors_by_row(spark, run)
    assert errors[(1, 1, 5.0)] == ["duplicate_key"]
    assert errors[(3, 3, None)] == ["null_field"]
    assert "price_not_positive" in errors[(3, 2, 0.0)]


def test_price_too_high_is_quarantined(spark, run):
    assert errors_by_row(spark, run)[(2, 3, 60.0)] == ["price_too_high"]


def test_price_too_low_is_quarantined(spark, run):
    """Prices 10x or more below their item's median are quarantined."""
    errors = errors_by_row(spark, run)
    assert errors[(3, 1, 0.4)] == ["price_too_low"]
    assert errors[(3, 2, 0.0)] == ["price_not_positive", "price_too_low"]


def test_unknown_codes_stay_in_silver_with_a_warning(spark, run):
    warned = {(r["premise_code"], r["item_code"]): r["dq_warnings"]
              for r in read(spark, run, "silver/prices").collect() if r["dq_warnings"]}
    assert warned == {(7, 10): ["unknown_premise"], (1, 99): ["unknown_item"]}


def test_run_log_counts_each_rule(spark, run):
    log = {r["check_name"]: r["rows"] for r in read(spark, run, "meta/dq_run_log").collect()}
    assert log["duplicate_key"] == 1
    assert log["price_too_high"] == 1
    assert log["unknown_item"] == 1
    assert log["days_without_data"] == 1
    assert log["rows_quarantined"] == read(spark, run, "silver/quarantine").count()


def test_rerun_replaces_the_month_and_appends_to_the_log(spark, run):
    before = read(spark, run, "silver/prices").count()
    assert silver.main(["--lake", str(run)]) == 0
    assert read(spark, run, "silver/prices").count() == before
    assert read(spark, run, "meta/dq_run_log").select("run_id").distinct().count() == 2


def test_no_bronze_is_an_error(tmp_path):
    assert silver.main(["--lake", str(tmp_path)]) == 1
