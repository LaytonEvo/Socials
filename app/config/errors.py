"""Config errors, separated by who has to act on them.

The distinction is the point. A malformed file is a bug and the developer fixes
it now. An unmade decision is not a bug — BUILD_PLAN Section 1 reserves eight of
them for a human, and CLAUDE.md says to use the placeholders and flag them — so
the config must load with those outstanding and fail only where a value is
actually needed.

Collapsing the two would mean either blocking the whole build on a decision that
only affects publishing, or letting a placeholder reach a provider as if it were
a value. Both have happened in this project's history; neither should be possible.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Base for every configuration failure."""


class ConfigFileError(ConfigError):
    """The file is missing, unreadable, or not the YAML shape expected.

    A developer's problem, raised at load. This is what task 0.2's "invalid
    config fails fast with a clear error" means.
    """


class DecisionPending(ConfigError):
    """A human decision has not been made, and something needs its value.

    Raised at the point of use, never at load. Carries the decision's own name
    so the message points at BUILD_PLAN Section 1 rather than at a line number.
    """


class UnverifiedPrice(ConfigError):
    """A price is missing, undated, or older than `price_max_age_days`.

    CLAUDE.md: prices live in config with a `verified_on` date. A stale price is
    a silent overspend, so the guard refuses rather than warns.
    """


class DisclosureWeakened(ConfigError):
    """Config tried to express a state where disclosure is off.

    CLAUDE.md: "Disclosure cannot be disabled. Don't add a flag, env var, or code
    path that skips either." A config key that turns it off is such a flag, so
    the loader refuses the file outright rather than trusting later code to
    ignore the value.
    """


class PolicyWeakened(ConfigError):
    """Config tried to weaken a permanent content prohibition.

    CLAUDE.md: "Financial products are out of scope permanently. The policy guard
    blocks them. Don't weaken it."
    """
