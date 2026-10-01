"""Picking between takes on a measurement rather than an opinion.

The generator cannot be prompted into holding a head still — a take asked for
"completely still and upright, no tilting" returned 8.9 degrees of roll variation — and
its seed is accepted but not honoured, so the same prompt twice gives different results
with no way to ask for the good one again. Selection is the only lever left.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.takes import TakeMeasurement, best_take, steadiest


def _take(name: str, roll: float, frames: int = 20, sampled: int | None = None) -> TakeMeasurement:
    return TakeMeasurement(
        path=Path(name),
        frames_with_face=frames,
        frames_sampled=sampled if sampled is not None else frames,
        head_roll_sd_deg=roll,
        mouth_activity=10.0,
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


def test_a_thinly_covered_take_does_not_win_on_a_flattered_score() -> None:
    """The first live run's mistake, as a test.

    take_1 measured 3.43 degrees of roll over 14 of 37 frames and beat take_3's 4.60
    over 37 of 37. The lower number came from the detector losing the face, not from a
    steadier head, and the take it chose was refused by the sync provider afterwards.
    """
    picked = steadiest(
        [
            _take("take_1", 3.43, frames=14, sampled=37),
            _take("take_3", 4.60, frames=37, sampled=37),
        ]
    )
    assert picked.path.name == "take_3", (
        "a take seen in 38% of its frames won on a score that coverage does not support"
    )


def test_no_adequately_covered_take_is_refused_rather_than_picked() -> None:
    """Shooting again costs $0.0625; syncing the wrong take costs $0.50."""
    with pytest.raises(ValueError, match="shoot more takes"):
        steadiest(
            [
                _take("a", 2.0, frames=10, sampled=40),
                _take("b", 3.0, frames=12, sampled=40),
            ]
        )


def test_coverage_is_a_ratio_not_a_count() -> None:
    """14 frames is most of a short take and a third of a longer one."""
    assert _take("short", 4.0, frames=14, sampled=16).coverage > 0.6
    assert _take("long", 4.0, frames=14, sampled=37).coverage < 0.6


# ------------------------------------------------- selection that agrees with the gate --
def _scored(
    name: str,
    roll: float,
    scores: tuple[float, ...],
    sampled: int = 10,
) -> TakeMeasurement:
    return TakeMeasurement(
        path=Path(name),
        frames_with_face=len(scores),
        frames_sampled=sampled,
        head_roll_sd_deg=roll,
        mouth_activity=10.0,
        identity_scores=scores,
    )


def test_identity_is_a_constraint_and_roll_only_a_preference() -> None:
    """Run 5 of the pass-rate battery, as a test.

    Its take was chosen on head roll alone — 2.78 degrees, steadiest of four — while
    already failing identity before the sync. The gate then refused the finished render
    for the reason a free local measurement would have given beforehand. A still head
    cannot rescue a take the gate will refuse; the sync moves the mean by thousandths.
    """
    picked = best_take(
        [
            _scored("steady_but_wrong", 2.78, (0.93,) + (0.96,) * 9),
            _scored("less_steady_but_her", 5.55, (0.96,) * 10),
        ],
        threshold=0.951,
    )
    assert picked.path.name == "less_steady_but_her"


def test_the_steadiest_of_the_acceptable_takes_wins() -> None:
    """Among takes the gate would accept, roll decides — it is still a real preference."""
    picked = best_take(
        [
            _scored("a", 8.9, (0.96,) * 10),
            _scored("b", 3.1, (0.955,) * 10),
            _scored("c", 6.2, (0.97,) * 10),
        ],
        threshold=0.951,
    )
    assert picked.path.name == "b"


def test_a_take_the_gate_would_refuse_is_not_synced() -> None:
    """Syncing a failing take buys a refusal at $0.50. The refusal names the nearest miss."""
    with pytest.raises(ValueError, match="Syncing it would buy a refusal"):
        best_take(
            [
                _scored("x", 3.0, (0.94,) + (0.96,) * 9),
                _scored("y", 4.0, (0.93, 0.94) + (0.96,) * 8),
            ],
            threshold=0.951,
        )


def test_thin_coverage_refuses_before_identity_is_blamed() -> None:
    """Which constraint failed decides the next move.

    Thin coverage means she moved out of frame, so the motion prompt is the lever. Frames
    below threshold mean the generator drifted off her face. Reporting the wrong one sends
    the next change to the wrong place.
    """
    with pytest.raises(ValueError, match="coverage floor"):
        best_take([_scored("thin", 2.0, (0.97, 0.98), sampled=10)], threshold=0.951)


def test_no_scorable_take_at_all_says_so_plainly() -> None:
    """Run 3 produced no detectable face in any frame of the finished render."""
    with pytest.raises(ValueError, match="not visible enough"):
        best_take([_scored("blind", 2.0, (), sampled=10)], threshold=0.951)


def test_coverage_counts_what_the_embedder_could_read() -> None:
    """The reconciliation, as a property.

    `measure` once reported 63-98% coverage on takes where 26-39% of frames could be
    embedded: the detector accepts a 63px face that `read` refuses under its 80px floor.
    A take could clear the floor and still be unscorable by the gate.
    """
    take = _scored("partial", 3.0, (0.96, 0.97, 0.96), sampled=10)
    assert take.coverage == pytest.approx(0.3)
    assert not take.would_pass_gate(threshold=0.951, min_coverage=0.6)


def test_a_take_scoring_well_over_too_few_frames_does_not_pass() -> None:
    """Three perfect frames in ten is 'cannot say', the same rule the gate applies."""
    take = _scored("flattered", 1.0, (0.99, 0.99, 0.99), sampled=10)
    assert take.frames_below(0.951) == 0
    assert not take.would_pass_gate(threshold=0.951, min_coverage=0.6)
