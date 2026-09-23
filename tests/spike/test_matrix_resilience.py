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


# --- retry the refusals the provider is inconsistent about, and only those ---


def _retrying(outcomes: list[object], attempts: int = 3) -> tuple[int, str]:
    """The retry policy, exercised without a provider.

    Mirrors _generate_with_retry: re-attempt a refusal on the retryable list,
    raise anything else immediately.
    """
    from scripts.spike.fal import RETRYABLE_REFUSALS

    calls = 0
    last: Exception | None = None
    for attempt in range(attempts):
        calls += 1
        outcome = outcomes[min(attempt, len(outcomes) - 1)]
        if not isinstance(outcome, Exception):
            return calls, "generated"
        if getattr(outcome, "error_type", None) not in RETRYABLE_REFUSALS:
            return calls, "raised-immediately"
        last = outcome
    assert last is not None
    return calls, "gave-up"


def test_a_content_policy_refusal_is_retried():
    """Measured, not assumed: the same image and prompt were refused and then
    accepted moments later, so one refusal says little."""
    refusal = ProviderRefused("flagged", error_type="content_policy_violation")
    calls, outcome = _retrying([refusal, refusal, None])
    assert calls == 3
    assert outcome == "generated"


def test_no_media_generated_is_not_retried():
    """A property of the input: one master still failed four times out of four.
    Retrying spends time to learn nothing."""
    refusal = ProviderRefused("no media", error_type="no_media_generated")
    calls, outcome = _retrying([refusal])
    assert calls == 1
    assert outcome == "raised-immediately"


def test_a_refusal_with_no_error_type_is_not_retried():
    """Absent a reason, assume the provider meant it."""
    calls, outcome = _retrying([ProviderRefused("something")])
    assert calls == 1
    assert outcome == "raised-immediately"


def test_retrying_gives_up_rather_than_looping():
    refusal = ProviderRefused("flagged", error_type="content_policy_violation")
    calls, outcome = _retrying([refusal], attempts=3)
    assert calls == 3
    assert outcome == "gave-up"
