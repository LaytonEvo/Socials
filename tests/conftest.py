"""Guards for tests that can spend money.

`CLAUDE.md`: live-provider tests are opt-in (`pytest -m live`) and budget-capped.
`docs/BUILD_ORDER.md` amendment A7: no live call outside a budgeted run.

Both are enforced here rather than trusted to discipline, because the failure
mode is silent and expensive: a live test that runs because someone typed
`pytest` is a bill nobody decided to incur. Three conditions must all hold
before a live test is allowed to run, and missing any of them **skips** rather
than fails — a developer running the suite normally should see the same green
as always, not a wall of red about credentials they were never meant to have.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pytest

LIVE = "live"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live-budget",
        default=None,
        metavar="USD",
        help=(
            "Hard spend cap for live provider tests, in USD. Required by -m live. "
            "There is deliberately no default: a default budget is a budget nobody chose."
        ),
    )


def _budget(config: pytest.Config) -> Decimal | None:
    raw = config.getoption("--live-budget")
    if raw is None:
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise pytest.UsageError(f"--live-budget must be a number in USD, got {raw!r}") from None
    if value <= 0:
        raise pytest.UsageError(f"--live-budget must be greater than zero, got {value}")
    return value


def pytest_configure(config: pytest.Config) -> None:
    """Make sure skip reasons are visible when live tests were asked for.

    Someone who typed `-m live` asked for those tests to run. Under `-q` a skip
    prints as a bare `s` with no reason, which reads as "ran, fine" -- the wrong
    thing to believe about a guard standing in front of money. So when live was
    requested, force skip reasons on.

    Done here rather than at collection because the terminal reporter reads
    `reportchars` when it is constructed, which is earlier; setting it later has
    no effect, as a test caught.
    """
    if not _live_was_asked_for(config):
        return
    chars = getattr(config.option, "reportchars", "") or ""
    if not any(c in chars for c in "saA"):
        config.option.reportchars = chars + "s"
        reporter = config.pluginmanager.getplugin("terminalreporter")
        if reporter is not None:  # already built: update it too
            reporter.reportchars = config.option.reportchars


def _live_was_asked_for(config: pytest.Config) -> bool:
    """Only an explicit `-m live` counts.

    Checked against the -m expression rather than a flag of our own, so that
    the documented command in CLAUDE.md is the one that works. A bare `pytest`,
    or `-m "not slow"`, must never select these.
    """
    expr = config.getoption("-m", default="") or ""
    return LIVE in expr.replace("not " + LIVE, "")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live_items = [i for i in items if i.get_closest_marker(LIVE)]
    if not live_items:
        return

    if not _live_was_asked_for(config):
        skip = pytest.mark.skip(reason="live test: needs an explicit `-m live`")
        for item in live_items:
            item.add_marker(skip)
        return

    if _budget(config) is None:
        skip = pytest.mark.skip(
            reason="live test selected but no --live-budget given; refusing to spend an "
            "amount nobody set (BUILD_ORDER A7)"
        )
        for item in live_items:
            item.add_marker(skip)


@pytest.fixture
def live_budget(request: pytest.FixtureRequest) -> Decimal:
    """The cap for this live run. Requesting it outside a live test is a bug."""
    if request.node.get_closest_marker(LIVE) is None:
        raise RuntimeError("live_budget is only meaningful on a test marked @pytest.mark.live")
    budget = _budget(request.config)
    if budget is None:  # pragma: no cover - collection should have skipped first
        pytest.skip("no --live-budget")
    return budget


@pytest.fixture
def require_env(request: pytest.FixtureRequest):
    """Skip a live test when its credential is absent, rather than failing it.

    Absent credentials mean "not configured here", not "broken".
    """
    import os

    def _require(*names: str) -> dict[str, str]:
        missing = [n for n in names if not os.environ.get(n)]
        if missing:
            pytest.skip(f"live test needs {', '.join(missing)} in the environment")
        return {n: os.environ[n] for n in names}

    return _require
