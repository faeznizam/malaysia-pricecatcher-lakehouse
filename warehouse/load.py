"""Load the landing files into the warehouse's RAW schema (the Snowflake path).

This is the SQL-first version of bronze: the same landing files, loaded
as they are into RAW tables, ready for dbt to transform.

    RAW.PRICES          one load per month; a month is replaced as a whole
    RAW.LOOKUP_ITEM     full snapshot, replaced on every load
    RAW.LOOKUP_PREMISE  full snapshot, replaced on every load

Two targets, same tables:

    --target snowflake   upload each file to an internal stage (PUT), then
                         COPY INTO the RAW table, inside one transaction
    --target duckdb      a local DuckDB file, for development and CI

Before anything is uploaded, each file is checked locally with DuckDB:
the schema contract (columns we depend on, with types we can cast to)
and, for price files, that every row is dated inside the file's month.
A bad file fails here, before it costs any warehouse time.

data.gov.my compresses its Parquet with Brotli. Each file is re-encoded
(same rows, same columns) to Snappy first, which every engine reads.

Loads are idempotent: loading a month again deletes that month and
inserts it fresh in one transaction, so re-runs never duplicate rows
and a failed run leaves the previous data in place.

Usage:
    python warehouse/load.py --target duckdb                     # every month in landing
    python warehouse/load.py --target snowflake --months 2026-10 # one month

Snowflake connection settings come from environment variables:
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PRIVATE_KEY_PATH,
    SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE
"""

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

import duckdb

DEFAULT_LANDING = os.environ.get("LANDING_DIR", "data/landing")
DEFAULT_DUCKDB = os.environ.get("DUCKDB_PATH", "warehouse/pricecatcher.duckdb")
LOOKUPS = ["lookup_item", "lookup_premise"]

# Columns we rely on downstream, with the SQL type each must cast to.
# Same contract as the PySpark bronze layer (pricecatcher/bronze.py).
CONTRACTS = {
    "prices": {"date": "DATE", "premise_code": "BIGINT", "item_code": "BIGINT", "price": "DOUBLE"},
    "lookup_item": {
        "item_code": "BIGINT", "item": "VARCHAR", "unit": "VARCHAR",
        "item_group": "VARCHAR", "item_category": "VARCHAR",
    },
    "lookup_premise": {
        "premise_code": "BIGINT", "premise": "VARCHAR", "address": "VARCHAR",
        "premise_type": "VARCHAR", "state": "VARCHAR", "district": "VARCHAR",
    },
}
# Snowflake names for the same types.
SNOWFLAKE_TYPES = {"DATE": "DATE", "BIGINT": "NUMBER(38,0)", "DOUBLE": "FLOAT", "VARCHAR": "VARCHAR"}


class SchemaContractError(Exception):
    """A landing file is missing a column we depend on, or a value can't be cast."""


def sql_string(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def month_of(path: Path) -> str:
    match = re.search(r"(\d{4}-\d{2})", path.name)
    if not match:
        raise ValueError(f"Can't tell the month from {path.name}")
    return match.group(1)


def prepare(source: Path, table: str, workdir: Path) -> tuple[Path, int]:
    """Check a landing file against its contract and write a clean Snappy copy.

    The copy holds only the contract's columns, already cast, so the
    warehouse load is a plain column-by-name copy. Returns (copy, rows).
    """
    contract = CONTRACTS[table]
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    found = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_string(source)})").fetchall()]
    missing = sorted(set(contract) - set(found))
    if missing:
        raise SchemaContractError(f"{source.name} is missing column(s) {missing}; found {found}")

    # CAST (not TRY_CAST): a value that can't be cast fails the load instead of becoming null.
    columns = ", ".join(f"CAST({name} AS {dtype}) AS {name}" for name, dtype in contract.items())
    select = f"SELECT {columns} FROM read_parquet({sql_string(source)})"
    try:
        rows = con.execute(f"SELECT count(*) FROM ({select})").fetchone()[0]
    except duckdb.ConversionException as e:
        raise SchemaContractError(f"{source.name}: {e}") from e

    if table == "prices":
        month = month_of(source)
        outside = con.execute(
            f"SELECT count(*) FROM ({select}) WHERE strftime(date, '%Y-%m') <> {sql_string(month)}"
        ).fetchone()[0]
        if outside:
            raise ValueError(f"{source.name} has {outside:,} rows dated outside {month}")

    staged = workdir / source.name
    con.execute(f"COPY ({select}) TO {sql_string(staged)} (FORMAT parquet, COMPRESSION snappy)")
    con.close()
    return staged, rows


# --- DuckDB target -------------------------------------------------------------

class DuckDBTarget:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(path)
        self.con.execute("SET enable_progress_bar = false")

    def setup(self):
        self.con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        for table, contract in CONTRACTS.items():
            cols = ", ".join(f"{name} {dtype}" for name, dtype in contract.items())
            extra = ", year_month VARCHAR" if table == "prices" else ""
            self.con.execute(
                f"CREATE TABLE IF NOT EXISTS raw.{table} ({cols}{extra}, "
                f"_source_file VARCHAR, _ingested_at TIMESTAMP WITH TIME ZONE)"
            )

    def load(self, staged: Path, table: str, month: str | None) -> None:
        cols = ", ".join(CONTRACTS[table])
        self.con.execute("BEGIN TRANSACTION")
        try:
            if month:
                self.con.execute(f"DELETE FROM raw.{table} WHERE year_month = ?", [month])
                month_col, month_val = ", year_month", f", {sql_string(month)}"
            else:
                self.con.execute(f"DELETE FROM raw.{table}")
                month_col = month_val = ""
            self.con.execute(
                f"INSERT INTO raw.{table} ({cols}{month_col}, _source_file, _ingested_at) "
                f"SELECT {cols}{month_val}, {sql_string(staged.name)}, now() "
                f"FROM read_parquet({sql_string(staged)})"
            )
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise

    def summary(self) -> list[tuple]:
        return self.con.execute(
            "SELECT year_month, count(*) FROM raw.prices GROUP BY 1 ORDER BY 1"
        ).fetchall()

    def close(self):
        self.con.close()


