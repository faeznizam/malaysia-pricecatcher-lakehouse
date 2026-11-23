"""Write a small, made-up landing folder for CI and local runs of the warehouse path.

Same file names, columns and Brotli compression as data.gov.my, plus one
example of each problem the data quality rules catch, so every rule has
something to find:

    <landing>/prices/pricecatcher_2026-09.parquet
    <landing>/prices/pricecatcher_2026-10.parquet
    <landing>/lookups/lookup_item.parquet
    <landing>/lookups/lookup_premise.parquet

Usage:
    python warehouse/sample_data.py --landing data/sample_landing
"""

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import duckdb

STATES = ["Selangor", "Johor", "Sabah"]
PREMISE_TYPES = ["Hypermarket", "Pasar Basah", "Kedai Runcit"]
ITEMS = [  # code, name, unit, group, category, base price
    (1, "AYAM BERSIH - STANDARD", "1kg", "BARANGAN SEGAR", "AYAM", 9.50),
    (2, "TELUR AYAM GRED A", "10 biji", "BARANGAN SEGAR", "TELUR", 4.20),
    (3, "BAWANG MERAH", "1kg", "BARANGAN KERING", "BAWANG", 6.80),
    (4, "BERAS SUPER 5%", "10kg", "BARANGAN BERBUNGKUS", "BERAS", 32.00),
    (5, "MINYAK MASAK", "5kg", "BARANGAN BERBUNGKUS", "MINYAK", 28.50),
    (6, "SAWI HIJAU", "1kg", "BARANGAN SEGAR", "SAYUR", 5.00),
]
PREMISES_PER_STATE = 10
MONTHS = ["2026-09", "2026-10"]


def premises():
    rows, code = [], 100
    for state in STATES:
        for n in range(PREMISES_PER_STATE):
            # A trailing space on some premise types, like the real lookup has.
            ptype = PREMISE_TYPES[n % 3] + (" " if n == 4 else "")
            rows.append((code, f"Kedai {code}", f"{n + 1} Jalan Contoh", ptype, state, f"{state} Daerah {n % 2}"))
            code += 1
    return rows


def month_days(month: str):
    first = date.fromisoformat(month + "-01")
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def price_rows(month: str, premise_rows, rng: random.Random):
    rows = []
    first = date.fromisoformat(month + "-01")
    # Keys the problem rows below use; leave them out of the normal rows so
    # each problem row trips only its own rule.
    taken = {(premise_rows[i][0], i + 1) for i in range(1, 5)}
    shift = 1.0 if month == MONTHS[0] else 1.03
    state_level = {"Selangor": 1.00, "Johor": 0.97, "Sabah": 1.08}
    for day in month_days(month):
        for code, _, _, _, state, _ in premise_rows:
            for item_code, *_, base in ITEMS:
                if day == first and (code, item_code) in taken:
                    continue
                price = base * shift * state_level[state] * rng.uniform(0.95, 1.05)
                rows.append((day, code, item_code, round(price, 2)))
    some_premise = premise_rows[0][0]
    rows += [
        (first, some_premise, 1, rows[0][3]),            # duplicate_key: same date, premise, item
        (first, premise_rows[1][0], 2, 45.0),             # price_too_high: missing decimal point
        (first, premise_rows[2][0], 3, 0.06),             # price_too_low
        (first, premise_rows[3][0], 4, 0.0),              # price_not_positive
        (first, premise_rows[4][0], 5, None),             # null_field
        (first, premise_rows[5][0], 999, 3.0),            # unknown_item (kept, flagged)
        (first, 9999, 6, 5.0),                            # unknown_premise (kept, flagged)
    ]
    return rows


def write(con, rows, columns, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute("DROP TABLE IF EXISTS t")
    con.execute(f"CREATE TABLE t ({', '.join(f'{name} {dtype}' for name, dtype in columns)})")
    con.executemany(f"INSERT INTO t VALUES ({', '.join('?' for _ in columns)})", rows)
    # Brotli, like the publisher's files.
    con.execute(f"COPY t TO '{path.as_posix()}' (FORMAT parquet, COMPRESSION brotli)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--landing", default="data/sample_landing")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    landing, rng = Path(args.landing), random.Random(args.seed)
    con = duckdb.connect()
    prem = premises()
    # Like the real lookups, both include a -1 "unknown" member.
    write(con, [(-1, "Unknown", None, None, None)] + [i[:5] for i in ITEMS],
          [("item_code", "BIGINT"), ("item", "VARCHAR"), ("unit", "VARCHAR"),
           ("item_group", "VARCHAR"), ("item_category", "VARCHAR")],
          landing / "lookups" / "lookup_item.parquet")
    write(con, [(-1, "Unknown", None, None, None, None)] + prem,
          [("premise_code", "BIGINT"), ("premise", "VARCHAR"), ("address", "VARCHAR"),
           ("premise_type", "VARCHAR"), ("state", "VARCHAR"), ("district", "VARCHAR")],
          landing / "lookups" / "lookup_premise.parquet")
    for month in MONTHS:
        rows = price_rows(month, prem, rng)
        write(con, rows, [("date", "DATE"), ("premise_code", "BIGINT"), ("item_code", "BIGINT"), ("price", "DOUBLE")],
              landing / "prices" / f"pricecatcher_{month}.parquet")
        print(f"wrote {month}: {len(rows):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
