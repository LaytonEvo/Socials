# Calibration on real images — 2026-09-23

First measurement this project has produced from anything other than synthetic
fixtures. Run on a GitHub runner (`.github/workflows/calibrate.yml`), because
the development environment blocks huggingface.co and cannot load DINOv2.

**Scorer:** `dinov2:facebook/dinov2-base:crop0.25-yunet:d768` (ADR 0002)
**Master set:** 28 Midjourney stills of one invented persona, all 28 usable
**Controls:** two sets, same master both times — only the definition of
"a different person" changes.

## Result

| Control | Verdict | Overlap | AUC | Threshold | TPR | Neg mean | Neg max |
|---|---|---|---|---|---|---|---|
| Easy — mixed ages and sexes, 15 faces | ADEQUATE | 0.063 | 0.997 | 0.700 | **92.3%** | 0.428 | 0.761 |
| Hard — young women of the same type, 16 faces | **MARGINAL** | **0.297** | 0.894 | 0.871 | **65.9%** | 0.721 | 0.902 |

## What it says

**Against a realistic control, DINOv2 only marginally separates this persona
from other young women.** Overlap nearly five times worse, AUC down from 0.997
to 0.894, and the true-positive rate collapses from 92% to **66%**.

That last figure is the one that matters. At a threshold holding false
positives to 1%, **one in three genuine images of her fails to score as her** —
on stills, in near-identical conditions, which is the easiest case this system
will ever see. The clip pass rule gates on the worst frame of ten; at this
separation almost nothing would pass.

Her images average 0.874 similarity to each other. Other young women average
0.721, and reach 0.902 — higher than many genuine pairs of her, whose minimum
is 0.561. The distributions genuinely cross.

## Why the easy control was so misleading

Nothing changed but the negatives. The easy set was mostly middle-aged men and
children, separable on age, sex and hair length without reference to facial
identity at all. It produced a flattering overlap and a threshold of 0.70 that
would have passed a great deal of drift.

Running both was worth more than running either.

## The likely cause, which contradicts ADR 0002's reasoning

ADR 0002 chose DINOv2 partly on the argument that a general visual embedder has
no trained-in invariance to pose, lighting, expression and hair — the axes a
persona drifts along — whereas a face recogniser is built to ignore exactly
those.

That argument appears to cut the other way here. The hard control is
stylistically identical to the master set: same golden-hour light, same
photographic treatment, similar hair, similar framing, because it was generated
from similar prompts. A general visual embedder sees *the same kind of image*
and scores it high. A face recogniser, being invariant to that styling, would
be forced onto facial geometry — which is the comparison we actually want.

The reasoning was sound about video drift and wrong about this discrimination.
Both effects are real; this result says the second dominates.

## Recommended next step

**Run the bake-off against dlib**, which ADR 0002 kept wired up as exactly this
fallback: `python -m scripts.spike.cli bake-off --backends dinov2 dlib`.

It is free, it is one command, and the harness already stamps every measurement
with the embedder that produced it so the two cannot be confused. Blocked only
on recording dlib's licence, which is an owner decision, and on the landmark
predictor file.

If dlib separates materially better, ADR 0002 should be revisited. If neither
does, the consequence ADR 0002 already anticipated applies: automated identity
scoring becomes advisory rather than gating, human review load in Phase 3 rises
substantially, and BUILD_PLAN task 3.4's auto-reject design needs rework before
it is built.

## Caveats, both of which make this result FLATTERING

- **The master set is narrow.** 28 images but almost all warm golden-hour, hair
  down in 27 of 28, no full body, no true profile — Midjourney's reference image
  dominated the scene instructions. Uniformity inflates how similar her images
  are to each other, so the real positives are lower than measured.
- **The hard control may be harder than reality**, being generated from
  deliberately similar prompts. But it is the right direction of error: the
  drift a video model produces looks like this, not like the easy set.

## Also raised by this data

The pass rule gates a clip on its single worst frame. Against a scorer with
this distribution that may be too strict — one bad frame kills an otherwise
sound take. Gating on the 5th percentile instead is worth considering before
Phase 3 builds auto-reject on top of it.
