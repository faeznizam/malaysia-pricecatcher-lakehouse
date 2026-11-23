PYTHON ?= .venv/bin/python
# Download every month from SINCE to now, or set MONTHS for specific ones.
SINCE ?= 2026-05
# Extra options for the checks, e.g. CHECK_ARGS="--max-age-days 30" on an old local copy.
CHECK_ARGS ?=

.PHONY: venv test download profile bronze silver gold check report pipeline benchmark

venv:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest -v

download:
	$(PYTHON) -m pricecatcher.download $(if $(MONTHS),--months $(MONTHS),--since $(SINCE))

profile:
	$(PYTHON) -m pricecatcher.profile

bronze:
	$(PYTHON) -m pricecatcher.bronze

silver:
	$(PYTHON) -m pricecatcher.silver

gold:
	$(PYTHON) -m pricecatcher.gold

check:
	$(PYTHON) -m pricecatcher.checks $(CHECK_ARGS)

report:
	$(PYTHON) -m pricecatcher.report

# Everything after download, in order (what the daily schedule runs).
# If a check fails, make stops before the report, so nothing bad is published.
pipeline: bronze silver gold check report

benchmark:
	$(PYTHON) -m pricecatcher.benchmark

# --- Snowflake + dbt path (warehouse/) -------------------------------------------
# Same landing files, transformed in SQL by dbt. WH_TARGET=duckdb runs it locally;
# WH_TARGET=snowflake runs it in Snowflake (see warehouse/README.md for setup).
WH_TARGET ?= duckdb
WH_LANDING ?= data/landing
WH_VENV ?= .venv-warehouse
WH_DUCKDB ?= $(abspath warehouse/pricecatcher.duckdb)
WH_DBT_ENV = cd warehouse/dbt && DBT_PROFILES_DIR=. DUCKDB_PATH=$(WH_DUCKDB) \
	DBT_TARGET=$(if $(filter snowflake,$(WH_TARGET)),snowflake,dev) $(abspath $(WH_VENV))/bin/dbt

.PHONY: wh-venv wh-sample wh-load wh-dbt wh-freshness warehouse

wh-venv:
	python3 -m venv $(WH_VENV)
	$(WH_VENV)/bin/pip install --upgrade pip
	$(WH_VENV)/bin/pip install -r warehouse/requirements.txt

# A small made-up landing folder with one example of each data problem.
wh-sample:
	$(WH_VENV)/bin/python warehouse/sample_data.py --landing data/sample_landing

wh-load:
	$(WH_VENV)/bin/python warehouse/load.py --target $(WH_TARGET) --landing $(WH_LANDING) \
		--duckdb-path $(WH_DUCKDB) $(if $(MONTHS),--months $(MONTHS))

# The --empty run creates any missing tables with no rows first, so the
# incremental unit test has a table to read on a brand-new warehouse.
wh-dbt:
	$(WH_DBT_ENV) run --empty --select +fct_price --quiet
	$(WH_DBT_ENV) build

wh-freshness:
	$(WH_DBT_ENV) source freshness

warehouse: wh-load wh-dbt
