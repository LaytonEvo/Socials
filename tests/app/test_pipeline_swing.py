"""Swing length, the dimension the gate was missing when it accepted a full swing.

The owner's report: *"we're generating videos where she is hitting a full swing golf
shot from around 30 yards away from the green."* The prompt that produced it said *"the
club goes back to about waist height"*, so this was never a prompting problem — nothing
measured what came back, and `golf.py` only reads prompt text for taboos.

The numbers in the separation test below are real. Measured 2026-10-13 with
`pose_landmarker_heavy` over every frame:

    broll/address_strike_take_0    peak 1.68    (withdrawn, declared a pitch)
    broll/address_strike_take_1    peak 1.65
    broll/address_strike_take_2    peak 1.61
    pinned-swing/take_0            peak 1.46    ("massive swing for such a short shot")
    pinned-swing/take_1            peak 1.51
    shot1-final/final_captioned    peak 0.16    (talking to camera, hands at rest)
    shot1-final/take_1             peak 0.11

The shoulder line at 1.0 sits in a gap an order of magnitude wide, which is why it can
be refused on. Nothing between 0.16 and 1.46 has been measured, so the ceilings for the
kinds in between are conventional and produce REVIEW, never a refusal.
"""

from __future__ import annotations

import pytest

from app.pipeline.swing import (
    CEILING,
    MIN_SPAN_FRACTION,
    SHOULDER_LINE,
    PoseFrame,
    check,
    height_of,
    measure,
    span_of,
)

#: A frame's anatomy in normalised image coordinates, y downward. Shoulders at 0.3, hips
#: at 0.6, so the hip-to-shoulder span is 0.3 and `h` units are thirds of the frame.
SHOULDER_Y = 0.3
HIP_Y = 0.6
SPAN = HIP_Y - SHOULDER_Y


def frame_with_hands_at(height: float, *, span: float = SPAN) -> PoseFrame:
    """A pose whose hands sit `height` hip-to-shoulder units above the hip line."""
    hip = HIP_Y
    shoulder = hip - span
    return PoseFrame(
        left_shoulder_y=shoulder,
        right_shoulder_y=shoulder,
        left_hip_y=hip,
        right_hip_y=hip,
        left_wrist_y=hip - height * span,
        right_wrist_y=hip - height * span,
    )


# ------------------------------------------------------------------- units --
@pytest.mark.parametrize("height", [0.0, 0.5, 1.0, 1.68])
def test_zero_is_the_hip_line_and_one_is_the_shoulder_line(height: float) -> None:
    frame = frame_with_hands_at(height)
    span = span_of(frame)
    assert span is not None
    assert height_of(frame, span=span) == pytest.approx(height)


def test_the_scale_does_not_depend_on_apparent_body_size() -> None:
    """A golfer further from the camera must measure the same.

    The whole point of dividing by the frame's own span: the number is in units of the
    body in that frame, so camera distance and lens drop out.
    """
    near = frame_with_hands_at(1.2, span=0.4)
    far = frame_with_hands_at(1.2, span=0.08)
    assert measure([near]).peak == pytest.approx(measure([far]).peak)


def test_one_visible_wrist_is_used_rather_than_discarding_the_frame() -> None:
    """A swing occludes the trailing hand routinely; both hands grip the same club."""
    frame = PoseFrame(
        left_shoulder_y=SHOULDER_Y,
        right_shoulder_y=SHOULDER_Y,
        left_hip_y=HIP_Y,
        right_hip_y=HIP_Y,
        left_wrist_y=HIP_Y - SPAN,  # one wrist, at the shoulder line
        right_wrist_y=None,
    )
    assert measure([frame]).peak == pytest.approx(1.0)


def test_a_frame_with_no_wrists_is_not_measurable() -> None:
    frame = PoseFrame(left_shoulder_y=SHOULDER_Y, left_hip_y=HIP_Y)
    assert measure([frame]).heights == ()


