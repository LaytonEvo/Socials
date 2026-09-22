"""Failure modes the harness raises deliberately.

Each one corresponds to a rule in CLAUDE.md or a blocker in docs/BUILD_ORDER.md.
They exist so that the harness stops loudly rather than producing evidence that
looks fine and is not.
"""

from __future__ import annotations


class SpikeError(Exception):
    """Base class for every deliberate refusal in the harness."""


class ConfigError(SpikeError):
    """config/spike.yaml is missing something, or something is unverified."""


class UnverifiedPriceError(ConfigError):
    """A price has no verified_on date, or the date is stale.

    CLAUDE.md: "Never hardcode model names, endpoints, or prices. They live in
    config with a verified_on date."
    """


class ProviderNotConfigured(ConfigError):
    """A provider slot is still a placeholder.

    Fill it in only after reading the provider's current official docs, and
    record the result in docs/decisions/ per CLAUDE.md.
    """


class EmbedderNotConfigured(ConfigError):
    """No identity scorer has been chosen.

    Blocked on docs/decisions/0002-face-embedding-model-licence.md. The scorer
    is the measuring instrument for the whole spike; it cannot be picked
    provisionally and swapped later without invalidating every measurement.
    """


class BudgetExceeded(SpikeError):
    """A paid call was refused because it would breach the run budget.

    Raised BEFORE the call is made, never after.
    """


class BudgetNotSet(SpikeError):
    """A run that can spend money was started without an explicit budget.

    BUILD_ORDER amendment A7: no live provider call outside an explicitly
    budgeted run.
    """


class CalibrationMismatch(SpikeError):
    """A calibration is being used with a different embedder than produced it.

    BUILD_ORDER amendment A3: a threshold is valid for exactly one embedding
    model at one version.
    """


class FakeDataInReport(SpikeError):
    """A Gate A report was requested from a run containing stub-provider data.

    A human reads the Gate A report to make a go/no-go decision. Fake evidence
    must never reach it silently.
    """


class FfmpegMissing(SpikeError):
    """Frame extraction from video needs ffmpeg on PATH."""
