"""`Fake*` providers. Task 0.6: the pipeline runs end to end on these.

They exist so the pipeline, the review UI and the tests can run with no network and
no spend. The risk with a fake is that it is *more permissive* than the real thing,
because then every test passes and the first real call fails — so these enforce the
same capability checks the real adapters will, reading them from the same config.

Two places they are deliberately **unlike** reality, stated here because building on
either would be a mistake:

- **They are byte-for-byte deterministic.** The same request produces the same
  output. No real model tested is: an identical seed sent twice to the same model
  gave a 25.42/255 mean per-pixel difference. Nothing may assume reproducibility
  because the fake has it.
- **They are instant.** A real video take runs minutes, which is why there is a
  worker at all. A test that passes quickly here proves nothing about timeouts.

They can, however, simulate the failure that matters: a call billed for work that
produced nothing. `FakeVideoProvider(fail_after_billing=True)` is amendment A2's
case, and it is the one nobody tests by accident.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.storage import StorageBackend

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
    SeedSupport,
    TextResult,
    VideoRequest,
    VoiceRequest,
)

#: Costs nothing, and says so with a real zero rather than a missing price. The
#: `fake` slots in config/providers.yaml carry 0.0 with a 1970 verification date
#: for the same reason: a price that is absent and a price that is genuinely zero
#: mean different things to the cost guard.
FREE = Decimal("0")


def _deterministic_bytes(*parts: object, size: int = 256) -> bytes:
    """Stable synthetic content derived from the request."""
    seed = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    out = bytearray()
    while len(out) < size:
        out.extend(seed)
        seed = hashlib.sha256(seed).digest()
    return bytes(out[:size])


@dataclass
class _FakeBase:
    """Shared bookkeeping: storage, the job log, and the A2 failure switch."""

    storage: StorageBackend
    #: Set to simulate a provider that billed and then produced nothing.
    fail_after_billing: bool = False
    #: Set to simulate a refusal before any work started, which is free.
    refuse: bool = False
    #: Every job this provider has created, for tests and for the dry run's report.
    jobs: list[ProviderJob] = field(default_factory=list)
    _results: dict[str, AssetResult | TextResult] = field(default_factory=dict, repr=False)

    name: str = "fake"
    model: str = "fake-v0"

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def cost_of(self, job: ProviderJob) -> Decimal:
        return job.cost_usd if job.cost_usd is not None else FREE

    def _start(self, model_price: Decimal) -> ProviderJob:
        job = ProviderJob(provider=self.name, model=self.model)
        self.jobs.append(job)
        if self.refuse:
            job.status = JobStatus.FAILED
            job.completed_at = dt.datetime.now(dt.UTC)
            job.cost_usd = FREE
            job.billed = False
            job.error = "fake refusal before submission"
            raise ProviderError(job.error, billed=False)
        job.provider_job_id = f"fake-{len(self.jobs):04d}"
        job.cost_usd = model_price
        return job

    def _finish(self, job: ProviderJob, result: AssetResult | TextResult) -> ProviderJob:
        if self.fail_after_billing:
            job.status = JobStatus.TIMED_OUT
            job.completed_at = dt.datetime.now(dt.UTC)
            job.error = "fake timeout after the provider began generating"
            job.billed = True
            return job
        job.status = JobStatus.SUCCEEDED
        job.completed_at = dt.datetime.now(dt.UTC)
        assert job.provider_job_id is not None
        self._results[job.provider_job_id] = result
        return job

    async def poll(self, job: ProviderJob) -> Any:
        if job.status is not JobStatus.SUCCEEDED:
            raise ProviderError(
                job.error or f"job {job.provider_job_id} is {job.status}", billed=job.billed
            )
        assert job.provider_job_id is not None
        return self._results[job.provider_job_id]


@dataclass
class FakeImageProvider(_FakeBase):
    name: str = "fake-image"
    model: str = "fake-image-v0"

    def capabilities(self) -> Capabilities:
        return Capabilities(aspects=("9:16", "16:9", "1:1"), seed=SeedSupport.HONOURED)

    def estimate_cost(self, req: ImageRequest) -> Decimal:
        return FREE

    async def generate(self, req: ImageRequest, *, key: str) -> ProviderJob:
        job = self._start(FREE)
        data = _deterministic_bytes("image", req.prompt, req.source_key, req.seed, size=512)
        self.storage.put(key, data, content_type="image/png")
        return self._finish(job, AssetResult(key, "image/png", len(data)))


@dataclass
class FakeVideoProvider(_FakeBase):
    name: str = "fake-video"
    model: str = "fake-video-v0"

    def capabilities(self) -> Capabilities:
        return Capabilities(
            durations_s=(4.0, 5.0, 6.0, 8.0),
            aspects=("9:16", "16:9", "1:1"),
            image_to_video=True,
            audio=AudioSupport.OPTIONAL,
            # Matching both real video slots. A pipeline that treats a seed as
            # making a take reproducible is wrong, and the fake must not teach it
            # otherwise.
            seed=SeedSupport.ACCEPTED_NOT_HONOURED,
        )

    def estimate_cost(self, req: VideoRequest) -> Decimal:
        return FREE

    async def generate(self, req: VideoRequest, *, key: str) -> ProviderJob:
        caps = self.capabilities()
        if not caps.permits_duration(req.duration_s):
            raise CapabilityError(
                f"{self.model} takes {caps.durations_s} seconds, not {req.duration_s}. "
                f"The real models are the same: one accepts 4, 6 or 8 as literals and "
                f"the other an integer no lower than 5, and the wrong value is a 422."
            )
        if not caps.permits_aspect(req.aspect):
            raise CapabilityError(f"{self.model} cannot render {req.aspect}")
        job = self._start(FREE)
        data = _deterministic_bytes(
            "video", req.prompt, req.keyframe_key, req.duration_s, req.seed, size=1024
        )
        self.storage.put(key, data, content_type="video/mp4")
        return self._finish(job, AssetResult(key, "video/mp4", len(data), req.duration_s))


@dataclass
class FakeVoiceProvider(_FakeBase):
    name: str = "fake-voice"
    model: str = "fake-tts-v0"

    def estimate_cost(self, req: VoiceRequest) -> Decimal:
        return FREE

    async def generate(self, req: VoiceRequest, *, key: str) -> ProviderJob:
        job = self._start(FREE)
        data = _deterministic_bytes("voice", req.text, req.voice_id, size=384)
        self.storage.put(key, data, content_type="audio/mpeg")
        # Roughly 15 characters a second, which is close enough to the measured
        # 3.84 s for the spike's 58-character line to be useful for a dry run.
        seconds = max(len(req.text) / 15.0, 0.5)
        return self._finish(job, AssetResult(key, "audio/mpeg", len(data), seconds))


@dataclass
class FakeLipSyncProvider(_FakeBase):
    name: str = "fake-lipsync"
    model: str = "fake-lipsync-v0"

    def estimate_cost(self, req: LipSyncRequest) -> Decimal:
        return FREE

    async def generate(self, req: LipSyncRequest, *, key: str) -> ProviderJob:
        job = self._start(FREE)
        data = _deterministic_bytes("lipsync", req.video_key, req.audio_key, size=1024)
        self.storage.put(key, data, content_type="video/mp4")
        return self._finish(job, AssetResult(key, "video/mp4", len(data)))


@dataclass
class FakeLLMProvider(_FakeBase):
    """Returns a shot list shaped like the schema it was given.

    Deliberately schema-driven rather than a fixed fixture: task 3.1 validates the
    reply, and a fake that returns a hand-written dict would pass validation the
    real model might fail.
    """

    name: str = "fake-llm"
    model: str = "fake-llm-v0"
    #: Shots the fake produces, so a dry run can ask for a specific shape.
    shots: int = 3

    def estimate_cost(self, req: LLMRequest) -> Decimal:
        return FREE

    async def generate(self, req: LLMRequest) -> ProviderJob:
        job = self._start(FREE)
        data = {
            "shots": [
                {
                    "order": index,
                    "description": f"fake shot {index} for: {req.prompt[:60]}",
                    "duration_s": 5.0,
                    "shot_type": "face" if index == 0 else "broll",
                    "dialogue": f"Line {index}." if index == 0 else None,
                    "format": "talking_head_course",
                }
                for index in range(self.shots)
            ]
        }
        return self._finish(
            job,
            TextResult(data=data, input_tokens=len(req.prompt) // 4, output_tokens=64),
        )
