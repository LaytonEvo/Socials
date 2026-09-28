# Is the golf failure veo3.1's, or video generation's?

**Date:** 2026-09-25, extended 2026-09-28 · **Status:** turbo rated and repeated; the other two carry no verdict.

Every conclusion the spike has drawn about what video models can and cannot do
rests on **one model family**: `veo3.1`, fast and flagship. The club-and-ball
causality failure — the club misses the ball and the ball moves anyway — was
measured 13 times on that one model and then generalised.

This probe tests whether the generalisation holds.

## Method

One variable: the model. Same shot (`putting_stroke`), same prompt, same
action-framed keyframe, one take each, all through the existing battery harness
so scoring is identical.

Durations differ because the schemas force it: `veo3.1` takes 4 s literals, the
h3-max family rejects anything under 5 s, `gemini-omni-flash` defaults to 8 s.
Noted rather than corrected — the question is whether a strike renders at all,
not a controlled duration comparison.

| Slot | Model | $/s | Result |
|---|---|---|---|
| `alt_h3max_turbo` | `minimax/h3-max-turbo/image-to-video` | 0.0125 | ran |
| `alt_h3max` | `minimax/h3-max/image-to-video` | 0.025 | ran |
| `alt_gemini` | `google/gemini-omni-flash/v1.1/image-to-video` | 0.03 | ran |
| `alt_wan3` | `alibaba/wan-3.0/image-to-video` | 0.05 | **skipped** — still `IN_QUEUE` when polling gave up |
| `fast` (incumbent) | `veo3.1/fast/image-to-video` | **0.15** | prior run |

**$0.68 for three clips.** Every alternative is cheaper per second than the tier
the spike chose, the cheapest by **12×**.

`bytedance/seedance` 2.0 and 2.5 were excluded despite 2.0 being cheapest: both
price per 1000 tokens, and the cost guard cannot reserve against a unit it
cannot predict before the call.

## What the frames show

Recorded as observation pending the owner's rating, whose reading of a clip has
corrected mine three times in this spike.

- **`h3max_turbo`** — address, the club moves back and through, the ball leaves
  and rolls away up the green, and the camera pans off her to follow it. The
  most complete golf sequence the project has produced.
- **`h3max`** — address, backswing, and the ball travels progressively away
  across the back half of the clip while the putter stays down by her feet.
- **`gemini`** — closest to the incumbent's failure. Much address and waggle,
  and the ball barely leaves its starting position.
- **`veo3.1 fast`** — the owner's reading: *"she practices behind it then never
  addresses the ball... she puts, misses the ball and the ball moves."*

**If the owner confirms either MiniMax clip, the central claim of the last two
reports is wrong.** Not "video models cannot render club-ball contact" but
"veo3.1 cannot, and a model costing a twelfth as much can."

## Identity: the cost is unchanged and universal

| Model | Face presence |
|---|---|
| `h3max` | 0.000 |
| `h3max_turbo` | 0.000 |
| `gemini` | 0.000 |
| `veo3.1 fast`, action keyframe | 0.000 |

**Zero across every model.** This confirms the framing conflict is structural
rather than a veo3.1 quirk: a shot composed to show a club striking a ball is
composed not to show a face, whoever renders it. Nothing here weakens D-A or the
proposal to verify identity on the keyframe and the clip on continuity.

## 2026-09-28: the owner rated it, and it was repeated

**`h3max_turbo` rated 4** — *"turbo looks ok"*. **The first club-and-ball clip in
this project the owner has not rejected on physics.** Every previous one was
either rejected outright or rated 4 under a blanket "they all look good" that
later inspection did not support.

`h3max` and `gemini` carry a note and no rating. The owner named turbo and said
nothing about the other two; not selected is not rejected, and recording a
verdict nobody gave would be putting words in the sheet.

### Takes 2 and 3

The n=1 caveat below was the whole weakness of this finding, so two more takes
were run on the same prompt and keyframe. **$0.125 for both**, which is the real
argument for this model as much as the physics is.

