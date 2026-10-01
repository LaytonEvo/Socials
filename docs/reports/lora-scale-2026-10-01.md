# LoRA scale: 1.3 → 1.7 — 2026-10-01

The `lora_scale: 1.3` note in `config/providers.yaml` said *"not pushed higher without
evidence: over-weighting a LoRA burns the likeness into every output and costs prompt
control."* That caution was right and it was also never tested. This is the test.

## Why it mattered now

A full run refused after **40 keyframe draws**, none reaching the 0.978 keyframe bar
(ADR 0014). The distribution from those 40 draws, one prompt and one LoRA:

```
mean 0.96224   sd 0.00606   min 0.94803   max 0.97430
```

The bar sits **+2.60 sd** out — about 1 draw in 215, or **$7.54 of draws per usable
keyframe**. That is the cost of sampling a tail. The alternative is to move the
distribution, which is what scale does.

## The sweep

Same prompt, same holdout centroid, texture measured at the size turbo renders from
(downsampled to 768 wide first, since texture correlates with face pixel size at +0.872 —
the confound caught in ADR 0014).

| scale | n | mean | sd | max | ≥ 0.978 | face texture | $ per usable keyframe |
|---|---|---|---|---|---|---|---|
| 0.9 | 3 | 0.94203 | — | 0.95014 | 0 | 166.8 | — |
| 1.1 | 3 | 0.94797 | — | 0.95878 | 0 | 171.4 | — |
| 1.3 | 40 | 0.96224 | 0.00606 | 0.97430 | 0 of 40 | ~100 | **$7.54** |
| 1.5 | 6 | 0.96345 | 0.00657 | 0.97332 | 0 of 6 | — | $2.60 |
| **1.7** | 9 | **0.97111** | **0.00483** | **0.97838** | **1 of 9** | **256.0** | **$0.45** |
| 1.9 | 10 | 0.96743 | 0.00643 | 0.97526 | 0 of 10 | 302.3 | $0.70 |

**1.7 raises the mean and tightens the spread**, which is the combination that matters: the
bar moves from +2.60 sd to +1.43 sd, roughly 1 draw in 13. A **17-fold** reduction in the
cost of a usable keyframe.

**1.9 is worse on both**, so 1.7 is a peak rather than a ramp — which is precisely what the
old note feared about over-weighting. It was found by measuring rather than by staying put.

## It also answers "a more AI version of her"

Texture at 1.7 is **256.0**, above her own training stills at **222.7**, and above 1.3 plus
the clarity-upscaler detail pass at **204.2**.

So the owner's complaint is addressed by a config value rather than by a second paid stage —
and that **removes an unresolved licence from the critical path**, since clarity-upscaler is
built on Stable Diffusion 1.5 plus ControlNet and ESRGAN components whose licensing for
commercial output was never settled. The slot stays configured and marked measurement-only;
it is simply no longer needed by default.

**One caveat a human has to settle.** 1.9's texture of 302.3 is well above her real stills,
which reads as over-sharpening rather than detail — and no metric here distinguishes crisp
from crunchy. 1.7's 256.0 is above her stills too, by less. The numbers say 1.7 is better
than everything else measured; only an eye can say whether it looks like a photograph or
like a sharpening filter.

## What did not work, recorded so it is not retried

**Shortening the clip.** The animation drop is a worst-of-N statistic, so a shorter clip
should have a smaller one. Measured across ten 6-second takes, frame by frame:

| clip length | frames | worst frame |
|---|---|---|
| 2.0s | 4 | 0.95120 |
| 3.0s | 6 | 0.94390 |
| 4.0s | 8 | 0.94222 |
| 6.5s | 13 | 0.94115 |

The curve **flattens almost immediately**. Going from 6.5s to 3s buys 0.00275 and only 2s
buys a useful 0.01006. The damage arrives in roughly the first second of animation and then
plateaus, so it is a step change from the animation process and not accumulating drift.
Shortening shots is not a lever.

## Cost of the finding

| | |
|---|---|
| the 40-draw refusal that prompted it | $1.40 |
| scale sweep, 1.3/1.5/1.7 and 1.7/1.9 confirmation | $1.33 |
| **total** | **$2.73** |

Against $7.54 saved on every keyframe hunt from here.
