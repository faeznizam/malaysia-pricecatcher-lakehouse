PYTHON ?= .venv/bin/python
MONTHS ?= 2026-09 2026-10

.PHONY: venv test download profile bronze silver gold report pipeline

venv:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest -v

download:
	$(PYTHON) -m pricecatcher.download --months $(MONTHS)

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