| Take | Structure | Face presence |
|---|---|---|
| 10 | address, stroke, ball rolls away, camera follows it | 0.000 |
| 11 | same, including the camera move | 0.000 |
| 12 | same, camera stays with her; **a small dark object sits on the green by her feet from a third of the way in** | 0.000 |

Sent for rating. Pending that, the structure repeated 3 for 3, which is the
first time any club-and-ball format in this spike has held across takes — the
two formats that started this report both passed take 1 and failed take 2.

**The artefact in take 12 matters more than it looks.** It is exactly the class
of defect the identity gate cannot see — not a face, not identity, just a wrong
object on the grass — and at 0.000 face presence the gate has nothing to say
about these clips at all. Whatever this model is worth, it does not reduce the
need for a human on every clip.

## What this does not establish

- ~~n=1 per model~~ — addressed for turbo on 2026-09-28 (3 takes). Still n=1 for
  `h3max` and `gemini`.
- **One shot.** Putting only. `full_swing_impact` and `ball_flight` are
  untested on every alternative.
- **`wan-3.0` never ran.** Its queue timeout is a harness limit, not a verdict.
- **Nothing is known about these models beyond this clip** — no identity
  behaviour on face-forward shots, no refusal rate, no duration stability.

## Carried forward

- Owner ratings on turbo takes 2 and 3.
- `full_swing_impact` and `ball_flight` on turbo — the untested half of the
  question, since everything so far is one shot.
- The face-forward battery on turbo, to check identity is not worse than veo's
  on the shots where a face is actually visible.
- `wan-3.0` with a longer poll window.
- ADR 0003's amendment still waits. This probe could move it again.

---

## 2026-09-28: full swing on turbo, from a portrait keyframe

`full_swing_impact` and `full_swing_follow`, three takes each, **$0.375**.

**Deliberately a harder test than the putt.** There is no full-swing action
keyframe anywhere in the project — `full_swing_address` take 1 turns out to be a
pure portrait with no club and no ball, and it was rated 4 under the blanket
"they all look good", which is one more mark against those take-1 ratings. So
these ran from the **same portrait keyframes the original battery used**, which
is also what the real pipeline has: the master set is 105 portraits.

### veo3.1 pans away from a portrait. Turbo swings.

This is the finding. Given a head-and-shoulders still and a swing prompt, veo3.1
left the framing and fabricated (report §"Why both clips failed"). Turbo cuts to
a wide shot and renders **address over a teed ball, backswing, downswing,
contact, follow-through, and ball flight** — a recognisable golf swing in
sequence.

It also invents **multi-shot edits**: impact take 3 cuts between the swing, a
close-up of the clubface at the ball, a close-up of the turf, the ball in flight,
and a finishing pose. Nobody asked for that.

### The gate has evidence again, and it fired

| Shot | Take | Face presence | Verdict | Min |
|---|---|---|---|---|
| `full_swing_impact` | 1 | 0.300 | indeterminate | 0.9872 |
| | 2 | 0.300 | indeterminate | 0.9894 |
| | 3 | 0.300 | **fail** | **0.9106** |
| `full_swing_follow` | 1 | 0.600 | indeterminate | 0.9481 |
| | 2 | 0.100 | indeterminate | 0.9894 |
| | 3 | 0.100 | indeterminate | 0.9884 |

**Presence is non-zero, unlike every action-keyframe clip before it** (all
0.000), because this model keeps cutting back to shots where the face is
visible. The gate is not blind here.

**And on impact take 3 it failed a clip on identity at 0.9106, well under the
0.9609 threshold — and on inspection it looks right.** The face in the closing
shots reads differently, and the outfit changes across the cuts. After a spike in
which the gate caught nothing the owner cared about, this is the first clip it
flagged that inspection supports. Owner rating will settle it.

### Defects visible without owner input

- **Debris.** Impact take 1 ends in an explosion of dark specks over the grass.
- **Wardrobe drift across cuts.** White tee and skirt in the keyframe, a white
  dress mid-clip, a beige skirt by the end of take 3. The multi-shot editing
  makes this worse, because each cut is a fresh chance to re-render her outfit.
- **Unrequested cutaways**, which is a content-control problem as much as a
  quality one: a shot list that asks for one shot and receives five is not a
  shot list.