def test_hips_above_shoulders_is_rejected_rather_than_producing_a_number() -> None:
    """An inverted or nonsense pose would otherwise divide by a negative span."""
    upside_down = PoseFrame(
        left_shoulder_y=0.6,
        right_shoulder_y=0.6,
        left_hip_y=0.3,
        right_hip_y=0.3,
        left_wrist_y=0.4,
        right_wrist_y=0.4,
    )
    assert span_of(upside_down) is None
    assert measure([upside_down]).heights == ()


def test_a_collapsed_span_is_excluded_and_counted() -> None:
    """The divisor is the span, so a foreshortened frame inflates `h` without limit."""
    good = [frame_with_hands_at(0.2) for _ in range(9)]
    collapsed = frame_with_hands_at(0.2, span=SPAN * MIN_SPAN_FRACTION / 2)
    m = measure([*good, collapsed])
    assert m.frames_foreshortened == 1
    assert len(m.heights) == 9


# ---------------------------------------------------------------- coverage --
def test_coverage_counts_frames_where_nothing_was_detected() -> None:
    """An empty frame must cost coverage.

    Dropping undetected frames in the pose source would make a clip with one good frame
    read as fully covered — the identity gate's own 2026-10-01 failure, in a new place.
    """
    m = measure([frame_with_hands_at(0.3), PoseFrame(), PoseFrame(), PoseFrame()])
    assert m.frames_sampled == 4
    assert m.coverage == pytest.approx(0.25)
    assert m.well_covered is False


def test_a_well_covered_clip_is_judgeable() -> None:
    m = measure([frame_with_hands_at(0.3) for _ in range(10)])
    assert m.coverage == 1.0
    assert m.well_covered is True


def test_the_peak_is_the_top_of_the_backswing() -> None:
    series = [0.1, 0.4, 0.9, 1.4, 0.8, 0.2]
    m = measure([frame_with_hands_at(h) for h in series])
    assert m.peak == pytest.approx(1.4)
    assert m.frames_above_shoulder == 1


# ------------------------------------------------------------------ rules --
def test_the_withdrawn_shot_would_now_be_caught() -> None:
    """Declared a pitch, measured at 1.68. The clip the owner withdrew."""
    swing = check("pitch", [frame_with_hands_at(h) for h in (0.1, 0.9, 1.68, 0.6, 0.1)])
    assert swing.verifiable
    assert swing.above_shoulder_line
    assert swing.longer_than_declared
    assert "1.68" in swing.explain()


def test_the_talking_shot_is_not_flagged() -> None:
    """Measured at 0.11-0.16 with hands at rest. The control that makes the metric mean
    something: if this read high too, the measurement would be worthless."""
    swing = check("pitch", [frame_with_hands_at(h) for h in (0.11, 0.16, 0.12, 0.14)])
    assert swing.verifiable
    assert not swing.above_shoulder_line
    assert not swing.longer_than_declared


def test_a_real_pitch_passes() -> None:
    """Club to waist height: hands around the hip line, nowhere near the shoulders."""
    swing = check("pitch", [frame_with_hands_at(h) for h in (0.0, 0.25, 0.5, 0.3, 0.0)])
    assert not swing.longer_than_declared
    assert not swing.above_shoulder_line


def test_a_full_swing_declared_as_one_is_fine() -> None:
    swing = check("full", [frame_with_hands_at(h) for h in (0.1, 1.0, 1.7, 0.9)])
    assert swing.above_shoulder_line
    assert not swing.longer_than_declared


def test_an_unmeasurable_clip_is_not_a_pass() -> None:
    """No person in frame — the b-roll cutaway case, measured at 0% coverage."""
    swing = check("pitch", [PoseFrame() for _ in range(20)])
    assert not swing.verifiable
    assert swing.measurement.peak is None
    assert "no frame gave a usable pose" in swing.explain()


def test_the_ceilings_rise_with_the_length_of_the_shot() -> None:
    """Ordering is the part of the table that is not a guess."""
    order = ["putt", "chip", "pitch", "half", "full"]
    ceilings = [CEILING[k] for k in order]
    assert ceilings == sorted(ceilings)
    assert CEILING["half"] == SHOULDER_LINE
