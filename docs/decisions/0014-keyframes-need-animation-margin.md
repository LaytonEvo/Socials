# ADR 0014 — Keyframes need animation margin, and the gate may be measuring the wrong thing

- **Status**: proposed — the second half needs the owner (D-A)
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
