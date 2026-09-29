"""Provider adapters — the ONLY package that may import a model vendor's SDK.

One module per capability, each implementing a protocol from BUILD_PLAN Section 5:
`ImageProvider`, `VideoProvider`, `VoiceProvider`, `LipSyncProvider`, `LLMProvider`.
Model ids, endpoints and prices come from `config/providers.yaml` and are never
written in code.

Every adapter reports the cost of a call that produced nothing (amendment A2). A
refusal after billing, a timeout, and a mid-generation failure all cost money; an
adapter that cannot tell a free failure from a billed one reports it as billed, for
the same reason the price convention takes the higher published figure.

`Fake*` implementations live here too, and the pipeline must run end to end on them
before any paid call exists (task 0.6).
"""

from __future__ import annotations

from .base import (
    ImageProvider,
    LipSyncProvider,
    LLMProvider,
    Provider,
    VideoProvider,
    VoiceProvider,
)
from .fakes import (
    FakeImageProvider,
    FakeLipSyncProvider,
    FakeLLMProvider,
    FakeVideoProvider,
    FakeVoiceProvider,
)
from .types import (
    AssetResult,
    AudioSupport,
    Capabilities,
    CapabilityError,
    ImageRequest,
    JobStatus,
    LipSyncRequest,
    LLMRequest,
    ProviderError,
    ProviderJob,
    ProviderRefused,
    SeedSupport,
    TextResult,
    VideoRequest,
    VoiceRequest,
)

__all__ = [
    "AssetResult",
    "AudioSupport",
    "Capabilities",
    "CapabilityError",
    "FakeImageProvider",
    "FakeLLMProvider",
    "FakeLipSyncProvider",
    "FakeVideoProvider",
    "FakeVoiceProvider",
    "ImageProvider",
    "ImageRequest",
    "JobStatus",
    "LLMProvider",
    "LLMRequest",
    "LipSyncProvider",
    "LipSyncRequest",
    "Provider",
    "ProviderError",
    "ProviderJob",
    "ProviderRefused",
    "SeedSupport",
    "TextResult",
    "VideoProvider",
    "VideoRequest",
    "VoiceProvider",
    "VoiceRequest",
]
