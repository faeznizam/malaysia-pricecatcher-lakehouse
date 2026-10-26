# Fixtures use Brotli compression, like the files data.gov.my publishes.
import duckdb
import pytest

from pricecatcher import bronze


def write_prices(path, rows, price_type="DOUBLE"):
    values = ", ".join(f"(DATE '{d}', {p}, {i}, {v})" for d, p, i, v in rows)
    duckdb.execute(f"""
        COPY (SELECT date, premise_code::BIGINT AS premise_code, item_code::BIGINT AS item_code,
                     price::{price_type} AS price
              FROM (VALUES {values}) t(date, premise_code, item_code, price))
        TO '{path}' (FORMAT parquet, COMPRESSION brotli)
    """)


@pytest.fixture
def landing(tmp_path):
    (tmp_path / "prices").mkdir()
    (tmp_path / "lookups").mkdir()
    write_prices(tmp_path / "prices" / "pricecatcher_2026-09.parquet",
                 [("2026-09-01", 1, 10, 5.0), ("2026-09-02", 2, 10, 6.0)])
    write_prices(tmp_path / "prices" / "pricecatcher_2026-10.parquet",
                 [("2026-10-10", 1, 10, 5.5)])
    duckdb.execute(f"""
        COPY (SELECT * FROM (VALUES (10::BIGINT, 'Beras', 'kg', 'BARANGAN KERING', 'BERAS', 'extra'))
              t(item_code, item, unit, item_group, item_category, new_column))
        TO '{tmp_path}/lookups/lookup_item.parquet' (FORMAT parquet, COMPRESSION brotli)
    """)
    duckdb.execute(f"""
        COPY (SELECT * FROM (VALUES (1::BIGINT, 'Kedai A', 'Jalan 1', 'Kedai Runcit', 'Selangor', 'Petaling'))
              t(premise_code, premise, address, premise_type, state, district))
        TO '{tmp_path}/lookups/lookup_premise.parquet' (FORMAT parquet, COMPRESSION brotli)
    """)
    return tmp_path


def read(spark, lake, table):
    return spark.read.format("delta").load(str(lake / "bronze" / table))


def month_counts(spark, lake):
    rows = read(spark, lake, "prices").groupBy("year_month").count().collect()
    return {r["year_month"]: r["count"] for r in rows}


def test_loads_all_months_and_lookups(spark, landing, tmp_path):
    lake = tmp_path / "lake"
    assert bronze.main(["--landing", str(landing), "--lake", str(lake)]) == 0
    assert month_counts(spark, lake) == {"2026-09": 2, "2026-10": 1}
    assert read(spark, lake, "lookup_item").count() == 1
    assert read(spark, lake, "lookup_premise").count() == 1


def test_adds_lineage_and_keeps_contract_types(spark, landing, tmp_path):
    lake = tmp_path / "lake"
    bronze.main(["--landing", str(landing), "--lake", str(lake)])
    prices = read(spark, lake, "prices")
    assert dict(prices.dtypes)["price"] == "double"
    assert dict(prices.dtypes)["date"] == "date"
    assert {r["_source_file"] for r in prices.collect()} == {
        "pricecatcher_2026-09.parquet", "pricecatcher_2026-10.parquet"}
    # an extra column in a lookup file is ignored, not loaded
    assert "new_column" not in read(spark, lake, "lookup_item").columns


def test_reloading_is_idempotent(spark, landing, tmp_path):
    lake = tmp_path / "lake"
    for _ in range(2):
        bronze.main(["--landing", str(landing), "--lake", str(lake)])
    assert month_counts(spark, lake) == {"2026-09": 2, "2026-10": 1}
    assert read(spark, lake, "lookup_item").count() == 1


def test_reloading_one_month_leaves_the_others(spark, landing, tmp_path):
    lake = tmp_path / "lake"
    bronze.main(["--landing", str(landing), "--lake", str(lake)])
    # October grows: the publisher appends new days to the current month's file
    write_prices(landing / "prices" / "pricecatcher_2026-10.parquet",
                 [("2026-10-10", 1, 10, 5.5), ("2026-10-11", 1, 10, 5.6), ("2026-10-12", 2, 10, 6.1)])
    bronze.main(["--months", "2026-10", "--landing", str(landing), "--lake", str(lake)])
    assert month_counts(spark, lake) == {"2026-09": 2, "2026-10": 3}


def test_missing_column_breaks_the_contract(spark, tmp_path):
    path = tmp_path / "pricecatcher_2026-09.parquet"
    duckdb.execute(f"COPY (SELECT DATE '2026-09-01' AS date, 1::BIGINT AS premise_code, 5.0 AS price) TO '{path}' (FORMAT parquet, COMPRESSION brotli)")
    with pytest.raises(bronze.SchemaContractError, match="item_code"):
        bronze.load_prices(spark, path, tmp_path / "lake")


def test_rows_from_another_month_are_rejected(spark, tmp_path):
    path = tmp_path / "pricecatcher_2026-09.parquet"
    write_prices(path, [("2026-09-30", 1, 10, 5.0), ("2026-10-01", 1, 10, 5.0)])
    with pytest.raises(ValueError, match="outside 2026-09"):
        bronze.load_prices(spark, path, tmp_path / "lake")


def test_decimal_price_is_cast_to_contract_type(spark, tmp_path):
    path = tmp_path / "pricecatcher_2026-09.parquet"
    write_prices(path, [("2026-09-01", 1, 10, 5.0)], price_type="DECIMAL(10,2)")
    bronze.load_prices(spark, path, tmp_path / "lake")
    assert dict(read(spark, tmp_path / "lake", "prices").dtypes)["price"] == "double"


def test_missing_landing_files_is_an_error(tmp_path):
    assert bronze.main(["--landing", str(tmp_path), "--lake", str(tmp_path / "lake")]) == 1
