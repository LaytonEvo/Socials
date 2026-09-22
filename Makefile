# Always go through `python3 -m` so the tooling runs on the same interpreter
# that holds the dependencies. A `mypy` on PATH can belong to a different
# Python and will report every third-party import as missing.
PY ?= python3

.PHONY: check lint types test demo clean-runs

check: lint types test

lint:
	$(PY) -m ruff check scripts tests
	$(PY) -m ruff format --check scripts tests

types:
	$(PY) -m mypy

test:
	$(PY) -m pytest -q

demo:
	$(PY) -m scripts.spike.cli demo

clean-runs:
	rm -rf spike/runs
