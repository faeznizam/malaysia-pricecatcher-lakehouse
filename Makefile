PYTHON ?= .venv/bin/python
MONTHS ?= 2026-09 2026-10

.PHONY: venv test download profile

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
