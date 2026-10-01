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
from PIL import ImageFont

from app.config.schema import DisclosureOverlay
from app.pipeline.captions import (
    CAPTION_HEIGHT_FRACTION,
    MAX_CUE_CHARS,
    MAX_CUE_LINES,
    MIN_CUE_SECONDS,
    USABLE_WIDTH_FRACTION,
    Band,
    CaptionsFailed,
    burn_in,
    caption_band,
    disclosure_band,
    split_into_cues,
    wrap_to_frame,
    write_srt,
)
from app.pipeline.disclosure import FONT

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
    assert cues[-1].text.endswith("Watch.")


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
    cues = split_into_cues("Hi. A considerably longer sentence than that first one was.", 6.0)
    first = next(c for c in cues if c.text.startswith("Hi"))
    rest = sum(c.duration_s for c in cues if c is not first)
    assert rest > first.duration_s


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


# --------------------------------------------- what a character budget cannot know --
def test_no_cue_is_wider_than_the_frame_it_is_drawn_on() -> None:
    """The defect that a character limit alone cannot catch.

    MAX_CUE_CHARS was 42 and the caption height 0.045, which renders 1471px wide on a 768px
    frame — nearly double it. Nothing counted characters wrongly; characters were simply the
    wrong unit. This measures against the same TrueType file ffmpeg draws with.
    """
    for width, height in ((768, 1344), (720, 1280), (1080, 1920)):
        font_px = int(height * CAPTION_HEIGHT_FRACTION)
        for cue in split_into_cues(LINE, 6.0):
            lines = wrap_to_frame(cue.text, frame_width=width, font_px=font_px)
            assert len(lines) <= MAX_CUE_LINES, (cue.text, lines)
            font = ImageFont.truetype(str(FONT), font_px)
            for line in lines:
                drawn = font.getbbox(line)[2]
                assert drawn <= width * USABLE_WIDTH_FRACTION, (
                    f"{line!r} draws {drawn}px on a {width}px frame"
                )


def test_a_word_too_wide_to_wrap_is_refused_not_truncated() -> None:
    """Silent truncation would draw it off both edges with nothing to show it happened."""
    with pytest.raises(CaptionsFailed, match="Reduce the caption height or the word"):
        wrap_to_frame("Unsplittablylongsinglewordthatcannotfit", frame_width=200, font_px=60)


# ------------------------------------------------------------- no unreadable flashes --
def test_no_cue_is_too_brief_to_read() -> None:
    """Splitting on commas produced "Right" for 0.336s and "first tee" for 0.604s."""
    for line, duration in (
        (LINE, 6.0),
        ("Right, first tee, and there is water left the whole way down. Watch.", 6.58),
        ("Thirty out, pin is middle of the green. Little pitch, let it release.", 6.0),
    ):
        cues = split_into_cues(line, duration)
        assert all(c.duration_s >= MIN_CUE_SECONDS for c in cues), [
            (c.text, round(c.duration_s, 2)) for c in cues
        ]


def test_a_long_sentence_splits_evenly_rather_than_leaving_an_orphan() -> None:
    """Greedy packing to the limit leaves a stub, and a stub becomes a flash.

    Packing "and there is water left the whole way down." greedily gave a full-length piece
    plus "down." alone. Choosing the piece count first and aiming for an even share does not.
    """
    cues = split_into_cues("And there is water left the whole way down the hole.", 4.0)
    lengths = [len(c.text) for c in cues]
    assert min(lengths) > max(lengths) / 3, lengths
