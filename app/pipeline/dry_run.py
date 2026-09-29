"""A pipeline run end to end on fakes — task 0.6's acceptance criterion.

This is not task 3.4's orchestrator. It has no identity scoring, no retry cap, no
review queue and no database; those arrive with Phase 1 and Phase 3. What it does
is prove the seams fit: a brief becomes a shot list, each shot gets a keyframe and
takes, dialogue shots get a voice line and a lip sync, and every artefact lands in
storage under the right persona prefix.

Worth having as real code rather than as a test fixture. The seams it exercises —
five providers, one storage backend, one key scheme — are the ones 3.4 will reuse,
and a shape that only exists inside a test is a shape nobody has to keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.providers import (
    ImageProvider,
    ImageRequest,
    JobStatus,
    LipSyncProvider,
    LipSyncRequest,
    LLMProvider,
    LLMRequest,
    ProviderError,
    ProviderJob,
    VideoProvider,
    VideoRequest,
    VoiceProvider,
    VoiceRequest,
)
from app.storage import StorageBackend, key_for

SHOT_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["shots"],
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["order", "description", "duration_s", "shot_type"],
                "properties": {
                    "order": {"type": "integer"},
                    "description": {"type": "string"},
                    "duration_s": {"type": "number"},
                    "shot_type": {"enum": ["face", "broll"]},
                    "dialogue": {"type": ["string", "null"]},
                    "format": {"type": "string"},
                },
            },
        }
    },
}


@dataclass
class Providers:
    """The five adapters a run needs. Protocols, so fakes and real ones both fit."""

    llm: LLMProvider
    image: ImageProvider
    video: VideoProvider
    voice: VoiceProvider
    lipsync: LipSyncProvider


@dataclass
class ShotOutcome:
    order: int
    shot_type: str
    keyframe_key: str
    take_keys: list[str] = field(default_factory=list)
    voice_key: str | None = None
    lipsync_key: str | None = None
    #: Takes that were billed and produced nothing. Amendment A2's case, carried
    #: through to the report rather than swallowed.
    billed_failures: int = 0


@dataclass
class DryRunReport:
    shots: list[ShotOutcome] = field(default_factory=list)
    jobs: list[ProviderJob] = field(default_factory=list)

    @property
    def total_cost(self) -> Decimal:
        """Every job's cost, including the ones that produced nothing."""
        return sum((job.cost_usd or Decimal("0") for job in self.jobs), Decimal("0"))

    @property
    def artefacts(self) -> list[str]:
        keys: list[str] = []
        for shot in self.shots:
            keys.append(shot.keyframe_key)
            keys.extend(shot.take_keys)
            keys.extend(k for k in (shot.voice_key, shot.lipsync_key) if k)
        return keys

    @property
    def billed_failures(self) -> int:
        return sum(shot.billed_failures for shot in self.shots)


async def dry_run(
    brief: str,
    *,
    persona_id: str,
    providers: Providers,
    storage: StorageBackend,
    takes_per_shot: int = 2,
    clip_duration_s: float = 5.0,
    voice_id: str = "fake-voice-id",
) -> DryRunReport:
    """Run a brief through every stage, on whatever providers are supplied."""
    report = DryRunReport()

    shot_job = await providers.llm.generate(
        LLMRequest(prompt=brief, schema=SHOT_LIST_SCHEMA, system="You write golf shot lists.")
    )
    report.jobs.append(shot_job)
    shot_list = await providers.llm.poll(shot_job)

    for shot in shot_list.data["shots"]:
        order = int(shot["order"])
        outcome = ShotOutcome(
            order=order,
            shot_type=str(shot["shot_type"]),
            keyframe_key=key_for(persona_id, "keyframe", f"shot{order:02d}.png"),
        )

        keyframe_job = await providers.image.generate(
            ImageRequest(prompt=shot["description"]), key=outcome.keyframe_key
        )
        report.jobs.append(keyframe_job)
        await providers.image.poll(keyframe_job)

        for take in range(takes_per_shot):
            take_key = key_for(persona_id, "take", f"shot{order:02d}-take{take}.mp4")
            take_job = await providers.video.generate(
                VideoRequest(
                    prompt=shot["description"],
                    duration_s=clip_duration_s,
                    keyframe_key=outcome.keyframe_key,
                ),
                key=take_key,
            )
            report.jobs.append(take_job)
            try:
                await providers.video.poll(take_job)
            except ProviderError as exc:
                # A take that failed after billing is still spend. Recorded, not
                # swallowed: this is the case the `job` table exists for.
                if exc.billed or take_job.status is JobStatus.TIMED_OUT:
                    outcome.billed_failures += 1
                continue
            outcome.take_keys.append(take_key)

        dialogue = shot.get("dialogue")
        if dialogue:
            outcome.voice_key = key_for(persona_id, "voice", f"shot{order:02d}.mp3")
            voice_job = await providers.voice.generate(
                VoiceRequest(text=dialogue, voice_id=voice_id), key=outcome.voice_key
            )
            report.jobs.append(voice_job)
            await providers.voice.poll(voice_job)

            # Lip sync applies to an accepted face-forward take. With no review
            # stage yet, the first usable take stands in for "accepted" — and
            # amendment A5 notes the render must be re-scored after this, which
            # is Phase 3's job because there is nothing scoring anything yet.
            if outcome.take_keys:
                outcome.lipsync_key = key_for(persona_id, "render", f"shot{order:02d}-synced.mp4")
                sync_job = await providers.lipsync.generate(
                    LipSyncRequest(video_key=outcome.take_keys[0], audio_key=outcome.voice_key),
                    key=outcome.lipsync_key,
                )
                report.jobs.append(sync_job)
                await providers.lipsync.poll(sync_job)

        report.shots.append(outcome)

    return report
