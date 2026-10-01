"""The pass-rate harness reads its own result out of another script's stdout.

That is a real hazard and it has a precedent: a verdict column once reported one
scorable frame in ten as "PASS every frame". A measurement tool that silently
misparses is worse than no measurement, because it is believed. These tests pin the
classification against log text taken verbatim from real runs, so a change to the
single-shot script's output breaks a test here instead of quietly reporting 0%.
"""

from __future__ import annotations

from decimal import Decimal

from scripts.pass_rate import (
    ACCEPTED,
    BLOCKING,
    ERROR,
    GATE_REFUSED,
    KEYFRAME_REFUSED,
    KEYFRAME_SCORE,
    NO_KEYFRAME,
    TAKE_LINE,
    RunResult,
    report,
)

# Verbatim from the accepted run, 2026-09-30.
ACCEPTED_LOG = """\
keyframe    keyframe.png
  take 1/4
    take_0.mp4: head roll sd 5.93 deg over 41/41 frames (100% coverage)
    take_1.mp4: head roll sd 4.11 deg over 41/41 frames (100% coverage)
  picked take_1.mp4
voice       line.mp3
disclosed   final.mp4
ACCEPTED  (0 blocking, 1 for review)
  [REVIEW] lip sync: whether the mouth matches the words is not measurable here.
"""

# Verbatim from the refused run that preceded it.
GATE_REFUSED_LOG = """\
keyframe    keyframe.png
    take_1.mp4: head roll sd 3.43 deg over 14/41 frames (34% coverage)
disclosed   final.mp4
REFUSED  (1 blocking, 1 for review)
  [BLOCKING] single: identity: 8 of 8 frames score below 0.951 (min 0.93318). \
It is not reliably her.
  [REVIEW] lip sync: whether the mouth matches the words is not measurable here.
"""

KEYFRAME_REFUSED_LOG = """\
  keyframe 1/4: 0.95049 below 0.9619
  keyframe 2/4: 0.94812 below 0.9619
  keyframe 3/4: 0.94103 below 0.9619
  keyframe 4/4: 0.95210 below 0.9619
no keyframe reached the still threshold 0.9619 (best 0.95210; all candidates: \
0.95049, 0.94812, 0.94103, 0.95210).
"""


def _classify(log: str, exit_code: int) -> str:
    """The classification branch of `run_once`, over text rather than a subprocess."""
    if exit_code == 0:
        return ACCEPTED
    if NO_KEYFRAME.search(log):
        return KEYFRAME_REFUSED
    if list(BLOCKING.finditer(log)):
        return GATE_REFUSED
    return ERROR


def test_an_accepted_run_is_read_as_accepted() -> None:
    assert _classify(ACCEPTED_LOG, 0) == ACCEPTED


def test_a_gate_refusal_is_not_an_error() -> None:
    """A refusal is the gate working. Counting it as an error would hide it."""
    assert _classify(GATE_REFUSED_LOG, 1) == GATE_REFUSED


def test_a_keyframe_refusal_is_distinguished_from_a_gate_refusal() -> None:
    """They cost about four times different, so averaging them reports a fiction."""
    assert _classify(KEYFRAME_REFUSED_LOG, 1) == KEYFRAME_REFUSED


def test_a_crash_is_an_error_not_a_failure() -> None:
    """A run that never reached a verdict was not judged, and must not count as one."""
    assert _classify("Traceback (most recent call last):\nConnectionError\n", 1) == ERROR


def test_keyframe_scores_are_read_off_the_log() -> None:
    found = [(float(m.group(3)), m.group(4)) for m in KEYFRAME_SCORE.finditer(KEYFRAME_REFUSED_LOG)]
    assert found == [
        (0.95049, "below"),
        (0.94812, "below"),
        (0.94103, "below"),
        (0.95210, "below"),
    ]


def test_take_coverage_is_read_as_a_ratio() -> None:
    thin = [int(m.group(3)) / int(m.group(4)) for m in TAKE_LINE.finditer(GATE_REFUSED_LOG)]
    assert thin == [14 / 41]


def _result(index: int, outcome: str) -> RunResult:
    return RunResult(
        index=index,
        outcome=outcome,
        seconds=600.0,
        keyframe_scores=[0.97],
        keyframe_passes=1,
        best_keyframe=0.97,
        take_coverage=[1.0],
        blocking=[] if outcome == ACCEPTED else ["identity"],
        exit_code=0 if outcome == ACCEPTED else 1,
    )


def test_errors_are_excluded_from_the_rate_rather_than_counted_as_failures() -> None:
    """Three accepted of four judged is 75%, not 60% of five attempted."""
    text = report(
        [
            _result(1, ACCEPTED),
            _result(2, ACCEPTED),
            _result(3, ACCEPTED),
            _result(4, GATE_REFUSED),
            _result(5, ERROR),
        ],
        per_run=Decimal("1.0352"),
    )
    assert "3/4 = 75%" in text
    assert "1 of 5 runs errored" in text


def test_a_zero_pass_rate_does_not_report_an_expected_attempt_count() -> None:
    """Dividing by a zero rate is infinity, which is not a retry cap."""
    text = report([_result(1, GATE_REFUSED), _result(2, KEYFRAME_REFUSED)], per_run=Decimal("1"))
    assert "No run passed" in text
    assert "Expected attempts" not in text


def test_the_expected_attempt_count_is_the_inverse_of_the_rate() -> None:
    """This is the number task 3.4's retry cap is a bet on."""
    text = report([_result(1, ACCEPTED), _result(2, GATE_REFUSED)], per_run=Decimal("1"))
    assert "1/2 = 50%" in text
    assert "2.00" in text
