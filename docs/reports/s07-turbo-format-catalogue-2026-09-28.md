# The format catalogue, rated blind

**Date:** 2026-09-28 · 26 clips, 13 formats, 2 takes each, `h3-max-turbo`,
prompt expansion disabled. **$1.625.**

Filenames carried the format and take number only — no gate verdicts — so the
owner's ratings are independent of the automated ones and the two can be
compared. Ratings are of the **picture**. Audio defects are recorded in the
owner's words but do not move the number: they appear on nearly every clip and
are governed separately by pinning a soundtrack, so rating them would make every
format a discard and measure nothing about format yield.

## Yield

| Face-forward | Usable | Ratings |
|---|---|---|
| `talking_head_course` | 2/2 | 5, 5 |
| `clubhouse` | 2/2 | 5, 5 |
| `equipment_closeup` | 2/2 | 5, 5 |
| `walking_fairway` | 2/2 | 5, 4 |
| `reaction` | 2/2 | 4, 4 |
| `apparel` | **0/2** | **1, 3** |
| **Total** | **10/12 — 83%** | |

| Club-and-ball | Usable | Ratings |
|---|---|---|
| `full_swing_address` | 2/2 | 5, 4 |
| `full_swing_follow` | 2/2 | 4, 5 |
| `putting_stroke` | 2/2 | 5, 4 |
| `ball_flight` | 1/2 | 5, 3 |
| `chip` | 1/2 | 2, 4 |
| `full_swing_impact` | 1/2 | 5, 3 |
| `full_swing_top` | **0/2** | **3, 3** |
| **Total** | **9/14 — 64%** | |

`BUILD_PLAN` §9 assumes 3 in 5 discarded. Measured here: **1 in 4.**

## The gate misses six defects in seven

| | Count |
|---|---|
| True positives — gate failed it, owner rejected it | **1** |
| False positives — gate failed it, owner kept it | 2 |
| **False negatives — gate passed it, owner rejected it** | **6** |
| True negatives | 17 |

**The owner rejected 7 clips. The gate flagged 1.**

The earlier 10-clip sample showed no false negatives and that was luck. On 26
the gate catches **14%** of what a human rejects, and two thirds of what it
condemns is fine.

**The one it caught was the one worth catching.** Clip 7: *"No no no. Turns into
a man halfway through."* The gate failed it at **0.8605**, the lowest identity
score in the set, before anyone watched it. That is what it is for: catastrophic
identity collapse. It is not a publishability instrument and no threshold makes
it one.

What it missed, all of it real: an outfit changing mid-clip, a club materialising
from nowhere, a ball becoming dirty from nowhere, a putter that doesn't look
real, and three clips of a swing with no ball in shot. **None of those is a
face**, which is exactly the D-A argument, now with a denominator.

## Defects the tag vocabulary cannot express

`FAILURE_TAGS` comes from `BUILD_PLAN` task 2.3: `hands_grip`,
`club_distortion`, `contact_physics`, `ball`, `swing_plane`, `background`,
`face_drift`. Most of what the owner actually reported has no tag:

| Observed | Tag |
|---|---|
| Outfit changes mid-clip | none — forced into `background` |
| Club appears from nowhere | none — forced into `background` |
| Swing with no ball in shot | none — forced into `ball` |
| Wrong shot rendered (a chip that putts) | none |
| Narration in the wrong language | none |
| Invented music over the top | none |
| Ball-strike sound too loud | none |
| Subject morphs into another person | `face_drift` understates it |

**Task 2.3's tag list was written before anything had been generated.** It should
be rewritten from this run's observations, because a rating sheet that cannot
name the defect cannot aggregate it.

## The finding that changes the pipeline

Five clips carry the same note: **"Fine, her. Lip sync good. Wrong Language."**

**The model's native lip sync is good.** It is only speaking the wrong language.

That reopens ADR 0005, which was answered *no* three hours earlier on the
evidence that a pinned soundtrack does not move the mouth. It does not — because
pinning muxes audio over a finished video. But the model **does** lip sync
correctly to **its own** generated speech, and nobody had checked that because
nobody had listened until the owner did.

If the spoken language can be steered — and the prompt is the obvious lever —
then native lip sync replaces the HeyGen stage at **$0.40/clip**, which is now
six times the cost of the clip itself.

**One blocker, and it is not small.** The voice would be the model's, not the
ElevenLabs voice the owner chose after rejecting several. Clip 7's note says
*"wrong voice on narration"*, so voice is already being judged. Whether a correct
language in the wrong voice is worth $0.40 a clip is an owner decision, not a
measurement.

Cheapest next test: two clips with the dialogue written into the prompt, about
**13p**, to find out whether the language can be steered at all. If it cannot,
ADR 0005's *no* stands and nothing is lost.
