"""Download raw PriceCatcher files from data.gov.my into the landing zone.

Files are saved unchanged (this is the "landing" step, before bronze):
    <landing>/prices/pricecatcher_YYYY-MM.parquet
    <landing>/lookups/lookup_item.parquet
    <landing>/lookups/lookup_premise.parquet

Files that are already downloaded are skipped, except the ones the
publisher keeps changing: the current month (new days are added daily)
and the two lookups (new items and premises are added). Those are
always fetched again.

Usage:
    python -m pricecatcher.download --months 2026-09 2026-10
    python -m pricecatcher.download --months 2026-09 --force
    python -m pricecatcher.download --recent 2           # last month and this month
"""

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_URL = "https://storage.data.gov.my/pricecatcher"
LOOKUP_FILES = ["lookup_item.parquet", "lookup_premise.parquet"]
DEFAULT_LANDING = os.environ.get("LANDING_DIR", "data/landing")

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PARQUET_MAGIC = b"PAR1"


def price_filename(month: str) -> str:
    """Return the file name for one month of prices, e.g. '2026-09'."""
    if not MONTH_PATTERN.match(month):
        raise ValueError(f"Month must look like YYYY-MM, got {month!r}")
    return f"pricecatcher_{month}.parquet"


def plan_downloads(months, landing: Path, base_url: str = BASE_URL, include_lookups: bool = True):
    """List (url, destination) pairs for the requested months and lookups."""
    plan = []
    for month in months:
        name = price_filename(month)
        plan.append((f"{base_url}/{name}", landing / "prices" / name))
    if include_lookups:
        for name in LOOKUP_FILES:
            plan.append((f"{base_url}/{name}", landing / "lookups" / name))
    return plan


def current_month() -> str:
    """This month in Malaysia time, e.g. '2026-10'."""
    return datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).strftime("%Y-%m")


def recent_months(n: int, latest: str | None = None) -> list[str]:
    """The last n months up to and including latest (default: this month), oldest first."""
    year, month = map(int, (latest or current_month()).split("-"))
    months = []
    for _ in range(n):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return months[::-1]


def changes_upstream(dest: Path) -> bool:
    """True for files the publisher keeps updating after first release."""
    return dest.name in LOOKUP_FILES or dest.name == price_filename(current_month())


def is_parquet(path: Path) -> bool:
    """A Parquet file starts and ends with the 4 bytes 'PAR1'."""
    if path.stat().st_size < 8:
        return False
    with open(path, "rb") as f:
        head = f.read(4)
        f.seek(-4, os.SEEK_END)
        tail = f.read(4)
    return head == PARQUET_MAGIC and tail == PARQUET_MAGIC


def download(url: str, dest: Path, force: bool = False) -> str:
    """Download one file. Returns 'skipped' or 'downloaded'.

    Writes to a .part file first and renames at the end, so a failed
    download never leaves a half-written file that looks complete.
    """
    if dest.exists() and not force:
        return "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        if not is_parquet(tmp):
            raise ValueError(f"{url} did not return a valid Parquet file")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return "downloaded"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--months", nargs="+", help="Months to download, e.g. 2026-09 2026-10")
    which.add_argument("--recent", type=int, metavar="N", help="The last N months, including this one")
    parser.add_argument("--landing", default=DEFAULT_LANDING, help="Landing folder (default: $LANDING_DIR or data/landing)")
    parser.add_argument("--no-lookups", action="store_true", help="Skip the item and premise lookup files")
    parser.add_argument("--force", action="store_true", help="Download again even if the file exists")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        months = args.months or recent_months(args.recent)
        plan = plan_downloads(months, Path(args.landing), args.base_url, not args.no_lookups)
    except ValueError as e:
        parser.error(str(e))

    failures = 0
    for url, dest in plan:
        try:
            status = download(url, dest, args.force or changes_upstream(dest))
            size_mb = dest.stat().st_size / 1_000_000
            print(f"{status:<10} {dest}  ({size_mb:.1f} MB)")
        except (urllib.error.URLError, ValueError, OSError) as e:
            failures += 1
            print(f"FAILED     {url}\n           {e}", file=sys.stderr)

    print(f"\n{len(plan) - failures} of {len(plan)} files ready in {args.landing}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
