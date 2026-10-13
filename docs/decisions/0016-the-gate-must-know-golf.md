# ADR 0016 — The gate has to measure the golf, not just the face

- **Status**: accepted, 2026-10-13
- **Amends**: ADR 0009, which decided "no golf knowledge base" and reasoned only about
  her dialogue. It never asked whether the *picture* is golf-correct.
- **Extends**: ADR 0012 — unverifiable is not acceptable — into a second dimension
- **Deciders**: Layton (owner)

## Context

The owner's report:

> *"Golf knowledge of the videos... we're generating videos where she is hitting a full
> swing golf shot from around 30 yards away from the green."*

This was never a prompting problem. The prompt that produced that shot is in
`scripts/make_broll.py` and says, in full:

> *"She takes a smooth pitching swing: the club goes back to about waist height, comes
> down and brushes the turf as it strikes the ball, and she holds a balanced finish."*

The model rendered a full swing anyway — three takes out of three, and again on the
pinned-swing retest a week later, which the owner summarised as *"massive swing for such
a short shot."* **Prompting swing length has now failed five times out of five.** It is
not a control surface.

The worse half is that nothing noticed. `app/pipeline/golf.py` reads prompt *text* for
taboos — a trolley on the green, a driver in a bunker — which catches a badly written
brief and says nothing about a badly rendered one. The acceptance gate measures identity,
disclosure, captions, audio provenance and head roll. **Swing length was measured
nowhere**, so the gate stamped ACCEPTED on a full swing from 30 yards and the owner
caught it by watching.

That is precisely the failure ADR 0012 was written about, in a dimension ADR 0012 did not
cover. The instrument of record was again the owner's eye.

## Decision

**Measure the swing. Refuse the ones that are definitively wrong, report the rest, and
block the ones that cannot be measured at all.**

### The metric is the hands, against the shoulder line of the same frame

Swing length is conventionally described by where the hands reach at the top of the
backswing — waist, shoulder, above the head — and the club follows the hands. Per frame,

    h = (hip_y - wrist_y) / (hip_y - shoulder_y)

so `h = 0` is that frame's hip line and `h = 1` is that frame's shoulder line.

**Only the `h = 1` boundary is used to refuse.** A golfer at address is bent forward,
which foreshortens the apparent shoulder-to-hip span and inflates intermediate values of
`h` — so those are reported, never refused on. What foreshortening does not move is the
boundary itself: `h > 1` means the hands are above the shoulder line *in that frame*,
whatever the posture, camera distance or lens. No putt, chip, pitch or half swing does
that. This is an anatomical fact, not a calibrated threshold, which is what makes it
safe to block on — and this project has paid three times for the difference (see
`identity-threshold-correction-2026-09-24.md`, `pass-rate-2026-10-01.md`, and the
retracted `texture` and `cranium` metrics).

### What the gate now does

`ShotUnderTest` gains `swing: SwingKind | None`, declared by the shot list exactly as
`face_expected` is, and for the same reason: inferring it from the render would let the
generator decide what it is allowed to fail at.

| Condition | Severity | Why |
|---|---|---|
| declares a swing, no pose source given | **BLOCKING** | a swing nobody measured is how this got through |
| pose coverage below 50% | **BLOCKING** | a peak over few frames is "cannot say"; missing the top *understates* it |
| hands above the shoulder line, declared anything but `full` | **BLOCKING** | anatomically anchored |
| longer than the declared kind but below the shoulder line | REVIEW | the inter-kind ceilings are conventional, not calibrated |
| declared `full`, hands never above the shoulders | REVIEW | the mirror fault; or the clip ends before the top |

### Sample every frame

The top of a pitch backswing lasts a fraction of a second. Missing it can only
*understate* the peak, which is the direction that lets a full swing through — so the
pose source reads the clip at its own frame rate, not at the 2 fps the identity gate uses.

## Measured

Every frame, `pose_landmarker_heavy`, 2026-10-13:

| Clip | Declared | Peak | Verdict now |
|---|---|---|---|
| `broll/address_strike_take_0` | pitch | **1.68** | REFUSED |
| `broll/address_strike_take_1` | pitch | **1.65** | REFUSED |
| `broll/address_strike_take_2` | pitch | **1.61** | REFUSED |
| `pinned-swing/take_0` | pitch | **1.46** | REFUSED |
| `pinned-swing/take_1` | pitch | **1.51** | REFUSED |
| `shot1-final/final_captioned` | — | 0.16 | not a swing shot; would pass |
| `shot1-final/take_1` | — | 0.11 | not a swing shot; would pass |
| `broll/result_take_0` | — | none (0% coverage) | nobody in frame; not checked |

**The gap between 0.16 and 1.46 is an order of magnitude wide and the shoulder line sits
in the middle of it.** That separation is the whole argument for blocking on it. Nothing
has been measured between those values, which is exactly why nothing between them is
refused.

## What this does not do

- **It does not make the swings right.** It refuses the wrong ones. Yield on club-and-ball
  shots was already 2 in 13; this lowers the measured pass rate rather than raising it,
  and that is the point — the previous number was wrong.
- **It does not check causality.** Whether the club strikes the ball *before* the ball
  moves is the defect `s07-golf-battery-2026-09-24.md` found, and it remains unmeasured.
- **It does not check club, lie or distance consistency.** A pitch played with a driver
  would pass this check.
- **It measures one person.** `num_poses=1`; a two-golfer frame is out of scope.

## Consequences

**The prompt route is closed and the plan narrows to one.** With swing length refusable,
the way to get a correct swing is to stop asking a model to invent one: motion transfer
from real footage, where the length is whatever was filmed. `kling-video/v3/motion-control`
on fal, $0.126/s, costed in `motion-transfer-options-2026-09-25.md` and
`vendor-review-2026-10-13.md`. This check is also what makes that test *readable*: the
driving footage can be measured before it is used, and the output measured after.

**A new dependency and a new set of weights.** mediapipe, Apache 2.0, verified from the
LICENSE in the installed wheel. The **weights licence is not verified** — Google publishes
the pose model card on `ai.google.dev`, which this environment's network policy blocks.
`config/providers.yaml` records it as null with `licence_cleared_for_publication: false`,
following the embedder's precedent. This is measurement only: nothing from the model enters
a render, so it blocks publication rather than measurement. **It is a second D-C until the
model card is read.**

**ADR 0009 stands, narrowed.** Its argument was about her words, and it was right about
them: a retrieval layer would make her an authority, which the spec spends a section
avoiding. It said nothing about the picture, and the picture needed a measurement rather
than a knowledge base.
