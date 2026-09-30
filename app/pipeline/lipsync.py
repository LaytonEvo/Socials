"""Task 3.7 — lip sync, applied selectively.

`BUILD_PLAN`: *"applied to accepted face-forward takes where dialogue is replaced;
skipped for B-roll."* Both halves of that matter and they fail differently.

Syncing B-roll is money spent making a mouth move that nobody is looking at — at
$0.10/second it is the most expensive stage in the chain, four times the cost of
generating the clip in the first place. Skipping a face-forward take with dialogue is
worse: the viewer sees a person talking with the wrong mouth, which is the single most
recognisable tell of synthetic video.

So the decision is a rule with a name rather than a judgement made per shot, and
`should_lip_sync` is the only place it lives.

**Amendment A5**: whatever comes out of here must be re-scored. `generation.identity_*`
describes the face before its last transformation, and the measured delta for this model
was `+0.0041` — small, and positive, and not zero.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.pipeline.errors import PipelineError


class LipSyncFailed(PipelineError):
    """The sync did not produce a usable clip."""


@dataclass(frozen=True)
class SyncDecision:
    """Why a take was or was not sent for sync, kept so the spend is explainable."""

    sync: bool
    reason: str


def should_lip_sync(*, face_forward: bool, has_dialogue: bool) -> SyncDecision:
    """The rule, in one place.

    Both conditions are required. A face-forward shot with no dialogue has nothing to
    sync to; a talking b-roll shot has no visible mouth to correct.
    """
    if not has_dialogue:
        return SyncDecision(False, "no dialogue on this shot")
    if not face_forward:
        return SyncDecision(False, "b-roll — the mouth is not the subject")
    return SyncDecision(True, "face-forward take with dialogue")


def lip_sync(
    client: httpx.Client,
    *,
    queue_root: str,
    model: str,
    video_url: str,
    audio_url: str,
    base: dict[str, Any],
    dest: Path,
    poll_interval_s: float = 5.0,
) -> Path:
    """Send one take for sync and download the result.

    `video_url` and `audio_url` are URLs rather than files because the provider fetches
    them itself. A presigned bucket URL keeps the take private; fal's own upload
    endpoint would not (ADR 0006).
    """
    arguments: dict[str, Any] = {"video_url": video_url, "audio_url": audio_url, **base}
    response = client.post(f"{queue_root}/{model}", json=arguments)
    if response.status_code >= 400:
        raise LipSyncFailed(f"submit failed {response.status_code}: {response.text[:400]}")
    submitted = response.json()
    status_url = str(submitted.get("status_url") or "")
    response_url = str(submitted.get("response_url") or "")
    if not status_url or not response_url:
        raise LipSyncFailed("provider accepted the job but returned no URLs to follow it")

    for _ in range(240):
        if client.get(status_url).json().get("status") in {"COMPLETED", "FAILED", "ERROR"}:
            break
        time.sleep(poll_interval_s)

    result = client.get(response_url)
    if result.status_code >= 400:
        raise LipSyncFailed(f"sync failed {result.status_code}: {result.text[:400]}")
    payload = result.json()
    url = str((payload.get("video") or {}).get("url") or "")
    if not url:
        raise LipSyncFailed(f"COMPLETED with no video: {str(payload)[:400]}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(client.get(url, timeout=300.0).content)
    return dest
