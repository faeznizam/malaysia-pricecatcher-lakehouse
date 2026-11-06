from datetime import date, datetime

import pytest

from pricecatcher import checks
from tests.test_gold import lake as gold_lake  # noqa: F401  (reuses the gold fixture)

LOG_SCHEMA = ("run_id string, run_at timestamp, year_month string, check_name string, "
              "severity string, rows long, rows_checked long")
FACT_SCHEMA = "date date, premise_code bigint, item_code bigint, source_premise_code bigint, source_item_code bigint"


def run_log(spark, rows):
    return spark.createDataFrame(rows, LOG_SCHEMA)


@pytest.fixture(scope="module")
def lake(spark, gold_lake):
    # 1 of 2,000 rows quarantined (0.05%): under the limit.
    run_log(spark, [("run1", datetime(2026, 10, 4, 6), "2026-10", "rows_quarantined", "info", 1, 2000)]) \
        .write.format("delta").mode("overwrite").save(str(gold_lake / "meta" / "dq_run_log"))
    return gold_lake


def by_name(results):
    return {r.name: r for r in results}


def test_sample_gold_passes_with_two_warnings(spark, lake):
    results = by_name(checks.run_checks(spark, lake, today=date(2026, 10, 4)))
    assert {name: r.status for name, r in results.items()} == {
        "freshness": "ok",
        "volume": "warn",         # 3 Oct has 1 row against a usual 4
        "quarantine": "ok",
        "unknown_codes": "warn",  # item 99: 1 of 10 rows
        "unique_key": "ok",
        "joins": "ok",
        "price_index": "ok",
    }
    assert "2026-10-03" in results["volume"].detail


def test_stale_data_fails(spark, lake):
    fact = checks.read(spark, lake, "gold/fact_price")
    assert checks.check_freshness(fact, date(2026, 10, 6)).status == "ok"
    result = checks.check_freshness(fact, date(2026, 10, 7))
    assert result.status == "fail"
    assert "4 day(s) old" in result.detail


def test_quarantine_uses_each_months_latest_run(spark):
    log = run_log(spark, [
        ("run1", datetime(2026, 10, 20, 6), "2026-10", "rows_quarantined", "info", 50, 1000),  # 5%, replaced
        ("run2", datetime(2026, 10, 21, 6), "2026-10", "rows_quarantined", "info", 0, 1000),
        ("run2", datetime(2026, 10, 21, 6), "2026-09", "rows_quarantined", "info", 1, 1000),   # 0.1%
    ])
    assert checks.check_quarantine(log).status == "ok"
    log = log.unionByName(run_log(spark, [
        ("run3", datetime(2026, 10, 22, 6), "2026-10", "rows_quarantined", "info", 2, 1000),  # 0.2%
    ]))
    result = checks.check_quarantine(log)
    assert result.status == "fail"
    assert "2026-10" in result.detail


def test_duplicate_key_fails(spark):
    row = (date(2026, 10, 1), 1, 10, 1, 10)
    fact = spark.createDataFrame([row, row, (date(2026, 10, 1), 2, 10, 2, 10)], FACT_SCHEMA)
    result = checks.check_unique_key(fact)
    assert result.status == "fail"
    assert result.detail.startswith("1 duplicated")


def test_unmatched_fact_row_fails(spark, lake):
    fact = spark.createDataFrame([(date(2026, 10, 1), 1, 777, 1, 777)], FACT_SCHEMA)
    result = checks.check_joins(fact, *(checks.read(spark, lake, f"gold/{t}")
                                        for t in ("dim_item", "dim_premise", "dim_date")))
    assert result.status == "fail"
    assert result.detail == "fact rows with no match: dim_item 1"


def test_price_index_out_of_range_fails(spark):
    good = spark.createDataFrame([(98.5,), (104.0,)], "price_index double")
    assert checks.check_price_index(good).status == "ok"
    bad = spark.createDataFrame([(None,), (250.0,)], "price_index double")
    result = checks.check_price_index(good, bad)
    assert result.status == "fail"
    assert result.detail.startswith("2 value(s)")


def test_main_stops_on_failure_and_logs_every_run(spark, lake, capsys):
    # Today is weeks after the sample's newest price (3 Oct 2026).
    assert checks.main(["--lake", str(lake)]) == 1
    assert "FAIL  freshness" in capsys.readouterr().out
    assert checks.main(["--lake", str(lake), "--max-age-days", "100000"]) == 0
    log = checks.read(spark, lake, "meta/check_log")
    assert log.count() == 14
    assert log.filter("check_name = 'freshness' and status = 'fail'").count() == 1
