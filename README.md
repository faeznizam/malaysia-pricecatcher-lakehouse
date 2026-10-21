# Malaysia PriceCatcher Lakehouse

A medallion lakehouse (bronze / silver / gold) built on Malaysia's open
[PriceCatcher](https://data.gov.my/data-catalogue/pricecatcher) retail price data,
using PySpark and Delta Lake.

> **Status:** being built step by step. This README describes what exists *now*.

## Data source

Daily item prices collected by KPDN at premises across Malaysia, published monthly
by data.gov.my under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

| File | Contents |
|---|---|
| `pricecatcher_YYYY-MM.parquet` | date, premise_code, item_code, price (RM) |
| `lookup_item.parquet` | item_code, item, unit, item_group, item_category |
| `lookup_premise.parquet` | premise_code, premise, address, premise_type, state, district |

## Quick start (Linux / WSL2)

```bash
make venv                          # create .venv and install dependencies
make test                          # run unit tests
make download                      # Sept + Oct 2026 prices and both lookups
make download MONTHS="2026-08"     # any other months
make profile                       # describe the downloaded files
```

Files land in `data/landing/` (override with `LANDING_DIR`). Data is never committed.

## Project layout

```
pricecatcher/download.py   landing step: fetch raw files from data.gov.my
pricecatcher/profile.py    read-only profile of the landing files (DuckDB)
tests/                     unit tests (no network needed)
```

## Roadmap

1. Repo skeleton + data download
2. Profile the real files (rows, types, nulls, duplicates, price ranges)  ← *here*
3. Bronze: raw files into Delta tables
4. Silver: schema contracts, data quality rules, quarantine
5. Gold: star schema and analysis marts
6. Findings report, storage benchmark, CI
