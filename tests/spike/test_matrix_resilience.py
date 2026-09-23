"""A refused cell must not end the matrix, and must not look like a failure.

fal's content checker refuses legitimate prompts non-deterministically (ADR
0006). Halting on the first refusal meant a matrix rarely finished, and the
cells that did finish were not a random sample of the ones attempted — a
biased result wearing the clothes of a partial one.
"""

from __future__ import annotations

from scripts.spike.errors import BudgetExceeded, ProviderRefused, SpikeError


def _run(outcomes: list[object], max_skips: int = 3) -> tuple[list[str], list[str], bool]:
    """The loop's error policy, exercised directly.

    Mirrors cmd_run_matrix rather than invoking it, so the policy is tested
    without a provider, a scorer or a network.
    """
    scored: list[str] = []
    skipped: list[str] = []
    halted = False
    for i, outcome in enumerate(outcomes):
        ref = f"cell-{i}"
        try:
            if isinstance(outcome, Exception):
                raise outcome
            scored.append(ref)
        except BudgetExceeded:
            halted = True
            break
        except SpikeError:
            skipped.append(ref)
            if len(skipped) >= max_skips:
                halted = True
                break
    return scored, skipped, halted


def test_a_refused_cell_is_skipped_and_the_run_continues():
    scored, skipped, halted = _run([None, ProviderRefused("content policy"), None])
    assert scored == ["cell-0", "cell-2"]
    assert skipped == ["cell-1"]
    assert not halted


def test_budget_exhaustion_still_stops_everything():
    """The one thing that must halt. Carrying on past the cap is the failure
    the guard exists to prevent."""
    scored, skipped, halted = _run([None, BudgetExceeded("over cap"), None])
    assert scored == ["cell-0"]
    assert halted
    assert skipped == []


def test_repeated_refusals_stop_the_run_rather_than_grinding_through():
    """Something systematic is wrong, and discovering that one cell at a time
    wastes both time and budget."""
    scored, skipped, halted = _run([ProviderRefused("x")] * 5, max_skips=3)
    assert halted
    assert len(skipped) == 3
    assert scored == []


def test_skipped_cells_are_not_counted_as_failures():
    """A clip that was never generated is missing evidence, not bad evidence.
    Folding the two together would understate the identity result."""
    scored, skipped, _ = _run([None, ProviderRefused("x"), None, None])
    assert len(scored) == 3
    assert len(skipped) == 1
    assert set(scored).isdisjoint(skipped)
