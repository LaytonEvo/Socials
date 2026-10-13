"""Measuring how long a golf swing is, so the gate can refuse the wrong one.

The brief asked for a 30-yard pitch, and *"the club goes back to about waist height"*
was in the prompt that produced the shot. The model rendered a full swing. Nothing in
this pipeline could tell: `golf.py` reads prompt TEXT for taboos — a trolley on the
green, a driver in a bunker — and the acceptance gate measures identity, disclosure,
captions and head roll. Swing length was measured nowhere. So a full swing from 30 yards
came back ACCEPTED and the owner caught it by watching.

That is ADR 0012 again, in a new dimension: what cannot be measured was treated as fine.

**The metric is the hands, not the club.** Swing length is conventionally described by
where the hands reach at the top of the backswing — waist, shoulder, above the head —
and the club follows the hands. Finding a club in a generated frame is fragile; wrists
are a standard pose landmark.

**The units are the golfer's own body.** Per frame,

    h = (hip_y - wrist_y) / (hip_y - shoulder_y)

so ``h = 0`` is that frame's hip line and ``h = 1`` is that frame's shoulder line. This
matters more than it first looks. A golfer at address is bent forward, which foreshortens
the apparent shoulder-to-hip span, so intermediate values of ``h`` are inflated and should
not be read as precise fractions of a backswing. What foreshortening does **not** move is
the boundary: ``h > 1`` means the hands are above the shoulder line *in that frame*,
whatever the posture, the camera distance or the lens. Only that boundary is used to
refuse a shot. Everything short of it is reported for a human, never passed silently.

**Sample densely.** The top of a pitch backswing lasts a fraction of a second. Missing the
peak can only *understate* it, and understating is the dangerous direction — it reads a
full swing as a short one. So the pose source takes frames at the clip's own rate rather
than at the 2 fps the identity gate samples at.

**What this does not measure.** Whether the club actually strikes the ball before the ball
moves; whether the lie, the club or the distance are consistent; tempo; plane. The first
of those is the defect `s07-golf-battery-2026-09-24.md` found and it remains unmeasured.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Final, Literal, Protocol, runtime_checkable

#: How long a backswing a shot is *meant* to have. Declared by the shot list, exactly as
#: `face_expected` is, and for the same reason: inferring it from the render would let the
#: generator decide what it is allowed to fail at.
SwingKind = Literal["putt", "chip", "pitch", "half", "full"]

#: The top of the backswing each kind may reach, in hip-to-shoulder units.
#:
#: **Only the 1.0 boundary is anatomically anchored** — it is the shoulder line, read off
#: the same frame as the hands. The others are the shot kinds' conventional descriptions
#: converted to this scale, and they are deliberately generous: they decide what gets
#: *reported*, never what gets refused. A number here being loose costs a review line; a
#: number here being tight would refuse good footage on a metric nobody has calibrated.
CEILING: Final[dict[str, float]] = {
    "putt": 0.15,  # the hands barely leave address
    "chip": 0.35,  # below the waist
    "pitch": 0.55,  # "club to about waist height"
    "half": 1.00,  # hands to the shoulder line
    "full": float("inf"),
}

#: The shoulder line. Hands above it are not making a pitch, a chip or a putt, and this
#: is the one claim in the module that does not depend on a calibration sample.
SHOULDER_LINE: Final = 1.0

#: Below this share of sampled frames carrying a usable pose, the peak describes too
#: little of the clip to stand for it. Mirrors `MIN_COVERAGE` in the identity gate and
#: exists for the same reason: a maximum over few frames is "cannot say", not a pass.
MIN_SWING_COVERAGE: Final = 0.5

#: A frame whose shoulder-to-hip span has collapsed to a fraction of the clip's typical
#: span is foreshortened or mis-detected past the point of use: the span is the divisor,
#: so a small one turns a modest hand height into a large `h`. Relative to the clip's own
#: median rather than to a pixel count, because landmark coordinates may be normalised.
MIN_SPAN_FRACTION: Final = 0.25


@dataclass(frozen=True)
class PoseFrame:
    """The vertical landmark positions this measurement needs, in image coordinates.

    `y` increases downward, as in every image coordinate system, so a *smaller* y is
    higher in the frame.

    Only y is carried. Swing length is a question about height, and holding x as well
    would invite metrics that nobody has calibrated — this project has retracted two of
    those already (`texture`, `cranium`).

    Each value is None when the pose source was not confident about that landmark. Both
    sides are kept separate rather than averaged by the adapter so that the reduction is
    testable here, where it can be exercised without a pose model.
    """

    left_shoulder_y: float | None = None
    right_shoulder_y: float | None = None
    left_hip_y: float | None = None
    right_hip_y: float | None = None
    left_wrist_y: float | None = None
    right_wrist_y: float | None = None


@runtime_checkable
class PoseSource(Protocol):
    """Whatever turns a video into a series of `PoseFrame`.

    A protocol so that nothing in the pipeline imports a pose library, and so that the
    maths above can be tested with hand-written frames and no model weights at all.
    """

    def frames(self, video: Path) -> list[PoseFrame]:
        """One entry per sampled frame, including frames where nothing was detected."""
        ...


def _mean(*values: float | None) -> float | None:
    """Average of the values that are present; None when none of them are.

    Both hands grip the club together, so averaging two wrists gives the grip. One
    visible wrist is used alone rather than discarding the frame, because a swing
    routinely occludes the trailing hand.
    """
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def span_of(frame: PoseFrame) -> float | None:
    """The frame's shoulder-to-hip distance, positive when the hips are below.

    None when either line is missing, and None when the span is not positive — hips at or
    above the shoulders means the figure is inverted or the landmarks are nonsense, and
    either way `h` would be meaningless rather than merely imprecise.
    """
    shoulder = _mean(frame.left_shoulder_y, frame.right_shoulder_y)
    hip = _mean(frame.left_hip_y, frame.right_hip_y)
    if shoulder is None or hip is None:
        return None
    span = hip - shoulder
    return span if span > 0 else None


def height_of(frame: PoseFrame, *, span: float) -> float | None:
    """Hand height in hip-to-shoulder units, against a span supplied by the caller.

    The span is passed in rather than recomputed so that `measure` can reject a
    foreshortened frame before dividing by it.
    """
    hip = _mean(frame.left_hip_y, frame.right_hip_y)
    wrist = _mean(frame.left_wrist_y, frame.right_wrist_y)
    if hip is None or wrist is None:
        return None
    return (hip - wrist) / span


@dataclass(frozen=True)
class SwingMeasurement:
    """What the clip actually shows, with enough detail to argue about it."""

    frames_sampled: int
    #: Hand heights for the usable frames only, in the order sampled.
    heights: tuple[float, ...]
    #: Frames dropped because their span had collapsed. Reported because a clip that
    #: loses most of its frames this way is telling you something about the render.
    frames_foreshortened: int = 0

    @property
    def coverage(self) -> float:
        if self.frames_sampled <= 0:
            return 0.0
        return len(self.heights) / self.frames_sampled

    @property
    def peak(self) -> float | None:
        """The top of the backswing. None when nothing was measurable."""
        return max(self.heights) if self.heights else None

    @property
    def frames_above_shoulder(self) -> int:
        return sum(1 for h in self.heights if h > SHOULDER_LINE)

    @property
    def well_covered(self) -> bool:
        return bool(self.heights) and self.coverage >= MIN_SWING_COVERAGE


def measure(frames: list[PoseFrame]) -> SwingMeasurement:
    """Reduce a frame series to one measurement.

    Two passes, because the foreshortening guard is relative to the clip: the first
    collects spans, the second divides by them.
    """
    spans = [s for s in (span_of(f) for f in frames) if s is not None]
    floor = median(spans) * MIN_SPAN_FRACTION if spans else 0.0

    heights: list[float] = []
    foreshortened = 0
    for frame in frames:
        span = span_of(frame)
        if span is None:
            continue
        if span < floor:
            foreshortened += 1
            continue
        height = height_of(frame, span=span)
        if height is not None:
            heights.append(height)
    return SwingMeasurement(
        frames_sampled=len(frames),
        heights=tuple(heights),
        frames_foreshortened=foreshortened,
    )


@dataclass(frozen=True)
class SwingCheck:
    """A measurement set against what the shot claimed to be.

    Carries no severity. What to *do* about a long swing is the acceptance gate's
    policy, and keeping it there means this module can be read as arithmetic.
    """

    declared: SwingKind
    measurement: SwingMeasurement

    @property
    def ceiling(self) -> float:
        return CEILING[self.declared]

    @property
    def verifiable(self) -> bool:
        """Whether the clip gave enough pose to say anything at all."""
        return self.measurement.well_covered

    @property
    def above_shoulder_line(self) -> bool:
        """Hands went above the shoulders. The anchored claim; refusable on its own."""
        peak = self.measurement.peak
        return peak is not None and peak > SHOULDER_LINE

    @property
    def longer_than_declared(self) -> bool:
        peak = self.measurement.peak
        return peak is not None and peak > self.ceiling

    def explain(self) -> str:
        m = self.measurement
        if not m.heights:
            return (
                f"declared a {self.declared} but no frame gave a usable pose "
                f"({m.frames_sampled} sampled, {m.frames_foreshortened} foreshortened)"
            )
        peak = m.peak
        assert peak is not None
        where = (
            "above the shoulder line"
            if peak > SHOULDER_LINE
            else f"{peak / SHOULDER_LINE:.0%} of the way to the shoulder line"
        )
        return (
            f"declared a {self.declared} (ceiling {self.ceiling:g}); hands peaked at "
            f"{peak:.2f}, {where}, with {m.frames_above_shoulder} of "
            f"{len(m.heights)} measured frames above the shoulder line "
            f"({m.coverage:.0%} of {m.frames_sampled} frames gave a usable pose)"
        )


def check(declared: SwingKind, frames: list[PoseFrame]) -> SwingCheck:
    """Measure a frame series and set it against the declared shot kind."""
    return SwingCheck(declared=declared, measurement=measure(frames))
