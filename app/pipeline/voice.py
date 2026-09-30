"""Task 3.6 — the voice layer.

Two rules from `BUILD_PLAN`, and they pull in different directions:

- the voice must be a **designed synthetic voice**, never cloned from a real person
  without a contract;
- and it must be the **same voice every time**, because a recurring personality whose
  voice drifts is as broken as one whose face does (ADR 0005).

The second is why speech is synthesised by a dedicated provider rather than taken from
the video model, whose native audio is well synced and a different person each take.

The first is not satisfied yet. `config/persona.yaml` carries
`voice.provenance_checked: false` — nobody has confirmed with the provider whether this
voice id is designed or cloned from a library recording of a real speaker. That blocks
PUBLISHING, not building, so this module synthesises freely and
`require_publishable_voice` is what refuses at the boundary that matters.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.pipeline.errors import PipelineError


class VoiceProvenanceUnverified(PipelineError):
    """The voice may be cloned from a real person, and nobody has checked.

    Deliberately not catchable-and-ignorable in the publishing path: task 3.6's rule is
    about someone's voice, and "we were fairly sure" is not a defence.
    """


class NarrationFailed(PipelineError):
    """Speech was synthesised but could not be laid onto the video."""


@dataclass(frozen=True)
class VoiceLine:
    """One spoken line, and where it belongs in the edit."""

    text: str
    audio: Path
    at_s: float
    voice_id: str


def require_publishable_voice(voice: Any) -> None:
    """Refuse to treat a render as publishable while the voice provenance is unknown.

    Called at the publishing boundary rather than at synthesis, because generating
    speech to listen to is not the thing task 3.6 restricts — putting it out into the
    world under a persona is.
    """
    checked = bool(getattr(voice, "provenance_checked", False))
    if not checked:
        raise VoiceProvenanceUnverified(
            f"voice {getattr(voice, 'voice_id', '?')} has provenance_checked=false. "
            "BUILD_PLAN task 3.6 requires a DESIGNED synthetic voice, never one cloned "
            "from a real person without a contract. Confirm with the provider and set "
            "persona.voice.provenance_checked before anything using this voice is "
            "published."
        )


def video_duration(video: Path) -> float:
    """The picture's length, which is what a narrated render should be."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise NarrationFailed(f"could not read duration of {video}: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise NarrationFailed(f"unreadable duration for {video}: {result.stdout!r}") from exc


def pad_to(audio: Path, seconds: float, dest: Path) -> Path:
    """Pad a spoken line with trailing silence until it is `seconds` long.

    The lip-sync provider refuses a take whose audio and video lengths are "too
    different" — 2.77 seconds of speech against a 5.18 second clip was enough to be
    rejected, even with duration adjustment enabled. Padding makes the line as long as
    the shot it belongs to, so the sync has matching inputs and the mouth simply closes
    once she stops talking.

    Trailing, never leading: the speech must still begin at zero, because a synced
    take's mouth is aligned to its own audio from the first frame.
    """
    _require_ffmpeg()
    if not audio.is_file():
        raise NarrationFailed(f"no such audio to pad: {audio}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(audio),
            "-af",
            f"apad=whole_dur={seconds:.3f}",
            "-t",
            f"{seconds:.3f}",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not dest.is_file():
        raise NarrationFailed(f"could not pad {audio}: {result.stderr.strip()[:300]}")
    return dest


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise NarrationFailed("ffmpeg is not on PATH; narration cannot be laid down")


def narrate(video: Path, lines: list[VoiceLine], dest: Path) -> Path:
    """Lay the voice lines onto a silent video at their offsets.

    Takes a video with no audio and returns one with a single spoken track. Each line is
    delayed to its cut offset rather than concatenated, so a line shorter than its shot
    leaves silence instead of dragging everything after it out of sync.
    """
    # Argument mistakes first, then the filesystem. An empty line list is a caller
    # error whether or not the video exists, and reporting the missing file instead
    # sends the reader looking in the wrong place.
    if not lines:
        raise NarrationFailed("narrate() was given no lines; use the silent render instead")
    _require_ffmpeg()
    if not video.is_file():
        raise NarrationFailed(f"no such video: {video}")
    for line in lines:
        if not line.audio.is_file():
            raise NarrationFailed(f"missing audio for {line.text!r}: {line.audio}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(video)]
    for line in lines:
        args += ["-i", str(line.audio)]

    delays = "".join(
        f"[{i + 1}:a]adelay={int(line.at_s * 1000)}|{int(line.at_s * 1000)}[d{i}];"
        for i, line in enumerate(lines)
    )
    mixed = "".join(f"[d{i}]" for i in range(len(lines)))
    filters = f"{delays}{mixed}amix=inputs={len(lines)}:normalize=0[a]"

    # NOT `-shortest`. The spoken lines finish before the picture does — the normal
    # case, since dialogue rarely fills every second of every shot — and `-shortest`
    # cuts the VIDEO down to the audio. It silently removed the last 2.6 seconds of the
    # first narrated piece, including part of the swing.
    #
    # `-t` pins the output to the picture's own length instead: audio that ends early
    # leaves silence, and audio that overruns is trimmed rather than extending the cut.
    args += [
        "-filter_complex",
        filters,
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        f"{video_duration(video):.3f}",
        str(dest),
    ]

    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not dest.is_file():
        raise NarrationFailed(
            f"could not lay narration onto {video}: {result.stderr.strip()[:400]}"
        )
    return dest
