"""Task 3.9 — captions, burned in and as a sidecar.

Shorts are watched muted, so a piece without captions is a piece most viewers never hear.
`BUILD_PLAN` asks for both forms: burned-in for the platform, SRT alongside for anything
that wants real text.

**The part that is not obvious: captions can switch the disclosure off.** The disclosure
overlay is a non-negotiable — every final render carries it — but "carries it" means
*visible*, and a caption box painted over it satisfies the letter while destroying the
point. The overlay sits bottom-left by default and a caption's natural home on a vertical
video is the lower centre, so the two collide by default rather than by accident. So the
geometry is computed and checked, and `burn_in` refuses rather than producing a render whose
disclosure is underneath a caption.

**What this does not do: real speech alignment.** Cue timings are apportioned by character
count, which is a proxy for how long a phrase takes to say and not a measurement of it.
Over a six-second line the drift is small; over a long one it would be visible. Word-level
timestamps would need a different TTS endpoint, so until that exists the acceptance gate
reports caption sync as something a human must check, in the same breath as lip sync.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config.schema import DisclosureOverlay
from app.pipeline.disclosure import FONT
from app.pipeline.errors import PipelineError

#: Where captions sit, as a fraction of frame height — the baseline of the block.
#: Lower-centre is where a Shorts viewer's eye already is, but not so low that it meets the
#: disclosure band.
CAPTION_CENTRE_FRACTION: float = 0.74

#: Caption text height as a fraction of frame height. Larger than the disclosure's 0.030,
#: because a caption is meant to be read and the disclosure only to be legible.
CAPTION_HEIGHT_FRACTION: float = 0.045

#: Longest a single cue may be. Beyond this a line wraps or runs off a phone screen.
MAX_CUE_CHARS: int = 42


class CaptionsFailed(PipelineError):
    """The captions could not be produced, or would have hidden the disclosure."""


@dataclass(frozen=True)
class Cue:
    """One caption, with the seconds it covers."""

    text: str
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def split_into_cues(line: str, duration_s: float) -> list[Cue]:
    """Break a spoken line into cues and apportion the time between them.

    Sentence boundaries first, because that is where a speaker pauses and therefore where a
    caption change is invisible. Only when a sentence is still too long to read at a glance
    is it broken on a comma, and then on words.

    Time is apportioned by character count. That is a proxy, not a measurement — see the
    module docstring.
    """
    if duration_s <= 0:
        raise CaptionsFailed(f"cannot time captions across {duration_s}s")
    text = " ".join(line.split())
    if not text:
        raise CaptionsFailed("no dialogue to caption")

    pieces: list[str] = []
    for sentence in [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]:
        if len(sentence) <= MAX_CUE_CHARS:
            pieces.append(sentence)
            continue
        # Too long to read at a glance: break on commas, then pack words up to the limit.
        for chunk in [c.strip() for c in sentence.split(",") if c.strip()]:
            if len(chunk) <= MAX_CUE_CHARS:
                pieces.append(chunk)
                continue
            current = ""
            for word in chunk.split():
                candidate = f"{current} {word}".strip()
                if len(candidate) > MAX_CUE_CHARS and current:
                    pieces.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                pieces.append(current)

    total = sum(len(p) for p in pieces)
    cues: list[Cue] = []
    at = 0.0
    for index, piece in enumerate(pieces):
        share = duration_s * len(piece) / total
        # The last cue ends exactly on the duration rather than on accumulated rounding.
        end = duration_s if index == len(pieces) - 1 else at + share
        cues.append(Cue(piece, at, end))
        at = end
    return cues


def _timestamp(seconds: float) -> str:
    whole = int(seconds)
    ms = round((seconds - whole) * 1000)
    if ms == 1000:  # rounding can carry
        whole, ms = whole + 1, 0
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d},{ms:03d}"


def write_srt(cues: list[Cue], dest: Path) -> Path:
    """The sidecar. Plain SRT, which every platform and editor reads."""
    if not cues:
        raise CaptionsFailed("no cues to write")
    blocks = [
        f"{index}\n{_timestamp(cue.start_s)} --> {_timestamp(cue.end_s)}\n{cue.text}\n"
        for index, cue in enumerate(cues, start=1)
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(blocks), encoding="utf-8")
    return dest


@dataclass(frozen=True)
class Band:
    """A horizontal strip of the frame, as fractions of height."""

    top: float
    bottom: float

    def overlaps(self, other: Band) -> bool:
        return self.top < other.bottom and other.top < self.bottom


def disclosure_band(overlay: DisclosureOverlay) -> Band:
    """Which horizontal strip the disclosure occupies.

    Horizontal only. A caption is centred and full width, so a vertical strip tells you
    nothing: if the caption's rows and the disclosure's rows overlap at all, the caption
    can cover it, whichever side the disclosure sits on.
    """
    height = float(overlay.font_height_fraction)
    margin = float(overlay.margin_fraction)
    # Box padding is specified in pixels against an unknown frame height; a frame could be
    # anywhere from 768 to 1920 tall, so the smaller assumption makes the band WIDER in
    # fractional terms, which is the cautious direction for a collision test.
    padding = float(overlay.box_padding_px) / 768.0
    if overlay.position.startswith("top"):
        return Band(top=margin - padding, bottom=margin + height + padding)
    return Band(top=1.0 - margin - height - padding, bottom=1.0 - margin + padding)


def caption_band(
    centre_fraction: float = CAPTION_CENTRE_FRACTION,
    height_fraction: float = CAPTION_HEIGHT_FRACTION,
) -> Band:
    """Which strip the captions occupy, allowing two lines plus padding."""
    half = height_fraction  # one line above and below the centre, plus breathing room
    return Band(top=centre_fraction - half, bottom=centre_fraction + half)


def burn_in(
    video: Path,
    cues: list[Cue],
    dest: Path,
    *,
    overlay: DisclosureOverlay,
    centre_fraction: float = CAPTION_CENTRE_FRACTION,
    height_fraction: float = CAPTION_HEIGHT_FRACTION,
) -> Path:
    """Burn the cues into the picture, refusing if they would sit over the disclosure.

    The refusal is the point. Every final render must carry a visible disclosure, and a
    caption box painted across it leaves the overlay in the file while removing it from the
    viewer's experience — which is the rule defeated rather than kept.
    """
    if not cues:
        raise CaptionsFailed("no cues to burn in")

    captions = caption_band(centre_fraction, height_fraction)
    disclosure = disclosure_band(overlay)
    if captions.overlaps(disclosure):
        raise CaptionsFailed(
            f"captions would occupy {captions.top:.3f}-{captions.bottom:.3f} of frame height "
            f"and the {overlay.position} disclosure occupies "
            f"{disclosure.top:.3f}-{disclosure.bottom:.3f}. A caption over the disclosure "
            f"leaves it in the file and takes it away from the viewer, which is the rule "
            f"defeated rather than kept. Move the captions or the overlay."
        )

    filters = []
    for cue in cues:
        # drawtext reads a colon as a field separator and a single quote as the end of the
        # text, so both have to go. The apostrophe is written by codepoint rather than as a
        # literal, which keeps ambiguous characters out of the source.
        text = cue.text.replace("\\", "\\\\").replace(":", r"\:").replace("'", "\u2019")
        filters.append(
            f"drawtext=fontfile={FONT}:text='{text}'"
            f":fontsize=h*{height_fraction}"
            f":fontcolor=white:borderw=3:bordercolor=black@0.85"
            f":x=(w-text_w)/2:y=h*{centre_fraction}-text_h/2"
            f":enable='between(t,{cue.start_s:.3f},{cue.end_s:.3f})'"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            ",".join(filters),
            # Audio copied rather than re-encoded: the voice has already been through the
            # sync provider and a second encode buys nothing but generation loss.
            "-c:a",
            "copy",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise CaptionsFailed(f"ffmpeg failed burning captions: {completed.stderr[:400]}")
    return dest
