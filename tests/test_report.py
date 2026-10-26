import csv
from datetime import datetime

import pytest

from pricecatcher import report
from tests.test_gold import lake as gold_lake  # noqa: F401  (reuses the gold fixture)

LOG_SCHEMA = ("run_id string, run_at timestamp, year_month string, check_name string, "
              "severity string, rows long, rows_checked long")


@pytest.fixture(scope="module")
def site(spark, gold_lake, tmp_path_factory):
    # Run 1 checked both months; run 2 re-checked only October, as a daily run would.
    log = [
        ("run1", datetime(2026, 10, 20, 6), "2026-09", "price_too_low", "error", 7, 5),
        ("run1", datetime(2026, 10, 20, 6), "2026-09", "rows_quarantined", "info", 7, 5),
        ("run1", datetime(2026, 10, 20, 6), "2026-10", "price_too_low", "error", 1, 5),
        ("run1", datetime(2026, 10, 20, 6), "2026-10", "rows_quarantined", "info", 1, 5),
        ("run2", datetime(2026, 10, 21, 6), "2026-10", "price_too_low", "error", 3, 5),
        ("run2", datetime(2026, 10, 21, 6), "2026-10", "rows_quarantined", "info", 3, 5),
    ]
    spark.createDataFrame(log, LOG_SCHEMA).write.format("delta").mode("overwrite").save(
        str(gold_lake / "meta" / "dq_run_log"))
    site = tmp_path_factory.mktemp("site")
    assert report.main(["--lake", str(gold_lake), "--site", str(site)]) == 0
    return site


def page(site):
    return (site / "index.html").read_text(encoding="utf-8")


def test_page_shows_latest_month_and_states(site):
    html = page(site)
    assert "Data up to <strong>03 Oct 2026</strong>" in html
    assert "Johor" in html and "Selangor" in html
    assert "Biggest price changes" in html


def test_dq_table_uses_each_months_latest_run(site):
    html = page(site)
    row = html[html.index(">price_too_low</td>"):].split("</tr>")[0]
    assert '<td class="n">7</td><td class="n">3</td>' in row  # September from run1, October from run2
    assert "60.000%" in html  # October tile: 3 of 5 rows quarantined


def test_csv_exports_have_headers(site):
    for name in ["mart_state_index", "mart_item_mom", "mart_item_month", "dq_run_log"]:
        with open(site / "data" / f"{name}.csv", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) > 1, name
    with open(site / "data" / "mart_state_index.csv", encoding="utf-8") as f:
        assert next(csv.reader(f))[:2] == ["year_month", "state"]


def test_bars_grow_from_the_baseline_and_escape_labels():
    svg = report.diverging_bars([("A & B", 105.0), ("C", 95.0)], 100, str, lambda s, v: s)
    assert "A &amp; B" in svg and "A & B" not in svg
    assert 'class="bar up"' in svg and 'class="bar down"' in svg
    assert report.diverging_bars([], 100, str, lambda s, v: s).startswith('<div class="chart-wrap">')


def test_fmt():
    assert report.fmt(None) == "–"
    assert report.fmt(1234.56) == "1,234.6"
    assert report.fmt(2.5, 1, True) == "+2.5"
