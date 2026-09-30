"""Task 3.6 — the voice layer.

Two things under test: that narration does not damage the picture, and that the
provenance rule is refused at the publishing boundary rather than trusted to be
remembered.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import load_all
from app.pipeline.voice import (
    NarrationFailed,
    VoiceLine,
    VoiceProvenanceUnverified,
    narrate,
    require_publishable_voice,
    video_duration,
)

REPO = Path(__file__).resolve().parent.parent.parent

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _silent_video(dest: Path, seconds: float) -> Path:
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
            f"color=c=blue:size=320x240:rate=12:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )
    return dest


def _tone(dest: Path, seconds: float) -> Path:
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
            f"sine=frequency=440:duration={seconds}",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )
    return dest


# ------------------------------------------------------------ provenance --
def test_an_unverified_voice_is_refused_at_the_publishing_boundary() -> None:
    """Task 3.6: a DESIGNED synthetic voice, never one cloned from a real person.

    The configured voice has `provenance_checked: false` — nobody has confirmed with the
    provider which it is. Building with it is fine; publishing is not, and the refusal
    names what has to happen rather than just failing.
    """
    voice = load_all(REPO / "config").persona.persona.voice
    with pytest.raises(VoiceProvenanceUnverified, match="DESIGNED synthetic voice"):
        require_publishable_voice(voice)


def test_a_verified_voice_passes() -> None:
    """The gate opens once someone has actually checked."""

    class Checked:
        voice_id = "some-id"
        provenance_checked = True

    require_publishable_voice(Checked())


# -------------------------------------------------------------- narration --
@needs_ffmpeg
def test_narration_does_not_shorten_the_picture(tmp_path: Path) -> None:
    """The bug this pins cost 2.6 seconds of the first narrated piece.

    `-shortest` makes the output as short as the shortest input. Dialogue almost never
    fills every second of every shot, so the audio ends first and the VIDEO gets cut —
    silently, with a file that plays perfectly and is simply missing its ending.
    """
    video = _silent_video(tmp_path / "picture.mp4", 6.0)
    line = _tone(tmp_path / "line.mp3", 1.0)

    out = narrate(video, [VoiceLine("hello", line, 0.5, "v1")], tmp_path / "spoken.mp4")

    assert video_duration(out) == pytest.approx(video_duration(video), abs=0.25), (
        "narration changed the length of the picture"
    )


@needs_ffmpeg
def test_audio_that_overruns_is_trimmed_not_allowed_to_extend_the_cut(tmp_path: Path) -> None:
    """The other direction: a long line must not stretch the render past its last frame."""
    video = _silent_video(tmp_path / "picture.mp4", 2.0)
    line = _tone(tmp_path / "long.mp3", 8.0)

    out = narrate(video, [VoiceLine("waffle", line, 0.0, "v1")], tmp_path / "spoken.mp4")

    assert video_duration(out) == pytest.approx(2.0, abs=0.25)


@needs_ffmpeg
def test_narration_adds_an_audio_track_to_a_silent_render(tmp_path: Path) -> None:
    video = _silent_video(tmp_path / "picture.mp4", 3.0)
    line = _tone(tmp_path / "line.mp3", 1.0)
    out = narrate(video, [VoiceLine("hello", line, 0.5, "v1")], tmp_path / "spoken.mp4")
    streams = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert streams.stdout.strip() != ""


@needs_ffmpeg
def test_lines_are_placed_at_their_offsets_not_concatenated(tmp_path: Path) -> None:
    """A line shorter than its shot must leave silence, not drag the rest forward."""
    video = _silent_video(tmp_path / "picture.mp4", 10.0)
    a = _tone(tmp_path / "a.mp3", 1.0)
    b = _tone(tmp_path / "b.mp3", 1.0)
    out = narrate(
        video,
        [VoiceLine("one", a, 0.0, "v1"), VoiceLine("two", b, 7.0, "v1")],
        tmp_path / "spoken.mp4",
    )
    assert video_duration(out) == pytest.approx(10.0, abs=0.25)


def test_narrating_with_no_lines_is_refused(tmp_path: Path) -> None:
    """An empty list means someone meant the silent render and called the wrong thing."""
    with pytest.raises(NarrationFailed, match="no lines"):
        narrate(tmp_path / "anything.mp4", [], tmp_path / "out.mp4")


@needs_ffmpeg
def test_a_missing_audio_file_is_named(tmp_path: Path) -> None:
    video = _silent_video(tmp_path / "picture.mp4", 2.0)
    with pytest.raises(NarrationFailed, match="missing audio"):
        narrate(video, [VoiceLine("hi", tmp_path / "ghost.mp3", 0.0, "v1")], tmp_path / "o.mp4")


# ------------------------------------------------------------ sound effects --
def test_a_sound_prompt_cannot_ask_for_a_voice() -> None:
    """The reason this module exists is a model that generated speech nobody asked for.

    Asking a different model for speech on purpose would be the same defect wearing a
    hat: an invented voice back in the render through another door, bypassing the one
    voice that is supposed to stay constant across every video (ADR 0005).
    """
    from app.pipeline.sfx import SoundFailed, check_prompt

    for prompt in (
        "a woman speaking over golf course ambience",
        "crowd noise and commentary voice",
        "birdsong with distant talking",
        "upbeat music with singing",
    ):
        with pytest.raises(SoundFailed, match="never a voice"):
            check_prompt(prompt)


def test_a_sound_prompt_about_the_world_is_allowed() -> None:
    from app.pipeline.sfx import check_prompt

    check_prompt("a golf club swishing then a sharp crack as it strikes the ball")
    check_prompt("quiet course ambience, footsteps on grass, distant birdsong")
