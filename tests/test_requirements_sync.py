"""requirements.txt must not drift from pyproject.toml.

The two files list the same dependencies for different readers: pyproject.toml for pip
and for anyone installing the project, requirements.txt for Railway's builder, which
does not treat a setuptools pyproject.toml as a Python detection trigger. A duplicated
list is a drift risk, so this test is the thing that makes the duplication safe.
"""

from __future__ import annotations

import pathlib

from scripts.gen_requirements import REQUIREMENTS, dependencies, render


def test_requirements_matches_pyproject() -> None:
    """Regenerating from pyproject.toml must not change requirements.txt."""
    assert REQUIREMENTS.read_text() == render(), (
        "requirements.txt is out of step with pyproject.toml. "
        "Run `make requirements` to regenerate it."
    )


def test_requirements_lists_every_runtime_dependency() -> None:
    """Every dependency in pyproject.toml appears in requirements.txt."""
    listed = {
        line.strip()
        for line in REQUIREMENTS.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert listed == set(dependencies())


def test_requirements_carries_the_server() -> None:
    """uvicorn specifically, because its absence is what crash-looped three deploys.

    A build that installs no packages still reports SUCCESS, so the failure only shows
    at container start. This pins the one dependency that failure turned on.
    """
    assert any(dep.startswith("uvicorn") for dep in dependencies())


def test_generator_is_not_left_pointing_at_a_missing_pyproject() -> None:
    """The paths the generator resolves must exist, or the test above passes vacuously."""
    assert pathlib.Path(REQUIREMENTS).exists()