# --- Snowflake target ----------------------------------------------------------

class SnowflakeTarget:
    STAGE = "RAW.LANDING"

    def __init__(self):
        import snowflake.connector  # only needed for this target

        settings = {
            "account": os.environ["SNOWFLAKE_ACCOUNT"],
            "user": os.environ["SNOWFLAKE_USER"],
            "role": os.environ.get("SNOWFLAKE_ROLE", "PRICECATCHER_LOADER"),
            "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "PRICECATCHER_WH"),
            "database": os.environ.get("SNOWFLAKE_DATABASE", "PRICECATCHER"),
        }
        if os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH"):
            settings["private_key_file"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
        else:
            settings["password"] = os.environ["SNOWFLAKE_PASSWORD"]
        self.con = snowflake.connector.connect(**settings)
        self.cur = self.con.cursor()

    def setup(self):
        """Tables and stage are created by warehouse/setup.sql; check they exist."""
        self.cur.execute(f"DESCRIBE STAGE {self.STAGE}")

    def load(self, staged: Path, table: str, month: str | None) -> None:
        folder = "prices" if table == "prices" else "lookups"
        # Parquet is already compressed, so don't gzip it again.
        self.cur.execute(
            f"PUT 'file://{staged.resolve().as_posix()}' @{self.STAGE}/{folder}/ "
            f"AUTO_COMPRESS = FALSE OVERWRITE = TRUE"
        )
        contract = CONTRACTS[table]
        cols = list(contract)
        casts = [f"$1:{name}::{SNOWFLAKE_TYPES[dtype]}" for name, dtype in contract.items()]
        if month:
            cols.append("year_month")
            casts.append(sql_string(month))
        cols += ["_source_file", "_ingested_at"]
        casts += ["METADATA$FILENAME", "CURRENT_TIMESTAMP()"]

        self.cur.execute("BEGIN")
        try:
            if month:
                self.cur.execute(f"DELETE FROM RAW.{table.upper()} WHERE year_month = %s", (month,))
            else:
                self.cur.execute(f"DELETE FROM RAW.{table.upper()}")
            # FORCE = TRUE: we deleted the old rows ourselves, so load the file even
            # if Snowflake's load history says it was loaded before.
            self.cur.execute(
                f"COPY INTO RAW.{table.upper()} ({', '.join(cols)}) "
                f"FROM (SELECT {', '.join(casts)} FROM @{self.STAGE}/{folder}/{staged.name}) "
                f"FILE_FORMAT = (TYPE = PARQUET) FORCE = TRUE ON_ERROR = ABORT_STATEMENT"
            )
            self.cur.execute("COMMIT")
        except Exception:
            self.cur.execute("ROLLBACK")
            raise

    def summary(self) -> list[tuple]:
        self.cur.execute("SELECT year_month, count(*) FROM RAW.PRICES GROUP BY 1 ORDER BY 1")
        return self.cur.fetchall()

    def close(self):
        self.cur.close()
        self.con.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=["duckdb", "snowflake"], default="duckdb")
    parser.add_argument("--months", nargs="+", help="Months to load, e.g. 2026-10 (default: all in landing)")
    parser.add_argument("--landing", default=DEFAULT_LANDING, help="Landing folder (default: $LANDING_DIR or data/landing)")
    parser.add_argument("--duckdb-path", default=DEFAULT_DUCKDB, help="DuckDB file for --target duckdb")
    args = parser.parse_args(argv)

    landing = Path(args.landing)
    if args.months:
        price_files = [landing / "prices" / f"pricecatcher_{m}.parquet" for m in args.months]
    else:
        price_files = sorted((landing / "prices").glob("pricecatcher_*.parquet"))
    lookup_files = [landing / "lookups" / f"{name}.parquet" for name in LOOKUPS]

    missing = [p for p in price_files + lookup_files if not p.exists()]
    if missing or not price_files:
        print("Missing landing files (run `make download` first):", file=sys.stderr)
        for p in missing or [landing / "prices"]:
            print(f"  {p}", file=sys.stderr)
        return 1

    target = SnowflakeTarget() if args.target == "snowflake" else DuckDBTarget(args.duckdb_path)
    try:
        target.setup()
        with tempfile.TemporaryDirectory() as tmp:
            for source in price_files:
                staged, rows = prepare(source, "prices", Path(tmp))
                target.load(staged, "prices", month_of(source))
                print(f"prices  {source.name:<32} {rows:>10,} rows")
            for source in lookup_files:
                staged, rows = prepare(source, source.stem, Path(tmp))
                target.load(staged, source.stem, None)
                print(f"lookup  {source.name:<32} {rows:>10,} rows")
        print(f"\nRAW.PRICES in {args.target} now holds:")
        for month, rows in target.summary():
            print(f"  {month}  {rows:>10,} rows")
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
