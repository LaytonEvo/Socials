"""Worst-frame contact sheets.

BUILD_PLAN task 1.7 asks for "a contact sheet of worst frames". Its real job is
not illustration -- it is the check on the instrument. A human looks at the
worst frame of every clip the scorer passed and asks whether they agree. If the
scorer passes clips the eye rejects, the scorer is the finding, and task 3.4's
auto-reject design has to change before it is built.

So the sheet is laid out to make disagreement easy to spot: every tile carries
its score and its verdict, and passed and failed clips are not separated.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from .score import ClipScore

TILE = 192
PAD = 8
#: Room reserved on the right of the caption for the face-lost flag.
FLAG_W = 64
CAPTION_H = 34
PASS_RGB = (46, 125, 50)
FAIL_RGB = (183, 28, 28)
MISSING_RGB = (66, 66, 66)
BG_RGB = (24, 24, 27)
TEXT_RGB = (240, 240, 240)


def _tile_for(score: ClipScore) -> Image.Image:
    tile = Image.new("RGB", (TILE, TILE + CAPTION_H), BG_RGB)
    src = score.worst_frame_source
    if src and Path(src).exists():
        with Image.open(src) as img:
            thumb = img.convert("RGB").resize((TILE, TILE), Image.Resampling.LANCZOS)
        tile.paste(thumb, (0, 0))
    else:
        draw = ImageDraw.Draw(tile)
        draw.rectangle([0, 0, TILE, TILE], fill=MISSING_RGB)
        draw.text((10, TILE // 2 - 6), "no usable frame", fill=TEXT_RGB)

    draw = ImageDraw.Draw(tile)
    colour = PASS_RGB if score.passed else FAIL_RGB
    draw.rectangle([0, TILE, TILE, TILE + CAPTION_H], fill=colour)
    verdict = "PASS" if score.passed else "FAIL"
    lo = score.identity_score_min
    score_text = f"{lo:.3f}" if lo is not None else "--"
    draw.text((6, TILE + 4), f"{verdict}  min {score_text}", fill=TEXT_RGB)

    # The face-lost flag is drawn first and the label is then truncated to
    # whatever room is left. Sizing the label independently let the two collide
    # on exactly the clips that most need reading -- the ones where the face
    # disappeared. Flags matter more than the tail of a name, so they win.
    flag = ""
    if score.no_face_frames or score.multi_face_frames:
        flag = f"!{score.no_face_frames}nf/{score.multi_face_frames}mf"
        draw.text((TILE - FLAG_W, TILE + 18), flag, fill=TEXT_RGB)

    room = TILE - 12 - (FLAG_W if flag else 0)
    draw.text((6, TILE + 18), _fit(caption_for(score), room, draw), fill=TEXT_RGB)
    return tile


def caption_for(score: ClipScore) -> str:
    """The identifying part of a clip's name.

    Every tile in a matrix run shares a ``matrix-NNN-`` prefix, so printing it
    spends a third of the caption saying nothing and truncates away the
    condition, which is the only part a reviewer is actually looking for.
    """
    return re.sub(r"^matrix-\d+-", "", score.label)


def _fit(text: str, width_px: int, draw: ImageDraw.ImageDraw) -> str:
    """Trim ``text`` to fit ``width_px``, measured rather than guessed."""
    if draw.textlength(text) <= width_px:
        return text
    while text and draw.textlength(text + "…") > width_px:
        text = text[:-1]
    return text + "…"


def build_contact_sheet(scores: list[ClipScore], dest: Path, columns: int = 6) -> Path:
    """Grid of every clip's worst frame, in the order given."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not scores:
        Image.new("RGB", (TILE, TILE), BG_RGB).save(dest)
        return dest

    columns = max(1, min(columns, len(scores)))
    rows = (len(scores) + columns - 1) // columns
    width = columns * TILE + (columns + 1) * PAD
    height = rows * (TILE + CAPTION_H) + (rows + 1) * PAD
    sheet = Image.new("RGB", (width, height), BG_RGB)

    for i, score in enumerate(scores):
        r, c = divmod(i, columns)
        x = PAD + c * (TILE + PAD)
        y = PAD + r * (TILE + CAPTION_H + PAD)
        sheet.paste(_tile_for(score), (x, y))

    sheet.save(dest)
    return dest


def worst_first(scores: list[ClipScore]) -> list[ClipScore]:
    """Order by lowest min score, with no-face clips first.

    Those are the ones a reviewer should look at, so they go at the top of the
    sheet rather than being buried in a grid ordered by generation sequence.
    """
    return sorted(
        scores,
        key=lambda s: (
            s.identity_score_min is not None,
            s.identity_score_min if s.identity_score_min is not None else 0.0,
        ),
    )
