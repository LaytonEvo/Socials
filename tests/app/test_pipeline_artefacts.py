"""The seam that shipped.

`spike/runs/shot1-final/keyframe.png` has a hard composite boundary across its lower
third, where an edit pasted a wedge-and-ball foreground into a master still. Every frame
of the one video the owner approved carries it. It passed screening because ADR 0011
screens a keyframe for identity and nothing else, and a pasted rectangle scores a
perfectly good identity number.

The numbers below are the real measurement, 2026-10-15, over 101 images:

    her 96 master/outfit/lighting/body stills  max 4.22
    the 5 keyframes with no visible seam       max 1.76
    shot1-final/keyframe.png                   9.83
    broll/address_strike_keyframe.png         13.74

Coverage alone was tried first and is not enough: a tree line across a real photograph of
her covers 17.8% of the width at one row, against the bad keyframe's 19.7%. What separates
them is isolation — natural structure spreads over several rows, a paste is one pixel.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.artefacts import SEAM_LIMIT, scan

HEIGHT, WIDTH = 400, 300
RNG = np.random.default_rng(0)


def textured(height: int = HEIGHT, width: int = WIDTH, *, base: float = 120.0) -> np.ndarray:
    """A plausible photograph: a smooth vertical gradient under fine grain."""
    gradient = np.linspace(base - 30, base + 30, height, dtype=np.float32)[:, None]
    return (gradient + RNG.normal(0, 6, (height, width))).astype(np.float32)


def test_a_clean_image_has_no_seam() -> None:
    reading = scan(textured())
    assert not reading.seamed
    assert reading.score < SEAM_LIMIT


def test_a_pasted_rectangle_is_found() -> None:
    """The defect itself: a block of different content dropped in with a hard edge."""
    image = textured()
    image[260:, :] = textured(HEIGHT - 260, WIDTH, base=200.0)
    reading = scan(image)
    assert reading.seamed, reading.explain()
    assert reading.axis == "horizontal"
    assert abs(reading.index - 259) <= 2, reading.explain()


def test_a_vertical_paste_is_found_too() -> None:
    image = textured()
    image[:, 180:] = textured(HEIGHT, WIDTH - 180, base=200.0).reshape(HEIGHT, WIDTH - 180)
    reading = scan(image)
    assert reading.seamed, reading.explain()
    assert reading.axis == "vertical"


def test_a_soft_natural_edge_is_not_a_seam() -> None:
    """A tree line or a horizon changes most of the width, over several rows.

    This is the case that killed the coverage-only version of the metric, so it is the
    case the test has to carry.
    """
    image = textured()
    for offset, weight in enumerate((0.2, 0.45, 0.7, 0.9, 1.0, 0.9, 0.7, 0.45, 0.2)):
        image[250 + offset, :] += 60.0 * weight
    reading = scan(image)
    assert not reading.seamed, reading.explain()


def test_an_edge_at_the_frame_border_is_not_a_seam() -> None:
    """One master still scored 0.609 on raw coverage at its second-to-last row and is
    perfectly clean. A border is a border."""
    image = textured()
    image[-2:, :] = 255.0
    assert not scan(image).seamed


def test_the_explanation_names_the_line_to_look_at() -> None:
    image = textured()
    image[260:, :] = textured(HEIGHT - 260, WIDTH, base=200.0)
    text = scan(image).explain()
    assert "row" in text and "jumps at once" in text


def test_a_colour_image_is_read_as_greyscale(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PIL import Image

    rgb = np.dstack([textured()] * 3).astype(np.uint8)
    rgb[260:, :, :] = 220
    path = tmp_path / "pasted.png"
    Image.fromarray(rgb, mode="RGB").save(path)
    assert scan(path).seamed


def test_a_non_image_array_is_refused() -> None:
    with pytest.raises(ValueError, match="2-D greyscale"):
        scan(np.zeros((4, 4, 3)))
