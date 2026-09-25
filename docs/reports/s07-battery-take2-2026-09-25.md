# S0.7 second battery take — two formats failed their second take

**Date:** 2026-09-25 · **Status:** 10 of 13 formats have a second take, owner-rated.

Gate A §5 carries the caveat *"one take, one provider. One good take does not
prove a format is reliably good."* This is the second take, run with
`--take-offset 1` so the take-0 clips the owner had already rated were not
re-bought. **Two formats did not survive it.**

## What ran

10 of 13 formats generated. Three did not: `walking_fairway`, `apparel`,
`full_swing_address`, all lost to `403 User is locked. Reason: TOP_UP` part way
through the run. Real spend $6.00 for 10 clips at the Fast tier.

The lock was intermittent — succeeding, locking, succeeding — which is
consistent with a balance hovering at zero rather than a hard stop, and is why
the run is ragged rather than truncated at a clean point.

## Owner verdict

The owner reviewed all ten and rejected two: **`ball_flight` and
`putting_stroke`, both on golf swing and ball physics.** Tagged
`contact_physics`, `swing_plane`, and `ball` on the ball-flight clip. The other
eight were not flagged; they carry no numeric score, only "reviewed, not
flagged", which is a weaker statement than the 4s and 5s take 0 received.

**These are the first below-4 ratings in the battery, and they overturn the
headline of Gate A §5.** Both formats were rated 4 (*usable, club/ball detail
off*) in take 0. The same prompt produced a usable clip once and a reject once.
That is exactly what the two-take criterion exists to find, and it found it.

| | Take 1 | Take 2 |
|---|---|---|
| `ball_flight` | 4 — usable | **2 — reject, physics** |
| `putting_stroke` | 4 — usable | **2 — reject, physics** |

**The 13/13 usable rate does not survive.** On the 10 formats with two takes,
**8 are usable twice and 2 are not.**

## Per-take reject rate, split by shot class

`hard: True` in `matrix.py` marks the seven formats where a club and ball are
doing the work in frame. Both rejects are in that set.

| Shot class | Takes generated | Rejected | Rate | 95% CI (Clopper-Pearson) |
|---|---|---|---|---|
| Club-and-ball (`hard`) | 13 | 2 | 15.4% | 1.9% – 45.4% |
| Face-forward | 10 | 0 | 0.0% | 0.0% – 30.8% |

**The split matches ADR 0003's prediction and the sample cannot establish it.**
The intervals overlap across most of their range; at these counts a true 20%
reject rate on face-forward shots is not excluded. What the data supports is
that both observed failures fell on the predicted side, which is consistent
with the prediction and is not the same as confirming it.

## The review lane caught both clips, for the wrong reason

Both rejects scored `indeterminate`, so both would have gone to a human rather
than being auto-published. **That is the right outcome reached by an unrelated
mechanism.** Neither was routed there because the swing looked wrong; both were
routed there because the face was found in 2 of 8 sampled frames. The gate still
cannot see physics, and nothing here suggests it can.

The reason the accident is not purely lucky is a structural correlation:

| Shot class | Takes | Face presence: mean | median | min |
|---|---|---|---|---|
| Club-and-ball | 13 | 0.529 | 0.375 | 0.250 |
| Face-forward | 10 | **1.000** | 1.000 | **1.000** |

**Every clip that ever lost a single frame of face was a club-and-ball shot —
10 of 10, no exceptions.** No face-forward shot has yet dropped below 1.000.
The relation is one-directional: low presence implies a club-and-ball shot, but
three club-and-ball takes held 1.000 presence, so high presence implies nothing.
Both owner rejects sit at the floor of the band (0.250), tied with
`full_swing_impact`.

The mechanism is unsurprising once stated. A shot framed to show a club striking
a ball is a shot in which the face is small, turned away, or out of frame. Face
presence, built as a *measurement-validity* signal, doubles as a *shot-type*
signal.

### What that offers D-A

A routing rule, not a detector: **face presence below 1.0 means the club and
ball are carrying the shot, so the clip needs a human looking at the golf, not
just at the face.** It costs nothing — the statistic is already computed — and
it is honest about what it is. It cannot detect a bad swing. It identifies the
clips where a bad swing is possible, which is the subset a human must watch
frame by frame.

This does not soften D-A. The gate remains unable to judge publishability, and
the owner's eye remains the only instrument that has identified a physics defect.

## ADR 0003: still needs amending, in the other direction

Gate A concluded ADR 0003 over-constrained the format list and *"the constraint
is not 'these formats are impossible' but 'club and ball detail is imperfect
wherever they appear' — far weaker."* **The second half of that is now too
generous.** On `ball_flight` and `putting_stroke` the defect was not detail being
imperfect; it was physics being wrong enough to discard the clip.

The defensible position sits between the ADR and my own reading of take 0:

- **ADR 0003's axis is right.** Club-and-ball shots are where failure lands. Both rejects are there and no face-forward clip has failed.
- **ADR 0003's strength is still too high.** 11 of 13 club-and-ball takes were usable. These formats are not impossible.
- **The constraint is a yield penalty, not a capability limit.** Roughly one club-and-ball take in seven is discarded, with wide uncertainty.

That has a cost consequence Gate A §6 does not carry. A format needing
occasional retakes costs more per finished piece than the ledger implies, and it
lands specifically on swing content — the formats a golf persona most needs.

**The amendment should wait** for the three missing formats and for owner
ratings on a third take of the two that failed. Amending twice on n=1 each time
is how the ADR got over-constrained in the first place.

## A hypothesis worth $0.60, not a prediction

First/last-frame conditioning solved the occlusion-return failure by pinning
both ends of a motion so the model interpolates rather than inventing the return
(ADR 0007). A golf swing is the same shape of problem: a constrained trajectory
whose midpoint the model currently invents. Pinning the address frame and the
follow-through frame may constrain the swing arc the way it constrained the turn.

**Flagged as untested.** Four of my predictions in this spike were wrong, and the
roll detector is a closer analogue than I would like: built on a plausible
mechanism, it did not catch the defect it was designed for. Two clips at
`flf_fast` would settle it.

## Carried forward

- `walking_fairway`, `apparel`, `full_swing_address` second takes: ~$1.80.
- First/last-frame on `ball_flight` and `putting_stroke`: ~$0.60, hypothesis above.
- Gate A §5 and §6 amended 2026-09-25; the ADR 0003 bullet is withdrawn pending the above.
- Two providers, the other half of the acceptance criterion, is still unaddressed. Both takes are `veo3.1/fast/image-to-video`.
