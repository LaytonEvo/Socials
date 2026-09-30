"""Task 3.10 — the on-video disclosure overlay.

**CLAUDE.md: disclosure cannot be disabled.** Config decides the text and where it sits.
Nothing decides whether it appears.

The rule is enforced by construction rather than by a check someone has to remember to
call. `FinalRender` has a private marker in its constructor, so the only way to obtain
one is `apply_disclosure`, which burns the overlay in first. Everything downstream —
signing, platform cuts, the publication record — takes a `FinalRender`, so a path that
skips the overlay does not type-check and does not run.

That matters more than it sounds. A boolean flag threaded through a pipeline is one
`if` away from being wrong in a way no test notices, and `render.disclosure_applied` in
the database is a claim the application makes about itself. This makes the claim
unforgeable at the point it is made.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.config.schema import DisclosureOverlay
from app.pipeline.errors import DisclosureFailed, FfmpegMissing

#: Where the overlay may sit. A free-form position would be a way to push it off-frame.
POSITIONS: Final = frozenset({"top-left", "top-right", "bottom-left", "bottom-right"})

#: Present on every container this project builds against.
FONT: Final = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

_MAKE_KEY: Final = object()


@dataclass(frozen=True)
class FinalRender:
    """A video file that has been through the overlay pass.

    Not constructible directly: `apply_disclosure` is the only thing holding the key.
    An instance of this type IS the evidence that the overlay ran, which is why
    `render.disclosure_applied` may be set from it and from nothing else.
    """

    path: Path
    disclosure_text: str
    position: str
    _key: Any = None

    def __post_init__(self) -> None:
        if self._key is not _MAKE_KEY:
            raise DisclosureFailed(
                "FinalRender cannot be constructed directly. Call apply_disclosure() — "
                "the point of this type is that holding one proves the overlay ran, and "
                "a constructor anyone can call proves nothing."
            )


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise FfmpegMissing("ffmpeg is not on PATH; the overlay pass cannot run")


def _position_expressions(position: str, margin: str) -> tuple[str, str]:
    """ffmpeg x/y expressions for a corner, in terms of text and frame size."""
    if position not in POSITIONS:
        raise DisclosureFailed(
            f"unknown overlay position {position!r}; expected one of {sorted(POSITIONS)}"
        )
    left, top = position.endswith("left"), position.startswith("top")
    x = margin if left else f"w-tw-{margin}"
    y = margin if top else f"h-th-{margin}"
    return x, y


def drawtext_filter(overlay: DisclosureOverlay | dict[str, Any], height: int, width: int) -> str:
    """Build the drawtext filter. Separated out so it can be asserted on without ffmpeg."""
    fields = overlay if isinstance(overlay, dict) else overlay.model_dump()
    text = str(fields.get("text") or "").strip()
    if not text:
        raise DisclosureFailed(
            "the disclosure overlay has no text. Config may choose the wording; it may "
            "not choose silence."
        )
    font_size = max(12, round(height * float(fields.get("font_height_fraction", 0.03))))
    margin = str(max(8, round(min(height, width) * float(fields.get("margin_fraction", 0.025)))))
    x, y = _position_expressions(str(fields.get("position", "bottom-left")), margin)
    escaped = text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    return (
        f"drawtext=fontfile={FONT}:text='{escaped}':fontsize={font_size}:"
        f"fontcolor={fields.get('text_colour', 'white')}:"
        f"box=1:boxcolor={fields.get('box_colour', 'black@0.55')}:"
        f"boxborderw={int(fields.get('box_padding_px', 10))}:x={x}:y={y}"
    )


def probe_size(video: Path) -> tuple[int, int]:
    """Frame width and height, so the overlay scales with the frame it lands on."""
    _require_ffmpeg()
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DisclosureFailed(f"could not read {video}: {result.stderr.strip()}")
    try:
        width, height = (int(part) for part in result.stdout.strip().split("x")[:2])
    except ValueError as exc:
        raise DisclosureFailed(f"unreadable frame size for {video}: {result.stdout!r}") from exc
    return width, height


def apply_disclosure(
    source: Path, dest: Path, *, overlay: DisclosureOverlay | dict[str, Any]
) -> FinalRender:
    """Burn the disclosure into every frame and return the proof that it happened.

    The only route to a `FinalRender`. Takes no flag that skips the pass, because there
    is no circumstance in which skipping it is correct.
    """
    _require_ffmpeg()
    if not source.is_file():
        raise DisclosureFailed(f"no such video to disclose: {source}")
    width, height = probe_size(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            drawtext_filter(overlay, height, width),
            "-c:a",
            "copy",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not dest.is_file():
        raise DisclosureFailed(f"overlay pass failed on {source}: {result.stderr.strip()}")
    settled = overlay if isinstance(overlay, dict) else overlay.model_dump()
    return FinalRender(
        path=dest,
        disclosure_text=str(settled["text"]),
        position=str(settled.get("position", "bottom-left")),
        _key=_MAKE_KEY,
    )
