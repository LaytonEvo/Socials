# Feeding the model real golf: what exists, what it costs, what it changes

**Date:** 2026-09-25 · **Status:** research only. Nothing implemented, no new
provider added. Needs an owner decision and, if taken, an ADR.

The owner asked: *"How can we feed the model golf swing data in order to correct
this?"* — after finding that in `battery-putting_stroke-fast-2` the club misses
the ball and the ball moves anyway.

## The literal answer is no, and the useful answer is not

**Veo 3.1 cannot be given golf data.** It is a closed hosted model behind fal's
queue API. There is no fine-tune hook, no LoRA slot, no reference-motion input.
Every lever the spike has used — prompt, keyframe, first/last frame — constrains
*appearance at a moment*. None constrains *motion between moments*, which is
where the defect lives.

But a different class of model on the same account does exactly what the question
asks. It is called **motion transfer** or **motion control**: supply a reference
video that carries the motion and a still that carries the character, and the
model maps one onto the other. **The swing mechanics come from real footage
rather than from the model's idea of a swing.**

That addresses the defect at its actual level. A driving video of a real putt has
causality in it because the events really happened: the club strikes the ball and
therefore the ball moves. The model is not asked to infer that relation.

## What is on fal today

Queried 2026-09-25 against `fal.ai/api/models`, prices from
`api.fal.ai/v1/models/pricing`, schemas from fal's queue OpenAPI. Not added to
`config/spike.yaml` — recording what was read, per the rule that a provider is
verified against its own docs before an adapter exists.

| Endpoint | $/s | Licence | Schema read |
|---|---|---|---|
| `fal-ai/bytedance/dreamactor/v2` | **0.05** | not listed | **no** — see below |
| `fal-ai/wan-motion` | **0.06** | commercial | yes |
| `fal-ai/one-to-all-animation/14b` | 0.06 | commercial | no |
| `fal-ai/scail-2` | 0.10 | commercial | no |
| `fal-ai/kling-video/v3/standard/motion-control` | 0.126 | commercial | yes |
| `fal-ai/kling-video/v3/pro/motion-control` | 0.168 | commercial | no |
| `moonvalley/marey/motion-transfer` | $2.00 / video | commercial | no |

For scale, the tier this spike chose — `veo3.1/fast/image-to-video` — is
**$0.15/s** at the guard figure. **Wan Motion is 2.5× cheaper than what the
pipeline already pays**, and Kling standard is cheaper too.

`dreamactor/v2` is the cheapest listed and its schema would not fetch: the
request died twice with `ws_closed_mid_exchange` through the agent proxy. Its
licence is also not listed in the catalogue. **Unverified on both counts, so it
is not a candidate until someone reads its docs.**

### The two schemas that were read

`fal-ai/wan-motion` — required `video_url`, `image_url`:

| Field | Meaning |
|---|---|
| `video_url` | the driving video, *provides the motion* |
| `image_url` | the reference image, *provides the character appearance* |
| `adapt_motion` | default true — adapts the driving motion to the reference image's body |
| `enhance_identity` | default false — preprocesses the reference image for identity preservation |
| `prompt` | optional steer |

`fal-ai/kling-video/v3/standard/motion-control` — required `image_url`,
`video_url`, `character_orientation`. It also takes an `elements` object for
**facial consistency binding**: a frontal image plus 1–3 further angles.

That last field is worth noting. It is built for the exact problem this project
has, and the master set has 105 images to fill it from.

## Where the driving footage comes from

This is the decision that matters more than the model choice.

1. **Film it yourself.** A phone on a tripod, the owner putting, chipping,
   swinging. **Free, and it is the only option with no rights question and no
   personal-data question** — the footage is the owner's own, and the output
   carries the persona's face rather than theirs. ADR 0002 Finding 4 kept real
   faces out of the control set because they would be Article 9 biometric data;
   the owner filming themselves is a different situation, and the face does not
   survive into the output regardless.
2. **Licensed stock golf footage.** Costs money, and the licence has to be read:
   a growing number of stock licences now specifically forbid use as AI training
   or conditioning input. Do not assume a standard licence permits this.
3. **Footage of real golfers from the internet.** No. Copyright, likeness, and a
   practical problem on top of both: motion transfer carries build and
   mannerisms, so a recognisable player's swing may stay recognisable.

**Option 1 is better than the other two on every axis**, including quality — the
footage can be shot in the framing the shot actually needs, at the tempo wanted,
for as many takes as it takes.

## What it changes about the pipeline

The shape stops being *prompt → clip* and becomes *film a real action once →
transfer it to the persona whenever needed*.

That means a small reusable library: a drive, an iron, a chip, a putt, a
reaction, a walk. Shot once, used for every piece afterwards. Per-clip cost falls
against the current tier, and the physics stops being regenerated — and
re-gambled — on every take. The 2-of-13 reject rate on club-and-ball shots is a
yield problem that this removes at the source rather than sampling against.

## What it does not solve, and one thing it may

**Identity becomes the whole risk.** The face arrives from a still and must
survive the transfer. Both leading candidates ship a dedicated mitigation —
`enhance_identity` on Wan, `elements` facial binding on Kling — which is good
evidence that drift is the known hard part. The spike already has the instrument
to measure it: the same dlib gate, the same 0.9609 threshold, the same
`identity_verdict`.

**It may close D-D rather than reopening it.** The previous report argued the
project needs action-framed stills of the persona, which it does not have. Motion
transfer needs a *character* image and takes the body and action from the driving
video — `adapt_motion` explicitly adapts the motion to the reference image's
body. If that holds, the portrait master set is sufficient after all and the
sourcing problem disappears. **Stated as a possibility, not a finding.** It is
one of the things the test below would settle.

## Proposed test, and what it needs from the owner

The cheapest decisive experiment:

1. **The owner films roughly six seconds of a real putt** on a phone — side-on,
   still camera, whole body in frame, including the strike and the ball leaving.
2. Run it through `fal-ai/wan-motion` (~$0.36) and
   `fal-ai/kling-video/v3/standard/motion-control` (~$0.76) against the same
   persona still. **About $1.15 total.**
3. Score both on the existing identity gate and put them in front of the owner.

Three things get answered at once: whether real motion transfers intact, whether
her face survives it, and whether a portrait still is enough character reference.

**Not started.** Both are new paid providers on the account, which needs asking
first, and adopting either is a stack deviation that needs an ADR.
