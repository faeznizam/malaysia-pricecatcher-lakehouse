import duckdb
import pytest

from pricecatcher import profile


@pytest.fixture
def landing(tmp_path):
    """A tiny fake landing zone with known problems planted in it."""
    (tmp_path / "prices").mkdir()
    (tmp_path / "lookups").mkdir()
    con = duckdb.connect()
    con.execute(f"""
        COPY (SELECT * FROM (VALUES
            (DATE '2026-09-01', 1, 10, 5.00),
            (DATE '2026-09-01', 1, 10, 5.00),   -- exact duplicate
            (DATE '2026-09-01', 2, 10, 6.00),
            (DATE '2026-09-01', 2, 10, 6.50),   -- same key, different price
            (DATE '2026-09-02', 3, 10, 500.00), -- 100x the median
            (DATE '2026-09-02', 1, 99, 0.00)    -- unknown item, zero price
        ) t(date, premise_code, item_code, price))
        TO '{tmp_path}/prices/pricecatcher_2026-09.parquet' (FORMAT parquet)
    """)
    con.execute(f"""
        COPY (SELECT * FROM (VALUES (10, 'Beras', 'kg', 'BARANG KERING', 'BERAS'))
              t(item_code, item, unit, item_group, item_category))
        TO '{tmp_path}/lookups/lookup_item.parquet' (FORMAT parquet)
    """)
    con.execute(f"""
        COPY (SELECT * FROM (VALUES
            (1, 'Kedai A', 'Jalan 1', 'Kedai Runcit', 'Selangor', 'Petaling'),
            (2, 'Kedai B', 'Jalan 2', 'Pasar Raya', 'Johor', 'Johor Bahru')
        ) t(premise_code, premise, address, premise_type, state, district))
        TO '{tmp_path}/lookups/lookup_premise.parquet' (FORMAT parquet)
    """)
    return tmp_path


def run(landing, capsys):
    assert profile.main(["--landing", str(landing)]) == 0
    return capsys.readouterr().out


def test_counts_rows_and_dates(landing, capsys):
    out = run(landing, capsys)
    assert "pricecatcher_2026-09.parquet  6" in out
    assert "2026-09-01" in out and "2026-09-02" in out


def test_finds_duplicates_and_conflicts(landing, capsys):
    out = run(landing, capsys)
    section = out.split("=== Duplicates ===")[1].split("===")[0]
    # 2 duplicated keys, 2 extra rows, 1 key with conflicting prices
    assert section.split("\n")[2].split() == ["2", "2", "1"]


def test_flags_zero_price_outlier_and_orphans(landing, capsys):
    out = run(landing, capsys)
    price_range = out.split("=== Price range (RM) ===")[1].split("===")[0]
    assert price_range.split("\n")[2].split()[-1] == "1"  # one zero price
    assert "Items flagged in total: 1" in out
    orphans = out.split("no match in the lookups ===")[1].split("===")[0]
    assert "unknown_items" in orphans and "unknown_premises" in orphans
    lines = orphans.strip().split("\n")
    assert lines[1].split() == ["1", "1"]  # item 99
    assert lines[3].split() == ["1", "1"]  # premise 3


def test_no_files_is_an_error(tmp_path, capsys):
    assert profile.main(["--landing", str(tmp_path)]) == 1
