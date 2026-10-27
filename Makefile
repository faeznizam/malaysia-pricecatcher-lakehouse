PYTHON ?= .venv/bin/python
# Download every month from SINCE to now, or set MONTHS for specific ones.
SINCE ?= 2026-05

.PHONY: venv test download profile bronze silver gold report pipeline benchmark

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

report:
	$(PYTHON) -m pricecatcher.report

# Everything after download, in order (what the daily schedule runs).
pipeline: bronze silver gold report

benchmark:
	$(PYTHON) -m pricecatcher.benchmark
