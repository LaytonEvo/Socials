"""Picking between takes on a measurement rather than an opinion.

The generator cannot be prompted into holding a head still — a take asked for
"completely still and upright, no tilting" returned 8.9 degrees of roll variation — and
its seed is accepted but not honoured, so the same prompt twice gives different results
with no way to ask for the good one again. Selection is the only lever left.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.takes import TakeMeasurement, steadiest


def _take(name: str, roll: float, frames: int = 20) -> TakeMeasurement:
    return TakeMeasurement(
        path=Path(name), frames_with_face=frames, head_roll_sd_deg=roll, mouth_activity=10.0
    )


def test_the_steadiest_take_wins() -> None:
    picked = steadiest([_take("a", 8.9), _take("b", 4.5), _take("c", 6.2)])
    assert picked.path.name == "b"


def test_a_take_with_too_little_face_is_not_eligible() -> None:
    """Head movement measured over two frames is not a measurement of a take."""
    picked = steadiest([_take("blind", 0.1, frames=1), _take("real", 7.0, frames=30)])
    assert picked.path.name == "real", (
        "a take with almost no detectable face scored best and should not have been "
        "eligible — its low number reflects having nothing to measure"
    )


def test_an_unmeasurable_take_is_not_eligible() -> None:
    picked = steadiest([_take("nan", float("nan")), _take("fine", 9.9)])
    assert picked.path.name == "fine"


def test_nothing_measurable_is_refused_rather_than_guessed() -> None:
    """Picking arbitrarily and calling it a choice is worse than saying so."""
    with pytest.raises(ValueError, match="no take had enough detectable face"):
        steadiest([_take("a", float("nan")), _take("b", 1.0, frames=0)])


def test_an_empty_list_is_refused() -> None:
    with pytest.raises(ValueError):
        steadiest([])


def test_usable_requires_several_frames() -> None:
    assert _take("x", 1.0, frames=2).usable is False
    assert _take("x", 1.0, frames=3).usable is True
