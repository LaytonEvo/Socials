"""Task 3.9 — captions, and the one way they can break a non-negotiable.

Shorts are watched muted, so captions are not decoration. But the disclosure overlay is a
non-negotiable and "carries it" has to mean visible: a caption box painted over the
overlay leaves it in the file and takes it away from the viewer. The overlay's default
home is bottom-left and a caption's natural home on a vertical video is the lower centre,
so these collide by default rather than by accident.
"""

from __future__ import annotations

import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

from app.config.schema import DisclosureOverlay
from app.pipeline.captions import (
    MAX_CUE_CHARS,
    Band,
    CaptionsFailed,
    burn_in,
    caption_band,
    disclosure_band,
    split_into_cues,
    write_srt,
)

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is not installed",
)

LINE = "Thirty yards, flag right in the middle. Ball back, hands forward, let it roll out. Watch."


def _overlay(position: str = "bottom-left") -> DisclosureOverlay:
    return DisclosureOverlay(
        text="AI-generated",
        position=position,
        font_height_fraction=0.030,
        margin_fraction=0.025,
        text_colour="white",
        box_colour="black@0.55",
        box_padding_px=10,
    )


# ------------------------------------------------------------------- cueing --
def test_the_line_breaks_on_sentences_first() -> None:
    """Sentence ends are where a speaker pauses, so a caption change there is invisible."""
    cues = split_into_cues(LINE, 6.0)
    assert len(cues) >= 3
    assert cues[0].text.startswith("Thirty yards")
    assert cues[-1].text == "Watch."


def test_no_cue_is_too_long_to_read_at_a_glance() -> None:
    cues = split_into_cues(LINE, 6.0)
    assert all(len(c.text) <= MAX_CUE_CHARS for c in cues), [c.text for c in cues]


def test_the_cues_cover_the_whole_line_without_a_gap_or_an_overrun() -> None:
    """The last cue must land exactly on the duration, not on accumulated rounding."""
    cues = split_into_cues(LINE, 6.0)
    assert cues[0].start_s == 0.0
    assert cues[-1].end_s == pytest.approx(6.0)
    for earlier, later in pairwise(cues):
        assert earlier.end_s == pytest.approx(later.start_s)


def test_longer_phrases_get_more_time() -> None:
    """Apportioned by characters — a proxy for speaking time, not a measurement of it."""
    cues = split_into_cues("Short. A considerably longer sentence than the first one.", 6.0)
    assert cues[1].duration_s > cues[0].duration_s


def test_an_empty_line_is_refused() -> None:
    with pytest.raises(CaptionsFailed, match="no dialogue"):
        split_into_cues("   ", 6.0)


def test_a_zero_duration_is_refused() -> None:
    with pytest.raises(CaptionsFailed, match="cannot time captions"):
        split_into_cues(LINE, 0.0)


# ---------------------------------------------------------------------- srt --
def test_the_sidecar_is_valid_srt(tmp_path: Path) -> None:
    path = write_srt(split_into_cues(LINE, 6.0), tmp_path / "line.srt")
    body = path.read_text(encoding="utf-8")
    assert body.startswith("1\n00:00:00,000 --> ")
    assert "-->" in body
    assert "Watch." in body


# ----------------------------------------------------- the collision guard --
def test_captions_do_not_overlap_the_default_bottom_disclosure() -> None:
    """The configured geometry must actually be safe, not merely checked."""
    assert not caption_band().overlaps(disclosure_band(_overlay("bottom-left")))


def test_captions_do_not_overlap_a_top_disclosure() -> None:
    assert not caption_band().overlaps(disclosure_band(_overlay("top-right")))


def test_a_caption_placed_over_the_disclosure_is_refused(tmp_path: Path) -> None:
    """Pushed down to where a Shorts caption would naturally sit, it collides."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"not really a video")
    with pytest.raises(CaptionsFailed, match="defeated rather than kept"):
        burn_in(
            video,
            split_into_cues(LINE, 6.0),
            tmp_path / "out.mp4",
            overlay=_overlay("bottom-left"),
            centre_fraction=0.95,
        )


def test_the_band_overlap_test_is_symmetric() -> None:
    assert Band(0.1, 0.3).overlaps(Band(0.2, 0.4))
    assert Band(0.2, 0.4).overlaps(Band(0.1, 0.3))
    assert not Band(0.1, 0.2).overlaps(Band(0.3, 0.4))
    assert not Band(0.3, 0.4).overlaps(Band(0.1, 0.2))


def test_touching_bands_do_not_count_as_overlapping() -> None:
    """Adjacent is not overlapping, or nothing could ever be placed."""
    assert not Band(0.1, 0.2).overlaps(Band(0.2, 0.3))


def test_the_disclosure_band_is_measured_cautiously() -> None:
    """Padding is in pixels against an unknown frame height.

    Assuming the smaller frame makes the band wider in fractional terms, which is the
    cautious direction for a collision test: it can refuse a layout that would have been
    fine, and never accept one that would have covered the overlay.
    """
    band = disclosure_band(_overlay("bottom-left"))
    assert band.bottom > 1.0 - 0.025  # padding pushes past the margin
    assert band.top < 1.0 - 0.025 - 0.030


# ------------------------------------------------------------------- burn in --
@needs_ffmpeg
def test_captions_burn_into_the_picture_and_keep_the_audio(tmp_path: Path) -> None:
    source = tmp_path / "src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=360x640:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    out = burn_in(
        source,
        split_into_cues("Hello there. Second cue here.", 3.0),
        tmp_path / "out.mp4",
        overlay=_overlay(),
    )
    streams = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "video" in streams
    assert "audio" in streams, "the voice must survive the caption pass"


@needs_ffmpeg
def test_an_apostrophe_does_not_break_the_filter(tmp_path: Path) -> None:
    """ffmpeg's drawtext treats quotes and colons as syntax, and golf talk has both."""
    source = tmp_path / "src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=360x640:d=2",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    out = burn_in(
        source,
        split_into_cues("Pin's middle: don't blink.", 2.0),
        tmp_path / "out.mp4",
        overlay=_overlay(),
    )
    assert out.is_file() and out.stat().st_size > 0
