import os

from pricecatcher import benchmark
from tests.test_gold import lake as gold_lake  # noqa: F401  (reuses the gold fixture)


def test_every_layout_is_written_and_timed(spark, gold_lake):
    results = benchmark.run_benchmark(spark, gold_lake, repeats=1)
    assert [r["layout"] for r in results] == benchmark.LAYOUTS
    by_layout = {r["layout"]: r for r in results}
    # by_day has one folder per date, so at least one file per date.
    assert by_layout["by_day"]["files"] >= 3
    for r in results:
        assert r["one_month"] >= 0 and r["one_item"] >= 0 and r["full_scan"] >= 0
    # Every layout holds the same rows.
    counts = {spark.read.format("delta").load(str(gold_lake / "benchmark" / layout)).count()
              for layout in benchmark.LAYOUTS}
    assert len(counts) == 1


def test_markdown_table_has_a_row_per_layout():
    row = {"layout": "x", "files": 1200, "size_mb": 1.25, "write_s": 2.0,
           "one_month": 0.5, "one_item": 0.25, "full_scan": 3.0}
    table = benchmark.to_markdown([row])
    assert table.splitlines()[-1] == "| x | 1,200 | 1.2 | 2.0 | 0.50 | 0.25 | 3.00 |"


def test_relative_lake_path_works(spark, tmp_path):
    # `make benchmark` passes the default lake as the relative path "lake".
    path = benchmark.Path(os.path.relpath(tmp_path / "lake" / "benchmark" / "by_month_zorder"))
    df = spark.createDataFrame([(1, "2026-10")], "item_code bigint, year_month string")
    benchmark.write_layout(spark, df, path, "by_month_zorder")
    files, _ = benchmark.table_files(spark, path)
    assert files == 1
