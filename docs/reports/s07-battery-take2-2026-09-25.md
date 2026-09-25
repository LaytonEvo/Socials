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

## Why both clips failed: the keyframe is a portrait, the shot is not

**I proposed a first/last-frame test before looking at the clips. Looking at
them killed the hypothesis.** Eight-frame strips of both rejects show one shared
structure, and it is not an invented middle between two good ends.

Both clips open on three frames of head-and-shoulders portrait, then the camera
leaves her face and the golf is fabricated in a wide shot:

- **`putting_stroke`** — after the cut to wide, she stands at address with a
  putter and **the ball sits on the far side of the putter face**, so the club
  is addressing it from the wrong side. The stroke is never made. Her face is
  behind her hair in every wide frame, which is the 0.250 presence.
- **`ball_flight`** — she turns, the camera pans off her to the fairway, and a
  ball travels away **low and flat, with no swing shown at all**. The owner's
  words: *"ball flight does have a ball in it... but low flight and no swing."*
  An iron also materialises lying on the turf for two frames and vanishes.

**Neither clip ever renders the golf action. They render the before and the
after.**

### The format that succeeded did the opposite

`full_swing_follow`, rated 4 and scored 1.000 presence, never leaves the portrait
framing. She holds a follow-through pose facing camera while a club swings into
frame from off-screen. It is a *portrait containing a club*, not a swing, and
that is exactly why it works.

### The mechanism

The keyframe every one of these shots starts from is a head-and-shoulders
Midjourney still. That composition is the model's anchor.

- A shot that can be **posed inside a portrait** — talking head, reaction,
  clubhouse, apparel, follow-through — stays anchored and succeeds. Every one of
  these held 1.000 face presence.
- A shot that **requires a wide action framing** — a putting stroke, a ball in
  flight — cannot be shown from the anchor, so the model pans away from it. From
  that point nothing constrains the scene, and the golf is invented: ball on the
  wrong side of the club, a swing skipped entirely, a club appearing on the grass.

**This reframes the presence correlation.** Low face presence is not a
coincidence that happens to track club-and-ball shots. It *is* the model leaving
the keyframe's composition, which is the same moment the physics stops being
anchored. The signal and the defect have one cause, which is why the routing
rule in the previous section works better than a proxy has any right to.

### The first/last-frame hypothesis is withdrawn

Pinning both ends of the motion cannot help when **both ends would be
portraits**. ADR 0007 worked on `turn_away_and_back` because the two ends were
the correct framing and only the middle was missing. Here the framing itself is
wrong for the shot, and interpolating between two wrong frames gives a smoother
wrong clip.

*Arithmetic correction: I costed that test at $0.60 for two clips. The Fast tier
is $0.15/s and these are 4 s clips, so it is $0.60 each and $1.20 for two.*

### What is being tested instead

One variable, two takes: the **same `putting_stroke` prompt, same Fast slot, and
a keyframe that is already in the action framing** — a full-body address frame
lifted from take 2 — against the two portrait-keyframe takes already on disk.
$1.20.

The readout does not depend on the keyframe being perfect, and it is not: the
frame carries the same ball-on-the-wrong-side flaw, because every action-framed
still of this persona has been extracted from a clip whose action was already
wrong. The question is whether the model **holds the framing and animates**, or
pans away and fabricates as before. That is visible either way.

### Result: the framing holds, the stroke still does not, and the gate goes blind

Two takes, $1.20, `battery-putting_stroke-fast-2` and `-fast-3`.

| | Keyframe | Face presence | Verdict |
|---|---|---|---|
| take 1 | portrait | 0.625 | fail |
| take 2 | portrait | 0.250 | indeterminate — **owner reject** |
| take 3 | **action** | **0.000** | indeterminate |
| take 4 | **action** | **0.000** | indeterminate |

**The mechanism is confirmed, 2 of 2.** Both action-keyframe takes hold the
framing for the full four seconds. No pan away, no cut to wide, no hallucinated
club on the turf, no wardrobe change, one continuous scene. Set beside the
portrait-keyframe takes the difference is not subtle. **Keyframe composition
governs whether the model stays in the shot you asked for.**

**The primary defect is not fixed by it.** She addresses the ball and remains at
address. Whether a stroke is made in the last second is a judgement I am not
making: the ball and putter head both travel up-frame over the final ~0.8 s,
which reads either as the ball rolling away from camera — a real stroke in
perspective — or as both objects drifting off the turf. **Sent to the owner.**
On the record of this spike, my reading of a clip is worth less than theirs.

### The cost of the fix: face presence 0.000

Both action takes score **zero** face presence. Not low — zero. The keyframe is a
full-body address with her face behind her hair, the model faithfully holds that
framing, and so the face is never visible in any sampled frame.

**The framing that makes the golf work is the framing the identity gate cannot
score at all.** That is worse than the portrait takes it replaces, and it is a
structural conflict rather than a tuning problem: a shot composed to show a club
striking a ball is composed not to show a face.

#### What it suggests for D-A and D-B

A design option, not a measurement: **verify identity on the keyframe, and
verify the clip for continuity instead.**

Clip-level identity scoring is trying to answer a question the keyframe already
answers, and on action shots it cannot answer it at all. If the keyframe is a
known-good still of the persona, identity is established at the source; what
remains to check is that the clip never cuts away from it, which is
frame-to-frame continuity — the same instrument D-A already needs for motion and
the same one that would have caught the wardrobe change in take 1.

This does not rescue the current gate. It moves the identity claim to where the
evidence actually is.

### This is the strongest argument yet for D-D

Gate A retired S0.4's LoRA partly on the grounds that *"Midjourney stills cover
keyframes"*. They cover **portrait** keyframes. There is currently no source of
an action-framed still of this persona, and the club-and-ball formats are failing
for exactly that reason.

**D-D should be reopened**, not as a LoRA question but as a sourcing question:
the pipeline needs stills of her at address, at the top, at impact, and the
portrait set does not contain them. A LoRA is one answer; pose-conditioned
Midjourney prompts may be a cheaper one.

### One more thing the gate cannot see

In take 1 of `putting_stroke` her lower garment changes mid-clip, white skirt to
black shorts, while the identity score stays fine. That is Gate A §3's first
blind spot — *"it scores a face crop: body, limbs and scene are outside the
measurement"* — with a concrete instance attached rather than an argument.

## Carried forward

- `walking_fairway`, `apparel`, `full_swing_address` second takes: ~$1.80.
- ~~First/last-frame on `ball_flight` and `putting_stroke`~~ — hypothesis withdrawn, see above.
- ~~Action-framed keyframe test on `putting_stroke`~~ — run 2026-09-25, $1.20. Framing fixed, stroke not. Owner rating outstanding.
- A source of action-framed stills of the persona. Reopens D-D.
- Gate A §5 and §6 amended 2026-09-25; the ADR 0003 bullet is withdrawn pending the above.
- Two providers, the other half of the acceptance criterion, is still unaddressed. Both takes are `veo3.1/fast/image-to-video`.
