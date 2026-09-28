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