### What this does and does not change

**Does:** the club-and-ball constraint is not a property of video generation. It
was a property of veo3.1. A model at **$0.0125/s — a twelfth of the incumbent —**
renders a full swing from the portrait stills the project already has.

**Does not:** say the swings are good. A golfer's eye decides that and the
owner's has not yet been applied. Six takes, one model, two shots.

**D-D may close after all.** These came from portrait keyframes, so on this model
the action-still sourcing problem does not arise. That reverses the 2026-09-25
argument for reopening it, which was based on veo3.1's behaviour.

---

## 2026-09-28: the full battery, a config error of mine, and a wrong mechanism

13 formats × 2 takes on turbo, **26 of 26 generated, zero refusals, $1.625**.
`veo3.1` never managed a clean sweep of the battery; it needed keyframe rotation
and still refused shots.

### The error

`prompt_expansion_mode` was set to `balanced` on both MiniMax slots when they
were added on 2026-09-25. fal's own description: *"How much effort to spend
rewriting the prompt before generation."*

**That is `auto_fix` under another name**, and the `veo3.1` slot a few lines
above in the same file carries the comment explaining why it is never on: *"in a
condition matrix the prompt IS the variable, so a silent rewrite means the cell
you recorded is not the cell that ran."* Every turbo clip from 2026-09-25 to
2026-09-28 ran an expanded prompt while every veo clip ran the literal one, so
that cross-model comparison was never one variable.

Fixed to `disabled` and the battery re-run, another $1.625.

### What the correction changed

| Turbo, identity min | expansion `balanced` | expansion `disabled` |
|---|---|---|
| club-and-ball, below 0.9609 | **10/14** | **4/14** |
| club-and-ball, median | 0.9395 | **0.9680** |
| club-and-ball verdicts | 0 pass, 9 indet, 5 fail | **5 pass**, 7 indet, 2 fail |
| face-forward, below 0.9609 | 4/12 | 6/12 |
| worst clip overall | 0.9146 | **0.7883** |

**Disabling the rewrite more than halved the below-threshold rate on golf shots
and produced the first club-and-ball passes this model has recorded.** It made
face-forward slightly worse and introduced two far worse outliers.

### My explanation for it was wrong, in both directions

I predicted the expansion was adding the unrequested cutaways, and that the cuts
were driving identity drift. A local cut detector (frame-to-frame luma
difference, free, no API) says otherwise.

**The expansion was suppressing cuts, not causing them.** With it disabled the
model cuts *more*: mean 3.46 against 1.92, max 10 against 6. A richer prompt
apparently gives the model enough to fill one shot with; a bare one leaves it
improvising extra shots.

**And cuts do not predict identity drift.** The −0.332 correlation I reported
was computed on the `balanced` half alone. Across all 52 turbo clips it collapses
to **−0.127**, and the bucket pattern is not monotonic — the clips with 6+ cuts
have the *best* median identity of any bucket (0.9690, 2/10 below threshold).

| Cuts | n | Median identity min | Below threshold |
|---|---|---|---|
| 0 | 17 | 0.9641 | 6/17 |
| 1–2 | 12 | 0.9485 | 9/12 |
| 3–5 | 13 | 0.9550 | 7/13 |
| 6+ | 10 | **0.9690** | **2/10** |

The config fix stands on principle regardless — a silent prompt rewrite has no
place in a measurement harness — but it was not right for the reason I gave.

**The cut detector is still worth keeping.** It is the frame-to-frame continuity
instrument D-A calls for, it cost nothing, and it would have caught the
skirt-to-shorts wardrobe change. It is simply not an identity predictor.

### The trade, now measured on both models

- **`veo3.1`** holds identity better (3/13 club-and-ball clips below threshold)
  and **cannot render the golf** — the owner rejected its clips on physics.
- **`h3-max-turbo`** renders golf the owner accepts and is **marginal on
  identity** (4/14 below threshold at its best, 5 pass / 7 indeterminate / 2
  fail), at a twelfth of the price.

