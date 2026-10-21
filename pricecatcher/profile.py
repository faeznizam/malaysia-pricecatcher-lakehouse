"""Profile the raw PriceCatcher files in the landing zone.

Answers "what does the data actually look like?" before we design the
pipeline: row counts, column types, nulls, duplicates, price ranges and
codes that don't match the lookups. Read-only: nothing is changed.

Usage:
    python -m pricecatcher.profile
    python -m pricecatcher.profile --landing data/landing
"""

import argparse
import os
import sys
from pathlib import Path

import duckdb

DEFAULT_LANDING = os.environ.get("LANDING_DIR", "data/landing")
PRICE_COLUMNS = {"date", "premise_code", "item_code", "price"}
OUTLIER_RATIO = 10  # flag items whose max price is 10x their median


def heading(title: str) -> None:
    print(f"\n=== {title} ===")


def show(con, sql: str, params=None) -> None:
    """Run a query and print it as a small aligned table."""
    rel = con.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    rows = [[("" if v is None else str(v)) for v in r] for r in rel.fetchall()]
    widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    print("  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("  " + "  ".join(v.ljust(w) for v, w in zip(r, widths)))
    if not rows:
        print("  (none)")


def scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def profile_columns(con, view: str) -> list[str]:
    """Print each column's type and null count; return the column names."""
    types = {r[0]: r[1] for r in con.execute(f"DESCRIBE {view}").fetchall()}
    columns = list(types)
    null_counts = ", ".join(f"count(*) - count({duckdb_quote(c)})" for c in columns)
    nulls = dict(zip(columns, con.execute(f"SELECT {null_counts} FROM {view}").fetchone()))
    print("  column               type         nulls")
    for c in columns:
        print(f"  {c:<20} {types[c]:<12} {nulls[c]:,}")
    return columns


def duckdb_quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sql_string(value) -> str:
    """Quote a value (e.g. a file path) as a SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def profile_prices(con, price_files: list[Path]) -> None:
    files = ", ".join(sql_string(p) for p in price_files)
    con.execute(f"CREATE VIEW prices AS SELECT * FROM read_parquet([{files}], filename = true)")

    heading("Price files")
    show(con, """
        SELECT regexp_extract(filename, '[^/]+$') AS file,
               count(*) AS rows,
               min(date) AS first_date,
               max(date) AS last_date,
               count(DISTINCT date) AS days
        FROM prices GROUP BY ALL ORDER BY file
    """)
    profile_missing_dates(con, scalar(con, "SELECT max(date) FROM prices"))

    heading("Price columns (all months)")
    columns = set(profile_columns(con, "(SELECT * EXCLUDE (filename) FROM prices)"))
    missing = PRICE_COLUMNS - columns
    if missing:
        print(f"\n  Expected columns missing: {sorted(missing)}. Skipping the remaining price checks.")
        return

    heading("Size")
    show(con, """
        SELECT count(*) AS rows,
               count(DISTINCT premise_code) AS premises,
               count(DISTINCT item_code) AS items
        FROM prices
    """)

    heading("Duplicates")
    show(con, """
        WITH k AS (
            SELECT date, premise_code, item_code,
                   count(*) AS n, count(DISTINCT price) AS prices
            FROM prices GROUP BY ALL HAVING count(*) > 1
        )
        SELECT count(*) AS duplicated_keys,
               coalesce(sum(n - 1), 0) AS extra_rows,
               count(*) FILTER (WHERE prices > 1) AS keys_with_conflicting_prices
        FROM k
    """)
    print("  (key = date + premise_code + item_code)")

    heading("Price range (RM)")
    show(con, """
        SELECT min(price) AS min,
               round(quantile_cont(price, 0.5), 2) AS median,
               round(quantile_cont(price, 0.99), 2) AS p99,
               max(price) AS max,
               count(*) FILTER (WHERE price <= 0) AS zero_or_negative
        FROM prices
    """)

    con.execute("""
        CREATE TEMP TABLE item_stats AS
        SELECT item_code, median(price) AS med FROM prices GROUP BY item_code
    """)
    for side, label, condition in [
        ("high", f">= {OUTLIER_RATIO}x", f"price >= {OUTLIER_RATIO} * med"),
        ("low", f"<= 1/{OUTLIER_RATIO} of", f"price <= med / {OUTLIER_RATIO}"),
    ]:
        heading(f"Prices {label} their item's median (top 15 items)")
        show(con, f"""
            SELECT item_code,
                   count(*) AS rows,
                   round(any_value(med), 2) AS median,
                   min(price) AS min,
                   max(price) AS max,
                   count(*) FILTER (WHERE {condition}) AS rows_{side}
            FROM prices JOIN item_stats USING (item_code)
            WHERE med > 0
            GROUP BY item_code
            HAVING rows_{side} > 0
            ORDER BY rows_{side} DESC LIMIT 15
        """)
        items, rows = con.execute(f"""
            SELECT count(DISTINCT item_code), count(*)
            FROM prices JOIN item_stats USING (item_code)
            WHERE med > 0 AND {condition}
        """).fetchone()
        print(f"  In total: {rows:,} rows across {items:,} items")

    heading("High prices that look like a missing decimal point (80x-120x median)")
    show(con, """
        SELECT count(*) AS rows,
               count(DISTINCT item_code) AS items,
               count(DISTINCT premise_code) AS premises
        FROM prices JOIN item_stats USING (item_code)
        WHERE med > 0 AND price BETWEEN 80 * med AND 120 * med
    """)


def profile_missing_dates(con, latest_date) -> None:
    """Days in each file's month with no rows at all (up to the latest date seen)."""
    heading("Days with no data")
    show(con, f"""
        WITH files AS (
            SELECT DISTINCT regexp_extract(filename, '[^/]+$') AS file,
                   strptime(regexp_extract(filename, '(\\d{{4}}-\\d{{2}})', 1), '%Y-%m')::DATE AS month_start
            FROM prices
        ),
        expected AS (
            SELECT file, unnest(generate_series(
                month_start,
                least(last_day(month_start), DATE '{latest_date}'),
                INTERVAL 1 DAY))::DATE AS day
            FROM files
        ),
        actual AS (
            SELECT DISTINCT regexp_extract(filename, '[^/]+$') AS file, date AS day FROM prices
        )
        SELECT file,
               count(*) AS missing_days,
               string_agg(strftime(day, '%d'), ' ' ORDER BY day) AS days_missing
        FROM expected ANTI JOIN actual USING (file, day)
        GROUP BY file ORDER BY file
    """)
    print("  (no rows listed = every day present)")


def profile_lookup(con, name: str, path: Path, key: str) -> bool:
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet({sql_string(path)})")
    heading(f"{path.name}")
    print(f"  rows: {scalar(con, f'SELECT count(*) FROM {name}'):,}")
    columns = profile_columns(con, name)
    if key not in columns:
        print(f"  Key column {key!r} not found.")
        return False
    dupes = scalar(con, f"SELECT count(*) FROM (SELECT {key} FROM {name} GROUP BY {key} HAVING count(*) > 1)")
    print(f"  duplicate {key}s: {dupes:,}")
    any_null = " OR ".join(f"{duckdb_quote(c)} IS NULL" for c in columns)
    if scalar(con, f"SELECT count(*) FROM {name} WHERE {any_null}"):
        print("  rows with a missing value:")
        show(con, f"SELECT * FROM {name} WHERE {any_null} LIMIT 10")
    return True


def profile_orphans(con, has_items: bool, has_premises: bool) -> None:
    heading("Codes in prices with no match in the lookups")
    if has_items:
        show(con, """
            SELECT count(DISTINCT p.item_code) AS unknown_items, count(*) AS rows_affected
            FROM prices p ANTI JOIN items i ON p.item_code = i.item_code
        """)
        show(con, """
            SELECT p.item_code AS unknown_item_code, count(*) AS rows,
                   min(date) AS first_seen, max(date) AS last_seen,
                   round(median(price), 2) AS median_price
            FROM prices p ANTI JOIN items i ON p.item_code = i.item_code
            GROUP BY ALL ORDER BY rows DESC LIMIT 15
        """)
    if has_premises:
        show(con, """
            SELECT count(DISTINCT p.premise_code) AS unknown_premises, count(*) AS rows_affected
            FROM prices p ANTI JOIN premises s ON p.premise_code = s.premise_code
        """)


def profile_breakdowns(con) -> None:
    heading("Rows by state (top 20)")
    show(con, """
        SELECT coalesce(s.state, '(unknown)') AS state, count(*) AS rows,
               count(DISTINCT p.premise_code) AS premises
        FROM prices p LEFT JOIN premises s USING (premise_code)
        GROUP BY ALL ORDER BY rows DESC LIMIT 20
    """)
    heading("Rows by item group")
    show(con, """
        SELECT coalesce(i.item_group, '(unknown)') AS item_group, count(*) AS rows,
               count(DISTINCT p.item_code) AS items
        FROM prices p LEFT JOIN items i USING (item_code)
        GROUP BY ALL ORDER BY rows DESC
    """)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--landing", default=DEFAULT_LANDING, help="Landing folder (default: $LANDING_DIR or data/landing)")
    args = parser.parse_args(argv)

    landing = Path(args.landing)
    price_files = sorted((landing / "prices").glob("pricecatcher_*.parquet"))
    if not price_files:
        print(f"No price files in {landing / 'prices'}. Run `make download` first.", file=sys.stderr)
        return 1

    con = duckdb.connect()
    profile_prices(con, price_files)

    item_path = landing / "lookups" / "lookup_item.parquet"
    premise_path = landing / "lookups" / "lookup_premise.parquet"
    has_items = item_path.exists() and profile_lookup(con, "items", item_path, "item_code")
    has_premises = premise_path.exists() and profile_lookup(con, "premises", premise_path, "premise_code")

    if PRICE_COLUMNS <= {r[0] for r in con.execute("DESCRIBE prices").fetchall()}:
        profile_orphans(con, has_items, has_premises)
        lookup_columns = (
            {r[0] for r in con.execute("DESCRIBE items").fetchall()} if has_items else set()
        ) | ({r[0] for r in con.execute("DESCRIBE premises").fetchall()} if has_premises else set())
        if {"state", "item_group"} <= lookup_columns:
            profile_breakdowns(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
