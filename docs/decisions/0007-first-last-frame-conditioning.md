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

## Consequences

- If the Fast test shows the return is correct, the shot-list constraint in
  `DRAFT_SHOTS` lifts and the battery's reaction and swing shots come back
  into scope for reasons unrelated to S0.4's LoRA.
- If it does not, the constraint stands and the finding is that the failure is
  deeper than conditioning can reach.
- Either way the identity gate is unaffected. It was never what caught this.
