# Always go through `python3 -m` so the tooling runs on the same interpreter
# that holds the dependencies. A `mypy` on PATH can belong to a different
# Python and will report every third-party import as missing.
PY ?= python3

.PHONY: check lint types test fmt install demo fetch-models check-embedder clean-runs

check: lint types test

# SRC is every path the tooling covers. `app` and `workers` are the production
# system; `scripts/spike` is the throwaway harness, still linted because it is
# still the only thing that runs.
SRC = app workers scripts tests

lint:
	$(PY) -m ruff check $(SRC)
	$(PY) -m ruff format --check $(SRC)

types:
	$(PY) -m mypy

fmt:
	$(PY) -m ruff format $(SRC)
	$(PY) -m ruff check --fix $(SRC)

# What CI runs on a clean clone, and what task 0.1's acceptance criteria mean by
# one: no editable install left over from a previous branch.
#
# RUN THIS IN A VIRTUALENV on Debian or Ubuntu. `redis` requires PyJWT >= 2.9,
# and a distro-installed PyJWT cannot be uninstalled by pip ("RECORD file not
# found"), so the install fails on a system Python through no fault of the
# dependency set. Override the interpreter rather than fighting it:
#
#     python3 -m venv .venv
#     make install PY=.venv/bin/python
#     make check   PY=.venv/bin/python
install:
	# Leading `-`: a distro-managed pip cannot uninstall itself ("RECORD file not
	# found"), which is the default on Debian and Ubuntu. The upgrade is a
	# convenience for very old pips, not a requirement, so its failure must not
	# take the install down with it.
	-$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

demo:
	$(PY) -m scripts.spike.cli demo

fetch-models:
	$(PY) -m scripts.spike.cli fetch-models

check-embedder:
	$(PY) -m scripts.spike.cli check-embedder

clean-runs:
	rm -rf spike/runs
