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
