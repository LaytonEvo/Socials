"""Task 3.7 — when lip sync runs, and when it does not.

The rule is the expensive part. At $0.10/second the sync costs four times what
generating the clip did, so syncing b-roll is the most wasteful thing this pipeline can
do — and skipping a face-forward take with dialogue is worse, because a person talking
with the wrong mouth is the most recognisable tell of synthetic video.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.pipeline.lipsync import LipSyncFailed, lip_sync, should_lip_sync
from app.pipeline.voice import NarrationFailed, pad_to, video_duration

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


# ------------------------------------------------------------- the rule --
def test_a_face_forward_take_with_dialogue_is_synced() -> None:
    assert should_lip_sync(face_forward=True, has_dialogue=True).sync is True


def test_b_roll_with_dialogue_over_it_is_not_synced() -> None:
    """The line still plays; her mouth is simply not what the viewer is watching."""
    decision = should_lip_sync(face_forward=False, has_dialogue=True)
    assert decision.sync is False
    assert "b-roll" in decision.reason


def test_a_face_forward_take_with_no_dialogue_is_not_synced() -> None:
    """Nothing to sync to."""
    decision = should_lip_sync(face_forward=True, has_dialogue=False)
    assert decision.sync is False
    assert "no dialogue" in decision.reason


def test_silent_b_roll_is_not_synced() -> None:
    assert should_lip_sync(face_forward=False, has_dialogue=False).sync is False


def test_every_decision_carries_a_reason() -> None:
    """The spend has to be explainable afterwards, not just correct."""
    for face_forward in (True, False):
        for has_dialogue in (True, False):
            decision = should_lip_sync(face_forward=face_forward, has_dialogue=has_dialogue)
            assert decision.reason.strip()


# ------------------------------------------------------------- padding --
@needs_ffmpeg
def test_a_line_is_padded_to_the_length_of_its_shot(tmp_path: Path) -> None:
    """The provider refuses inputs whose durations differ much.

    2.77 seconds of speech against a 5.18 second clip was rejected outright with
    "Audio and video durations are too different", even with duration adjustment
    enabled. Padding gives the sync matching inputs.
    """
    line = tmp_path / "line.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            str(line),
        ],
        capture_output=True,
        check=True,
    )
    padded = pad_to(line, 5.0, tmp_path / "padded.mp3")
    assert video_duration(padded) == pytest.approx(5.0, abs=0.2)


@needs_ffmpeg
def test_padding_is_trailing_so_speech_still_starts_at_zero(tmp_path: Path) -> None:
    """A synced take's mouth is aligned to its own audio from the first frame.

    Leading silence would push the speech later than the mouth movement, which is the
    defect the sync exists to prevent.
    """
    line = tmp_path / "line.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1.0",
            str(line),
        ],
        capture_output=True,
        check=True,
    )
    padded = pad_to(line, 4.0, tmp_path / "padded.mp3")
    # Measure loudness of the first second; silence at the head would read far lower.
    probe = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(padded),
            "-t",
            "0.8",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "mean_volume" in probe.stderr
    volume_line = next(ln for ln in probe.stderr.splitlines() if "mean_volume" in ln)
    mean = float(volume_line.split("mean_volume:")[1].replace("dB", "").strip())
    assert mean > -50.0, "the start of the padded line is silent; padding went to the head"


def test_padding_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(NarrationFailed, match="no such audio"):
        pad_to(tmp_path / "ghost.mp3", 3.0, tmp_path / "out.mp3")


def test_provider_fetch_failure_is_retried_with_fresh_urls() -> None:
    """A provider-side download failure gets one retry, re-presigned.

    Measured on the first single-shot run: `response_url` returned 422
    `"Failed to download the file"` for an `audio_url` that fetched correctly from
    this side. The input was sound, so the job is resubmitted once — and with fresh
    signatures, because a retry that inherits an expiring one fails the same way for
    a different reason.
    """
    refreshed: list[int] = []

    def refresh() -> tuple[str, str]:
        refreshed.append(1)
        return ("https://v2", "https://a2")

    attempts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            attempts.append(json.loads(request.content))
            return httpx.Response(
                200, json={"status_url": "https://s", "response_url": "https://r"}
            )
        if request.url.path.endswith("/s") or str(request.url) == "https://s":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if str(request.url) == "https://r":
            if len(attempts) == 1:
                return httpx.Response(
                    422,
                    json={
                        "detail": [
                            {
                                "loc": ["body", "audio_url"],
                                "msg": (
                                    "Failed to download the file. "
                                    "Please check if the URL is accessible."
                                ),
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"video": {"url": "https://clip"}})
        return httpx.Response(200, content=b"synced-bytes")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        tempfile.TemporaryDirectory() as tmp,
    ):
        dest = Path(tmp) / "synced.mp4"
        out = lip_sync(
            client,
            queue_root="https://queue",
            model="m",
            video_url="https://v1",
            audio_url="https://a1",
            base={},
            dest=dest,
            poll_interval_s=0.0,
            refresh_urls=refresh,
        )
        synced_bytes = out.read_bytes()

    assert len(attempts) == 2
    assert refreshed == [1]
    assert attempts[1]["audio_url"] == "https://a2"
    assert synced_bytes == b"synced-bytes"


def test_a_rejected_input_is_not_retried() -> None:
    """Only a fetch failure earns a second paid job.

    A provider that rejects the input itself will reject it again, so resubmitting
    buys nothing and costs a second call.
    """
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            attempts.append(1)
            return httpx.Response(
                200, json={"status_url": "https://s", "response_url": "https://r"}
            )
        if str(request.url) == "https://s":
            return httpx.Response(200, json={"status": "ERROR"})
        return httpx.Response(400, json={"detail": "No speech detected in the input video"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        tempfile.TemporaryDirectory() as tmp,
        pytest.raises(LipSyncFailed, match="No speech detected"),
    ):
        lip_sync(
            client,
            queue_root="https://queue",
            model="m",
            video_url="https://v",
            audio_url="https://a",
            base={},
            dest=Path(tmp) / "out.mp4",
            poll_interval_s=0.0,
        )

    assert attempts == [1]
