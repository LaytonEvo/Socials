"""Sound for shots where nobody is speaking.

Dropping the video model's invented soundtrack was right — it was a generated voice in
no identifiable language that nobody chose. Leaving the shot in total silence was not.
A golf swing with no contact sound reads as broken, and silence under b-roll reads as a
missing file rather than as a choice.

This generates audio ALIGNED TO THE PICTURE from a text prompt, which is the thing a
stock library cannot do: the ball has to sound at the frame the club reaches it, and
that frame is different in every take.

**It is not her voice and must never be used as one.** Speech belongs to the voice
provider, where one voice stays constant across every video (ADR 0005); this is for the
world around her.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.pipeline.errors import PipelineError


class SoundFailed(PipelineError):
    """Audio could not be generated for a shot."""


#: Prompts that ask for the world, never for a person. A prompt mentioning speech would
#: put an invented voice back into the render through a different door.
FORBIDDEN = ("speech", "speaking", "voice", "talking", "dialogue", "narration", "singing")


def check_prompt(prompt: str) -> None:
    """Refuse a sound prompt that asks for a voice.

    The whole reason this module exists is that a model generated speech nobody asked
    for. Asking a different model for speech on purpose would be the same defect wearing
    a hat.
    """
    lowered = prompt.lower()
    found = [word for word in FORBIDDEN if word in lowered]
    if found:
        raise SoundFailed(
            f"sound prompt asks for {', '.join(found)}: {prompt!r}. This generates the "
            "world around her, never a voice — speech comes from the voice provider so "
            "that one voice stays constant across every video."
        )


def generate_sound(
    client: httpx.Client,
    *,
    queue_root: str,
    model: str,
    video_url: str,
    prompt: str,
    duration_s: float,
    base: dict[str, Any],
    dest: Path,
    poll_interval_s: float = 5.0,
) -> Path:
    """Generate a soundtrack for one shot and download the result."""
    check_prompt(prompt)
    arguments: dict[str, Any] = {
        "video_url": video_url,
        "prompt": prompt,
        "duration": round(duration_s, 2),
        **base,
    }
    response = client.post(f"{queue_root}/{model}", json=arguments)
    if response.status_code >= 400:
        raise SoundFailed(f"submit failed {response.status_code}: {response.text[:400]}")
    submitted = response.json()
    status_url = str(submitted.get("status_url") or "")
    response_url = str(submitted.get("response_url") or "")
    if not status_url or not response_url:
        raise SoundFailed("provider accepted the job but returned no URLs to follow it")

    for _ in range(180):
        if client.get(status_url).json().get("status") in {"COMPLETED", "FAILED", "ERROR"}:
            break
        time.sleep(poll_interval_s)

    result = client.get(response_url)
    if result.status_code >= 400:
        raise SoundFailed(f"sound generation failed {result.status_code}: {result.text[:400]}")
    payload = result.json()
    url = str((payload.get("video") or payload.get("audio") or {}).get("url") or "")
    if not url:
        raise SoundFailed(f"COMPLETED with no output: {str(payload)[:400]}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(client.get(url, timeout=300.0).content)
    return dest
