"""Task 3.10's rule: disclosure cannot be disabled.

Most of these test what the code REFUSES to do. A disclosure overlay that works is
unremarkable; one that cannot be skipped is the requirement, so the interesting cases
are the ways a caller in a hurry might try to get a finished video without it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import load_all
from app.pipeline.disclosure import (
    POSITIONS,
    FinalRender,
    apply_disclosure,
    drawtext_filter,
    probe_size,
)
from app.pipeline.errors import DisclosureFailed

REPO = Path(__file__).resolve().parent.parent.parent
OVERLAY = load_all(REPO / "config").persona.persona.disclosure.overlay.model_dump()

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    """Two seconds of test pattern with a tone, so the pass has real pixels to alter."""
    dest = tmp_path / "source.mp4"
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
            "testsrc=size=640x360:rate=12:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )
    return dest


# ------------------------------------------------------ the rule itself --
def test_a_final_render_cannot_be_constructed_directly() -> None:
    """The whole design rests on this.

    If `FinalRender` were an ordinary dataclass, any caller could declare a video
    disclosed without running the pass, and `render.disclosure_applied` would become a
    claim the application makes about itself rather than evidence.
    """
    with pytest.raises(DisclosureFailed, match="cannot be constructed directly"):
        FinalRender(
            path=Path("anything.mp4"), disclosure_text="AI-generated", position="bottom-left"
        )


def test_the_overlay_has_no_off_switch() -> None:
    """There is no parameter, anywhere in the signature, that skips the pass."""
    import inspect

    parameters = set(inspect.signature(apply_disclosure).parameters)
    assert parameters == {"source", "dest", "overlay"}
    forbidden = {"skip", "enabled", "disable", "apply", "dry_run", "overlay_enabled"}
    assert not (parameters & forbidden)


def test_empty_disclosure_text_is_refused() -> None:
    """Config may choose the wording. It may not choose silence."""
    for text in ("", "   ", None):
        with pytest.raises(DisclosureFailed, match="may not choose silence"):
            drawtext_filter({**OVERLAY, "text": text}, 360, 640)


def test_an_unknown_position_is_refused() -> None:
    """A free-form position is a way to push the overlay off-frame."""
    with pytest.raises(DisclosureFailed, match="unknown overlay position"):
        drawtext_filter({**OVERLAY, "position": "off-screen"}, 360, 640)


@pytest.mark.parametrize("position", sorted(POSITIONS))
def test_every_allowed_position_stays_inside_the_frame(position: str) -> None:
    """Each corner expression keeps the text box within the frame bounds."""
    built = drawtext_filter({**OVERLAY, "position": position}, 360, 640)
    assert "x=" in built and "y=" in built
    # Right and bottom placements must subtract the text size, or the box runs off.
    if position.endswith("right"):
        assert "w-tw-" in built
    if position.startswith("bottom"):
        assert "h-th-" in built


# ---------------------------------------------------------- it actually runs --
@needs_ffmpeg
def test_the_pass_changes_the_pixels(clip: Path, tmp_path: Path) -> None:
    """A filter that silently no-ops would satisfy every test above."""
    dest = tmp_path / "disclosed.mp4"
    final = apply_disclosure(clip, dest, overlay=OVERLAY)
    assert final.path.is_file()
    assert final.disclosure_text == OVERLAY["text"]

    def first_frame(video: Path, out: Path) -> bytes:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(out),
            ],
            capture_output=True,
            check=True,
        )
        return out.read_bytes()

    before = first_frame(clip, tmp_path / "before.png")
    after = first_frame(dest, tmp_path / "after.png")
    assert before != after, "the overlay pass produced an identical frame"


@needs_ffmpeg
def test_the_overlay_scales_with_the_frame(clip: Path) -> None:
    """A fixed pixel size would vanish on a large frame and swamp a small one."""
    width, height = probe_size(clip)
    small = drawtext_filter(OVERLAY, height, width)
    large = drawtext_filter(OVERLAY, height * 4, width * 4)
    assert small != large


@needs_ffmpeg
def test_disclosing_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DisclosureFailed, match="no such video"):
        apply_disclosure(tmp_path / "nope.mp4", tmp_path / "out.mp4", overlay=OVERLAY)