Whether "marginal on identity" is *visible* is the owner's call and not the
gate's. Four clips — two the gate failed, two it passed — have gone for rating.
That answer also measures the gate's own accuracy, which is the more valuable
number now that it has one confirmed true positive.

### Standing count of my wrong calls in this spike

Seven. The calibration space, "the distributions cross", the S0.4 dependency,
turning being the worst motion, ADR 0003 being over-constrained, club-and-ball
being beyond video models, and now the cut mechanism. Every one was caught by
measuring rather than by thinking harder, which is the argument for measuring.

---

## 2026-09-28, later: the gate check, and audio nobody had noticed

### The gate's failures are mostly wrong

Four club-and-ball clips went to the owner — two the gate had failed on identity,
two it had passed. **All four came back "They all look OK."**

Scored against every turbo clip the owner has now given a verdict on:

| | Count |
|---|---|
| True positives — gate failed it, owner rejected it | **1** |
| False positives — gate failed it, owner kept it | **2** |
| False negatives — gate passed it, owner rejected it | 0 |
| True negatives | 7 |

**Precision of a gate FAIL: 1 in 3.** Two of the three clips it condemned were
usable, and on this sample it has never wrongly let one through.

That is a sharper statement of D-A than anything in Gate A. The gate is not
useless and it is not a rejector: it has **never missed a bad clip the owner
caught** (0 false negatives in 10), and **two thirds of what it condemns is
fine**. Used as an auto-reject it destroys usable footage at twice the rate it
saves anyone from a bad clip. Used as a *router* — flag for a human, never
discard — it has so far cost nothing and caught the one genuine impostor.

**Auto-reject on identity should not be built.** Routing should.

The one true positive remains the one that matters: the gate found a different
person before any human looked.

### The driver

*"I'd argue the driver in the last video doesn't look real."* Tagged
`club_distortion`, which is one of ADR 0003's original predicted failure modes
and the one that survives the change of model. The gate passed the clip and was
right to: club geometry is not a face, and **nothing in this harness measures
it.** That is the second instrument D-A needs, and it is still unbuilt.

### Every turbo clip has a soundtrack, and it is speaking an unknown language

*"Not sure what language she's speaking."*

**61 of 61 turbo clips carry an AAC audio track. Every veo clip is silent**,
because `generate_audio: false` was set deliberately. The turbo schema has **no
audio on/off control at all** — soundtrack generation is unconditional — so the
spike has generated 61 clips of speech in an unidentified language without
anyone noticing, including in the clips already used as evidence.

**This was found by the owner, not by the harness.** Nothing in the scoring
pipeline looks at audio, and it should: a clip whose soundtrack is wrong is not
publishable however good the picture.

Two consequences, one bad and one good.

**Bad:** the language is wrong for a British persona, and there is no flag to
turn it off. Any turbo clip used as-is needs its audio stripped or replaced.

**Good, and possibly large:** `target_audio_url` pins a supplied soundtrack —
fal's words, *"the original audio replaces the output soundtrack"*. That means
ElevenLabs TTS could be fed **directly into video generation**, and the video
would be generated to that audio rather than lip-synced to it afterwards.

If that works it removes a stage, a provider and a measured identity cost:
S0.8 chose HeyGen at **$0.40/clip** precisely because it was the only lip-sync
model that did not damage identity. A model that takes the audio up front has
nothing to damage. **ADR 0005 flagged exactly this question** — whether native
audio can replace the lip-sync stage — and parked it as a separate run.

Untested. It is the cheapest large thing left: one turbo clip with a pinned
ElevenLabs line, against the existing HeyGen result, for about **7p**.

---

## 2026-09-28: pinning the soundtrack, and what it would remove

Two `talking_head_course` clips generated with the persona's ElevenLabs voice
supplied as `target_audio_url`. **$0.1282 for both, speech included.**

### The audio is pinned bit-exactly

Not "sounds similar" — measured. The clips' audio tracks were extracted and
correlated against the synthesised source:

| | Duration | Correlation with the pinned speech |
|---|---|---|
| pinned take 1 | 5.18 s | **+1.000** |
| pinned take 2 | 5.18 s | **+1.000** |
| an unpinned clip, same format | 5.18 s | −0.017 |

