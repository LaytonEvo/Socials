# S0.6 — the condition matrix, and what actually drives failure

**18 of 20 cells generated, 11 passed identity, 7 indeterminate, 0 failed.**
The last two cells could not be generated: the fal balance is exhausted
(`403 User is locked. Reason: TOP_UP`).

Provider `fal-ai/veo3.1/fast/image-to-video`, six master stills rotated,
threshold 0.9609, spend $12.00 across two attempts.

## Pass rate by axis — the S0.6 deliverable

§3.3 item 2 asks for the breakdown rather than a headline, because "the
breakdown is where the decision lives". It does:

| Axis | Level | Pass | Worst frame | Indeterminate |
|---|---|---|---|---|
| **angle** | front | **6/6 (100%)** | 0.9821 | 0 |
| | profile | 3/6 (50%) | 0.9551 | 3 |
| | three_quarter | **2/6 (33%)** | 0.8920 | 4 |
| **distance** | close | 5/6 (83%) | 0.8920 | 1 |
| | medium | 5/6 (83%) | 0.9564 | 1 |
| | wide | **1/6 (17%)** | 0.9471 | 5 |
| **light** | golden_hour | **4/4 (100%)** | 0.9708 | 0 |
| | overcast | 4/5 (80%) | 0.9471 | 1 |
| | indoor | 2/4 (50%) | 0.8920 | 2 |
| | midday | **1/5 (20%)** | 0.9551 | 4 |
| **motion** | turning | 5/6 (83%) | 0.9551 | 1 |
| | static | 4/6 (67%) | 0.9718 | 2 |
| | walking | **2/6 (33%)** | 0.8920 | 4 |

## Nothing failed. Five of seven indeterminates are the detector losing her

| Cell | Usable frames | Cause |
|---|---|---|
| `profile-wide-indoor-static` | 3/8 | coverage |
| `three_quarter-medium-midday-walking` | 3/8 | coverage + a frame below |
| `profile-wide-midday-turning` | 8/8 | a frame below |
| `profile-wide-midday-static` | 3/8 | coverage |
| `three_quarter-wide-overcast-walking` | 3/8 | coverage + a frame below |
| `three_quarter-wide-midday-walking` | 3/8 | coverage |
| `three_quarter-close-indoor-walking` | 6/8 | a frame below |

**Zero cells failed on identity.** Where a face was visible it was almost
always her. Five of seven indeterminates are the same shape: the detector
found a face in 3 of 8 sampled frames, below the 50% coverage floor. That is
not "identity breaks in wide shots" — it is **"identity cannot be measured in
wide shots"**, because the face is too small or too fleeting to detect.

A different finding, and a better one: the gate is declining to judge rather
than judging wrongly, which is what the owner asked for on 2026-09-24 when
they chose strictness and review over false confidence.

## The axes are confounded, so do not read those rates as independent

With 18 cells over four axes the levels co-occur heavily. The seven
indeterminates are **5 wide, 4 walking, 4 midday, 4 three_quarter**, and
`three_quarter-wide-midday-walking` is one cell contributing to all four. So
`midday 20%` is probably not a lighting effect at all — midday cells in this
sample are disproportionately wide and walking.

The single mechanism consistent with every row is **apparent face size**.
Wide framing makes the face small; walking moves it; both reduce the frames a
detector can lock onto. Angle compounds it: a three-quarter or profile face
presents less to find than a front-on one.

That would also explain the one genuinely counterintuitive result.

## A prediction I got wrong, again

Before the run I expected `turning` to be the worst motion, on the grounds
that the one reproducible Veo failure is a face leaving frame and returning.
**`turning` was the best motion at 83%**, better than `static` at 67%.

The occlusion-return bug is real — the owner rejected two clips for it — but
it is not what this matrix measures, and turning a face through frame appears
to give the detector *more* to work with rather than less.

## What this says for the shot list

Directly usable, and it agrees with the battery:

- **Front-on, close or medium, golden hour** is the safe envelope: 100%,
  83%, 100%.
- **Wide shots cannot be identity-checked.** They are not forbidden, but they
  will arrive unverified and need a human, so they should be used where the
  face is not the point.
- **Walking wide is the worst combination** and appears in four of seven
  indeterminates.

## Limits

- 18 cells, 4–6 per level. These are directional, not rates to plan against.
- Axes confounded, as above. Separating them needs a balanced sample, which
  means the full 108 or a designed subset.
- Single keyframe per cell, no first/last-frame conditioning, so this measures
  the unfixed occlusion behaviour.
- Two cells never ran. The run is incomplete for the reason below.

## Blocked

The fal balance is exhausted. Nothing further can be generated until it is
topped up — including the two missing cells, the second battery take, and any
further lip-sync work.
