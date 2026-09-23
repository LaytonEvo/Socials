"""The guards that stand between a stray `pytest` and a real bill.

Tested with pytest's own in-process runner rather than by reasoning about the
conftest, because the thing being asserted is what the collector actually does.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

LIVE_TEST = """
import pytest

@pytest.mark.live
def test_spends_money():
    assert True

def test_free():
    assert True
"""


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    """A throwaway project using the real conftest, not a copy of it."""
    from pathlib import Path

    conftest = Path(__file__).resolve().parents[1] / "conftest.py"
    pytester.makeconftest(conftest.read_text())
    pytester.makeini("[pytest]\nmarkers =\n    live: spends real money\n")
    pytester.makepyfile(test_sample=LIVE_TEST)
    return pytester


def test_a_bare_pytest_run_never_selects_a_live_test(project):
    """The failure this exists to prevent: someone types `pytest`, money moves."""
    result = project.runpytest("-q")
    result.assert_outcomes(passed=1, skipped=1)


def test_live_without_a_budget_is_skipped_not_run(project):
    """Amendment A7: no live call outside an explicitly budgeted run."""
    result = project.runpytest("-q", "-m", "live")
    result.assert_outcomes(skipped=1, deselected=1)
    # And it must say why, even at -q: a silent skip reads as a pass, which is
    # the wrong thing to believe about a guard that stands in front of money.
    result.stdout.fnmatch_lines(["*live-budget*"])


def test_live_with_a_budget_runs(project):
    result = project.runpytest("-q", "-m", "live", "--live-budget", "5.00")
    result.assert_outcomes(passed=1, deselected=1)


def test_a_zero_or_negative_budget_is_refused(project):
    """A cap of zero reads like 'unlimited' to a careless eye. Refuse it."""
    for bad in ("0", "-1"):
        result = project.runpytest("-q", "-m", "live", "--live-budget", bad)
        result.stderr.fnmatch_lines(["*greater than zero*"])


def test_a_nonsense_budget_is_refused(project):
    result = project.runpytest("-q", "-m", "live", "--live-budget", "lots")
    result.stderr.fnmatch_lines(["*must be a number*"])


def test_excluding_live_does_not_count_as_asking_for_it(project):
    """`-m "not live"` must not trip the substring check and select them."""
    result = project.runpytest("-q", "-m", "not live", "--live-budget", "5.00")
    result.assert_outcomes(passed=1, deselected=1)
