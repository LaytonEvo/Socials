"""Requests, results and capabilities shared by every adapter.

Two things here are shaped by Spike 0 findings rather than by the vendors.

**`SeedSupport` is three-valued.** Every provider tested accepts a seed; none
honoured it. The spike sent an identical seed twice to the same model and measured
a 25.42/255 mean per-pixel difference, so a pipeline that treats "accepts a seed"
as "reproducible" is wrong. `accepted_not_honoured` is the honest third value, and
it is the one both configured video models actually have.

**Job status strings match the `job` table's CHECK constraint exactly.** An adapter
status that the database refuses is a row that cannot be written at the moment
something has just been billed, which is the worst time to discover a typo.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    """Mirrors `ck_status_vocabulary` on the `job` table. Do not diverge."""

    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    @property
    def is_finished(self) -> bool:
        return self is not JobStatus.SUBMITTED and self is not JobStatus.RUNNING


class SeedSupport(StrEnum):
    NONE = "none"
    #: Sent and respected. Nothing tested so far is in this category.
    HONOURED = "honoured"
    #: Sent, accepted, and makes no difference to the output. Both video models.
    ACCEPTED_NOT_HONOURED = "accepted_not_honoured"


class AudioSupport(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    #: Generates a soundtrack whether or not one is wanted, with no flag to stop
    #: it. The turbo video model does this, which is why every clip in one battery
    #: came back speaking an unidentified language.
    FORCED = "forced"


@dataclass(frozen=True)
class Capabilities:
    """What a model can actually do, read from config rather than hardcoded.

    CLAUDE.md keeps model facts in `config/providers.yaml`. A capability asserted in
    code is a second source of truth that goes stale the first time a provider
    changes, and nothing notices.
    """

    durations_s: tuple[float, ...] = ()
    aspects: tuple[str, ...] = ()
    image_to_video: bool = False
    audio: AudioSupport = AudioSupport.NONE
    seed: SeedSupport = SeedSupport.NONE

    def permits_duration(self, seconds: float) -> bool:
        return not self.durations_s or seconds in self.durations_s

    def permits_aspect(self, aspect: str) -> bool:
        return not self.aspects or aspect in self.aspects


# ------------------------------------------------------------------ requests --
@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    #: An existing image to edit. Present for a wardrobe change, because editing a
    #: master still keeps the face the threshold was calibrated against, where
    #: generating a fresh one only hopes for it.
    source_key: str | None = None
    seed: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoRequest:
    prompt: str
    duration_s: float
    #: The keyframe. Authoritative over her body; the prompt is authoritative over
    #: the world. Changing clothes in the prompt forces a cut and a re-rendered
    #: person, so wardrobe belongs in this image.
    keyframe_key: str | None = None
    last_frame_key: str | None = None
    aspect: str = "9:16"
    seed: int | None = None
    #: A soundtrack to mux in. It does NOT drive the mouth: the spike measured a
    #: pinned track landing bit-exact while the lips ignored it entirely.
    audio_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    voice_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LipSyncRequest:
    video_key: str
    audio_key: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRequest:
    """A prompt plus the JSON schema the reply must satisfy.

    The schema is not optional. Task 3.1 requires a schema-validated shot list, and
    a free-text reply that happens to look like JSON is the thing that breaks
    quietly three weeks later.
    """

    prompt: str
    schema: dict[str, Any]
    system: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------- jobs, results --
@dataclass
class ProviderJob:
    """One call to a provider, from submit to outcome.

    Mutable, and carries `cost_usd` even when it produced nothing — amendment A2.
    A refusal after billing, a timeout, and a mid-generation failure all cost money,
    and `generation` rows only exist for calls that returned something.
    """

    provider: str
    model: str
    provider_job_id: str | None = None
    status: JobStatus = JobStatus.SUBMITTED
    submitted_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    completed_at: dt.datetime | None = None
    #: None only while the call is still in flight. Once finished this is a number,
    #: because "we do not know what it cost" is a state the `job` table refuses.
    cost_usd: Decimal | None = None
    error: str | None = None
    #: Whether the provider billed for this call. False for a pre-submission
    #: refusal; True for anything that reached generation. Where an adapter cannot
    #: tell, it says True — a ledger that understates is worse than one that
    #: over-reserves.
    billed: bool = True


@dataclass(frozen=True)
class AssetResult:
    """An artefact that landed in object storage."""

    storage_key: str
    content_type: str
    bytes_written: int
    duration_s: float | None = None


@dataclass(frozen=True)
class TextResult:
    """A schema-validated reply from an LLM."""

    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    """A provider refused or failed. Carries whether the attempt was billed."""

    def __init__(self, message: str, *, billed: bool = True) -> None:
        super().__init__(message)
        self.billed = billed


class ProviderRefused(ProviderError):
    """Refused before any work started, so nothing was billed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, billed=False)


class CapabilityError(ProviderError):
    """The request asks for something the model cannot do. Free, because it
    is caught before the call."""

    def __init__(self, message: str) -> None:
        super().__init__(message, billed=False)
