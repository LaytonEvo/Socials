# ADR 0007 — First/last-frame conditioning for motion across occlusions

**Status:** accepted, 2026-09-24
**Context:** `docs/reports/occlusion-return-failure-2026-09-24.md`

## The problem

The one reproducible Veo failure measured so far is a face that leaves frame
and comes back. Five coverage-probe clips were assessed by the owner: the two
bad ones are exactly the two where the face leaves and returns; the three good
ones either never lose the face or lose it and never regain it.
`profile_to_camera` discriminates — it turns toward camera through the same
angular range with the face visible throughout, and it is fine.

Nothing carries the head's state across the window where the model cannot see
her, so the return is *reconstructed* rather than continued. The owner's
description: *"her head position on the turn back doesn't match the head
position when she turns away ... her head is tilting the other way on the
return."*

The identity gate cannot detect this, structurally, and three separate fixes
to it on the same day did not change that: every one of the five clips has
healthy identity, including both the owner rejected.

## Decision

Add first/last-frame conditioning as a video provider slot. Supplying a second
still pins the end of the motion, so the model interpolates between two known
states instead of inventing the end. It cannot get the return wrong when the
return is given to it.

The request carries the second still (`VideoRequest.last_keyframe`); config
decides which model id receives it. No model name enters the code (CLAUDE.md
rule 1), and a model that cannot accept two frames answers with a free 422.

## What was verified, 2026-09-24

Against fal's own OpenAPI for `fal-ai/veo3.1/first-last-frame-to-video`:

```
required:  prompt, first_frame_url, last_frame_url
optional:  duration, resolution, aspect_ratio, negative_prompt,
           generate_audio, safety_tolerance, auto_fix, seed
```

Every optional field matches the image-to-video slot already in use, so the
queue contract, billability rules and refusal handling of ADR 0006 carry over
unchanged.

Tiers and published rates, from fal's model listing queried 2026-09-24:

| Endpoint | Audio off | Audio on |
|---|---|---|
| `veo3.1/first-last-frame-to-video` | $0.20/s | $0.40/s |
| `veo3.1/fast/first-last-frame-to-video` | **$0.10/s** | $0.15/s |
| `veo3.1/lite/first-last-frame-to-video` | $0.03/s | $0.05/s |

The Fast tier is configured first: it is the cheapest tier whose quality has
any chance of matching the flagship, and if it holds it also fixes the
economics. The recorded guard price is the **higher** figure ($0.15/s), for
the same reason as the flagship slot — a cost guard that understates lets a
run pass the cap while reporting it is inside it.

## Also found, and not acted on

Two further endpoints address adjacent problems and are recorded here so they
are not rediscovered:

- `veo3.1/extend-video` (video-to-video) continues an existing clip, so the
  model sees real prior frames rather than one still. That is the route to
  pieces longer than a single generation without a cut.
- `veo3.1/reference-to-video` takes reference images, which may hold identity
  better than a single keyframe. Untested against the identity gate.

And a cost finding that stands alone: the flagship slot reserves $0.40/s while
the published audio-off rate for the endpoint in use is $0.20/s, with Fast at
$0.10/s and Lite at $0.03/s. `BUILD_PLAN` Section 9 assumes roughly $60 for a
60-second piece; at Fast rates that is about $6 before discards. The budget
model should not harden until a real invoice settles which figure is charged.

## Outcome — tested 2026-09-24, it works

`turn_away_and_back` on `veo3.1/fast/first-last-frame-to-video`, first and
last frame the same still, 4 s, $0.60 reserved at the guard rate. Generated
first time with no refusal.

```
identity   PASS   min 0.9712 (threshold 0.9609)   coverage 75% (6/8)
per-frame  0.9912 0.9839 -- -- 0.9712 0.9898 0.9930 0.9921
```

Owner: **"that motion works"**. The face does leave frame for two sampled
frames, so the clip exercises the failure rather than avoiding it, and the
frames after the return score higher than those before it — the opposite of
`approach_camera`, where the return frame was the clip's worst.

## Consequences

- **The occlusion-return failure is solved** for any motion whose end pose we
  have a still of. From the existing master set that covers turning away and
  back, looking around, and gesturing and returning to camera.
- **It is not a substitute for S0.4.** Conditioning needs a still of the pose
  the motion *ends* in, so mid-swing, top-of-backswing, follow-through and
  addressing the ball still need the LoRA — to generate their end frames, not
  to fix their motion. Some battery failures were being attributed to the
  LoRA's absence and were in fact this bug.
- **Fast vs flagship, run 2026-09-24: the owner preferred Fast.** Same shot,
  same two stills, same seed, same duration, resolution and audio setting --
  tier the only variable. The flagship take "messed up the motion"; the Fast
  take "works".

  | | Fast | Flagship |
  |---|---|---|
  | Rate (audio off) | $0.10/s | $0.20/s |
  | Guard rate recorded | $0.15/s | $0.40/s |
  | Identity | PASS, min 0.9712 | PASS, min 0.9500 |
  | Coverage | 75% (6/8) | 88% (7/8) |
  | Owner | **works** | **messed up** |
  | File size | 3.83 MB | 3.85 MB |

  **The scores point the wrong way and must not be used here.** Flagship
  scores *lower* on identity precisely because it keeps the face detectable
  for one extra frame of the turn, and that frame is a deep profile -- 0.9500,
  in the same band as `master_010` (0.95041), `approach_camera` (0.9504) and
  `turn_away_hold` (0.9398). Under the old `min` rule flagship would have
  failed and Fast passed, for reasons unrelated to either being better.

  **This is n=1 per tier and Veo is stochastic, so it is not a quality
  ranking.** What it does establish is that the 4x rate gap buys nothing
  visible on this shot, which is enough to default to Fast and revisit if
  quality problems appear. Lite at $0.03/s is untested and the same trial
  would cost $0.12.
- The identity gate is unaffected throughout. It was never what caught this,
  and it said `pass` about the broken clip and the fixed one alike.
