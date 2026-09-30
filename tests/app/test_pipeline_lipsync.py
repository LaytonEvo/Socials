"""Task 3.7 — when lip sync runs, and when it does not.

The rule is the expensive part. At $0.10/second the sync costs four times what
generating the clip did, so syncing b-roll is the most wasteful thing this pipeline can
do — and skipping a face-forward take with dialogue is worse, because a person talking
with the wrong mouth is the most recognisable tell of synthetic video.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.pipeline.lipsync import should_lip_sync
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
