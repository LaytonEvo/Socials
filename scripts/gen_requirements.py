"""Regenerate requirements.txt from pyproject.toml.

pyproject.toml is the single source of truth for dependencies. requirements.txt exists
only because Railway's builder detects a Python project from it; see the header it
writes. tests/test_requirements_sync.py fails if the two drift apart.
"""

from __future__ import annotations

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"

HEADER = """\
# GENERATED FROM pyproject.toml — do not edit by hand.
#
# pyproject.toml remains the single source of truth for dependencies. This file is a
# mirror of its [project].dependencies, kept in step by tests/test_requirements_sync.py,
# which fails if the two drift apart. Regenerate with `make requirements`.
#
# It exists because Railway's builder (Railpack) detects a Python project from
# requirements.txt; a setuptools pyproject.toml with no lockfile is not a detection
# trigger, so without this the image builds with an interpreter and no packages, reports
# SUCCESS and then crash-loops on a missing uvicorn.
#
# The list is spelled out rather than a single `.` installing this project. Railpack
# installs dependencies in a layer that is cached before the source is copied, so at
# install time there is no pyproject.toml beside this file for `.` to resolve to.
"""


def dependencies() -> list[str]:
    """The runtime dependencies declared in pyproject.toml, in declaration order."""
    data = tomllib.loads(PYPROJECT.read_text())
    return list(data["project"]["dependencies"])


def render() -> str:
    """The full requirements.txt content implied by pyproject.toml."""
    return HEADER + "\n".join(dependencies()) + "\n"


def main() -> None:
    REQUIREMENTS.write_text(render())
    print(f"wrote {REQUIREMENTS.relative_to(ROOT)} with {len(dependencies())} dependencies")


if __name__ == "__main__":
    main()
