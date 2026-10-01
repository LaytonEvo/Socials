# ADR 0014 — Keyframes need animation margin, and the gate may be measuring the wrong thing

- **Status**: Part 1 **revised** 2026-10-01 (bar 0.978 → 0.970). Part 3's proposal withdrawn.
- **Date**: 2026-10-01
- **Extends**: ADR 0011 (screen the keyframe), ADR 0012 (unverifiable is not acceptable)

## Part 1 — accepted: a keyframe is not a still

A keyframe is not a deliverable, it is the input to an animation that costs identity.
Measured over nine runs, keyframe score against the worst frame of the best take it
produced:

```
0.0165  0.0166  0.0226  0.0237  0.0245  0.0266  0.0310  0.0328  0.0477
mean 0.0269   median 0.0245   90th 0.0358   max 0.0477
```

To clear `identity_threshold_video` of 0.951 on the worst frame, a keyframe therefore
needs **0.978** at the mean drop, **0.987** at the 90th percentile, and **0.999** at the
worst observed.

The stills threshold is **0.9619**, which leaves no margin at all. That is why five of six
runs failed with a keyframe that had *passed* the stills screen — 0.96239, 0.96576,
0.96662, 0.96707 and 0.96731 all passed as stills and every one produced a take the gate
refused.

**Decided:** `persona.look.identity_threshold_keyframe`, set to 0.978, with a schema
validator that refuses a keyframe bar at or below the video bar. Screening here is about
forty times cheaper than discovering the same answer downstream ($0.035 against $1.46).

## Part 2 — the problem that makes Part 1 insufficient

The bar is **not reachable at a useful rate**. Of roughly 40 keyframes measured, exactly
one reached 0.978. A deliberate hunt of 12 at the 9:16 size produced none, topping out at
0.97028. And at the 90th-percentile drop the bar would be 0.987, above anything this LoRA
has ever produced.

So with the current rule the pipeline refuses almost always — honestly, and cheaply, but
it does not make pieces.

## Part 3 — evidence that the rule, not the pipeline, is the problem

The gate refuses on **the worst single frame**. Comparing the two candidate
discriminators against the 2026-09-30 control set (three different faces, same motions,
synthetic throughout per ADR 0002 Finding 4) and eleven clips of her:

| discriminator | her clips | control clips | separation |
|---|---|---|---|
| **clip mean** | min **0.95178** (n=11) | max **0.94195** (n=3) | **clean, gap +0.0098** |
| **worst frame** | 0.92259 – 0.95010 | frames reach **0.94724** | **overlaps** |

Her clip means separate cleanly from the controls. Her per-frame minima do not — some of
her genuine frames score below frames of a different face.

This is not a surprise on reflection. A minimum over 13 frames is an order statistic: it
falls as you sample more, and the threshold was calibrated against a minimum over 21
frames from a handful of clips. The mean is stable under sample size; the minimum is not.

**So the gate is currently judging on the measure that does not discriminate.**

## What is NOT decided, and why not

Changing the acceptance rule is exactly the change that would make my own runs pass. That
is a conflict of interest, so the evidence goes to the owner rather than into the gate:

- The control set is **three clips**. The threshold report already calls it THIN.
- A clip-mean rule is **more permissive in a way a viewer might notice**: a clip could
  average well and still contain one frame where she looks like someone else. Her takes
  contain frames at 0.922, and a control face reached 0.947.