`target_audio_url` does exactly what the schema claims: the supplied track
replaces the model's own, sample for sample, padded with silence past the 3.94 s
of speech. **The unidentified-language problem is solved outright** — any clip
that needs controlled audio can simply be given it.

### Identity is unharmed

| Take | Audio | Presence | Verdict | Min |
|---|---|---|---|---|
| 30 | model's own | 1.000 | indeterminate | 0.9569 |
| 31 | model's own | 1.000 | pass | 0.9641 |
| 40 | model's own | 1.000 | pass | 0.9725 |
| 41 | model's own | 1.000 | pass | 0.9748 |
| **50** | **pinned** | 1.000 | indeterminate | 0.9434 |
| **51** | **pinned** | 1.000 | pass | 0.9767 |

0.9434 and 0.9767 against 0.9569–0.9748 for the same format unvoiced. **Inside
the spread of the unvoiced clips**, and n=2 either side, so the honest reading is
that pinning audio does not obviously cost identity — not that it is free.

Contrast what the current pipeline pays. S0.8 measured every lip-sync model
against identity and chose HeyGen at **$0.40/clip** because it was the only one
that did not take margin off: pixverse cost up to −0.0123 and dropped one passing
clip in three below threshold. **A model handed the audio before generation has
nothing to damage**, because no second model ever touches the face.

### What it would remove, if the mouth matches

| Stage | Now | With pinned audio |
|---|---|---|
| Video | veo3.1 fast, $0.15/s | turbo, $0.0125/s |
| Lip sync | HeyGen precision, **$0.40/clip** | **gone** |
| Identity cost of the sync pass | measured, mitigated by model choice | **not incurred** |
| Providers in the chain | 3 | 2 |

**This is the question ADR 0005 parked** — whether native audio can replace the
lip-sync stage — and the mechanism now measurably works. The one thing not
settled is the only thing that decides it: **whether the mouth moves to the
English words** or to whatever the model intended to say. That is an owner
judgement and the clips have gone for it.

If the answer is yes, S0.8's provider choice and ADR 0005 both need revisiting,
and the per-clip cost of a talking-head piece falls from roughly $0.60 + $0.40 to
about $0.07.

### The mouth does not follow it. ADR 0005 is answered: no.

*"Lip sync is off."*

**`target_audio_url` muxes audio over a finished video. It does not condition
generation.** The schema says so and I read it wrong — "pin to the generated
soundtrack … the original audio **replaces the output soundtrack**, padded with
silence if shorter than the video, without changing playback speed." Every word
of that describes what happens to the audio track. Nothing in it says the video
is generated to the speech. I read "pin" as conditioning; it means attach.

So the lip-sync stage stays, and with it HeyGen and its $0.40. The table in the
previous section is wrong and the claim that a talking-head clip falls to $0.07
is withdrawn.

### What survives

**The audio control is still worth having.** Turbo invents a soundtrack on every
clip with no way to switch it off, and pinning is the only way to govern it.
For a non-speaking clip — a swing, a reaction, B-roll — pinning ambience or
silence replaces an unidentified language with something publishable, for
nothing. For a talking-head clip it is redundant, because the lip-sync pass
overwrites the audio anyway.

**And the cost shape has inverted, which matters more.**

| Stage | Veo pipeline | Turbo pipeline |
|---|---|---|
| Video | $0.60 (4 s at $0.15) | **$0.0625** (5 s at $0.0125) |
| Lip sync | $0.40 | $0.40 |
| Talking-head clip | ~$1.00 | **~$0.47** |

The video was the dominant cost and is now a seventh of it. **Lip sync is now
six times the price of the clip it is applied to.** S0.8 chose HeyGen over
veed ($0.28) and pixverse ($0.16) on identity grounds, correctly, when video
dominated the bill. That trade should be re-examined now that lip sync *is* the
bill — the question is no longer "which sync model is cheapest" but "what is
0.0041 of identity margin worth at six times the cost of the footage".

Not a decision to take here. It belongs with D-B, which already asks whether the
gate should run before or after the lip-sync pass.
