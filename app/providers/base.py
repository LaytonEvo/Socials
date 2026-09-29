"""The five adapter protocols from BUILD_PLAN Section 5.

Pipeline code depends on these and never on a vendor. The rule is enforced rather
than asserted: `tests/app/test_scaffold.py` reads every module's imports and fails
if a vendor SDK appears outside the package that adapts it.

Each protocol has the same five members, and the fifth is the one amendment A2
added: `cost_of(job)` reports what a call cost **whether or not it produced
anything**. A `generation` row exists only for a call that returned something, so
without this a timeout after billing had nowhere to be recorded and the ledger was
quietly incomplete.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from .types import (
    AssetResult,
    Capabilities,
    ImageRequest,
    LipSyncRequest,
    LLMRequest,
    ProviderJob,
    TextResult,
    VideoRequest,
    VoiceRequest,
)


@runtime_checkable
class Provider(Protocol):
    """What every adapter has, regardless of capability."""

    name: str
    model: str

    def capabilities(self) -> Capabilities: ...

    def cost_of(self, job: ProviderJob) -> Decimal:
        """The billable cost of a call, success or failure.

        An adapter that can tell a free failure from a billed one must do so — a
        403 before submission is free, a timeout after generation started is not.
        Where it cannot tell, it reports the cost as billed.
        """
        ...


@runtime_checkable
class ImageProvider(Provider, Protocol):
    async def generate(self, req: ImageRequest, *, key: str) -> ProviderJob: ...
    async def poll(self, job: ProviderJob) -> AssetResult: ...
    def estimate_cost(self, req: ImageRequest) -> Decimal: ...


@runtime_checkable
class VideoProvider(Provider, Protocol):
    async def generate(self, req: VideoRequest, *, key: str) -> ProviderJob: ...
    async def poll(self, job: ProviderJob) -> AssetResult: ...
    def estimate_cost(self, req: VideoRequest) -> Decimal: ...


@runtime_checkable
class VoiceProvider(Provider, Protocol):
    async def generate(self, req: VoiceRequest, *, key: str) -> ProviderJob: ...
    async def poll(self, job: ProviderJob) -> AssetResult: ...
    def estimate_cost(self, req: VoiceRequest) -> Decimal: ...


@runtime_checkable
class LipSyncProvider(Provider, Protocol):
    async def generate(self, req: LipSyncRequest, *, key: str) -> ProviderJob: ...
    async def poll(self, job: ProviderJob) -> AssetResult: ...
    def estimate_cost(self, req: LipSyncRequest) -> Decimal: ...


@runtime_checkable
class LLMProvider(Provider, Protocol):
    async def generate(self, req: LLMRequest) -> ProviderJob: ...
    async def poll(self, job: ProviderJob) -> TextResult: ...
    def estimate_cost(self, req: LLMRequest) -> Decimal: ...