- A compound rule ("mean above threshold **and** no frame below the control ceiling of
  0.94724") still fails five of eight takes, so it is not a free fix.
- Anything softer — "at most N% of frames below" — means inventing a parameter, which is
  how a threshold stops meaning anything.

`BUILD_ORDER` §3.3 already names the test that settles it:

> If the scorer passes clips a human rejects, **the scorer is the finding**, and Phase 3's
> auto-reject design needs rethinking before it is built.

The converse applies here. If the owner watches these takes and sees Mollie, the scorer is
refusing acceptable work and D-A needs the rule changed. If he sees the face going wrong
where the numbers say it does, the scorer is right and the generation needs to improve.
The frames are in `spike/runs/judge/worst-frames.png` and the clips in
`spike/runs/vt2/`.

## Costs, so the choice is informed

| | |
|---|---|
| keyframe draw (720×1280) | $0.035 |
| 4 takes × 6s at 768P | $0.96 |
| lip sync | $0.50 |
| a keyframe hunt to 0.978, at ~1 in 40 | ~$1.40 |

Spent reaching this finding today: about $2.50 on keyframes and takes, against the $100
monthly ceiling set the same day.


## The owner's verdict, and why Part 3 is withdrawn

Asked to judge the frames the gate refuses on, the owner said:

> "It's her but almost a more AI version of her."

and then:

> "Could also not be fully her."

That is not "the scorer is rejecting acceptable work". The scorer and his eye **agree** that
something is wrong with these takes, so the case for relaxing the rule to a clip mean
collapses: it would have been a change that made failing work pass, justified by a
judgement that did not actually endorse the work.

**`identity_threshold_video` stays at 0.951 and the gate keeps refusing on the worst
frame.** The clip-mean analysis stays on record as a genuine property of the data — her
clip means do separate cleanly from the controls where her per-frame minima do not — but a
measure that separates is not automatically the measure that should decide, and nothing in
the owner's judgement says these clips should ship.

## What "a more AI version of her" measures as

His phrasing points at rendition rather than identity, so fine detail in the face was
measured directly — Laplacian variance inside the detected face box, each crop resized to
a constant 256x256.

**The first attempt was confounded and is retracted.** It reported a 35% texture loss at
the keyframe, measured across faces of 155 to 322 pixels, and texture correlated with face
size at **+0.872**. It was ranking how big the face was.

Re-measured on the band the training stills occupy, 215-275px, mean face size within 7% across
the three populations:

| population | n | texture | vs her stills |
|---|---|---|---|
| her training stills | 16 | 339.9 (sd 102.4) | — |
| keyframes (flux + LoRA) | 20 | 187.8 (sd 51.1) | **-45%** |
| video frames (turbo) | 19 | 150.2 (sd 28.2) | **-56%** |

Welch t ≈ 5.4 for stills against keyframes. The generated face carries roughly **half the
fine detail** of her real stills at the same size, and **most of the loss arrives at the
keyframe, before any video exists**.

## Two hypotheses tested and refuted

**`lora_scale` was not overbaking the texture.** The scale had been tuned to maximise the
identity score, and the identity score cannot see "AI-ness", so overbaking looked like the
obvious culprit. It is not — higher scale is better on *both* axes:

| lora_scale | identity (mean of 3) | texture |
|---|---|---|
| 0.9 | 0.94203 | 166.8 |
| 1.1 | 0.94797 | 171.4 |
| **1.3** | **0.96876** | **192.6** |

**More inference steps were inconclusive.** Steps are free here, since billing is per
megapixel, so 50 steps cost the same as 28. At n=2 per cell the texture metric swung from
60 to 220 within one setting, which is the metric's noise and not an effect. Needs more
draws before it means anything.

## Where this leaves the brief

The binding constraint is the **fidelity of the generation stack**, not the measurement and
not the prompt. Coverage is solved by 9:16, identity margin is understood and configured,
and the remaining gap is that flux+LoRA renders her about half as finely as the stills she
was trained on. The levers left all cost something real:

- a higher-fidelity image model, or a detail/upscale pass on the keyframe (new paid step,
  needs asking first)
- retraining the LoRA, which re-opens the D-C licence question before anything can publish
- accepting a softer look as the house style, which is a content decision rather than a
  technical one


## Part 1 revised: the drop is not a constant, it is a function of the scale

The bar of 0.978 came from drops of 0.0165 to 0.0477. **Every one of those was measured on a
`lora_scale: 1.3` keyframe.** When the scale went to 1.7 the drop changed with it:

| | drops observed |
|---|---|
| scale 1.3 | 0.0165, 0.0166, 0.0226, 0.0237, 0.0245, 0.0266, 0.0310, 0.0328, 0.0477 |
| **scale 1.7** | **0.0113, 0.0174, 0.0177, 0.0181** |

A stronger likeness in the keyframe leaves the video model less room to drift away from it,
so the bar was carrying a penalty the pipeline no longer pays. Two independent signs that
0.978 had become wrong:

1. **It was above the best of 80 draws** across both scales (max 0.97739). A gate that has
   never passed is a stop, not a gate.
2. **A 0.97739 keyframe produced four passing takes out of four** — zero frames below
   threshold, 100% coverage, mins 0.95925 / 0.96606 / 0.95969 / 0.96001.

Revised to **0.970**, which is 0.951 plus the worst drop seen at 1.7 and a little over. At
scale 1.7 that is roughly one draw in two instead of one in 215, so a usable keyframe costs
about **$0.08** instead of **$7.54**.

**This is the revision the original text asked for**, not a relaxation to make work pass:
the bar was written with the criterion *"upward if takes keep failing at it, downward if
they comfortably pass"*, and four of four passing is comfortable. The criterion is unchanged
and the evidence is thin — four drops at 1.7 — so it may have to go back up.

### Why this is a different case from Part 3

Part 3 proposed relaxing the **gate's own acceptance rule** and was withdrawn because the
owner's judgement did not endorse the work it would have passed. This changes a **screening
heuristic that sits upstream of the gate**, and the gate's rule is untouched: those four
takes were accepted by the unchanged rule, measured on the unchanged threshold. The
difference matters — one would have changed what counts as good, this changes only what is
worth attempting.
