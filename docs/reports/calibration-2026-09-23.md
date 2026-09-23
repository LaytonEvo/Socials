> **SUPERSEDED 2026-09-23 by [`calibration-2026-09-23-corrected.md`](calibration-2026-09-23-corrected.md).**
> Every number below was measured in the wrong space: the calibration used
> pairwise similarities while the scorer compares frames to the master
> centroid. The thresholds here are all too lenient. Kept unedited, because a
> report that quietly acquires correct numbers teaches nobody what went wrong.

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

## Bake-off result — dlib, run the same day

| Backend | Verdict | Overlap | AUC | Threshold | TPR | Dim |
|---|---|---|---|---|---|---|
| dinov2 | MARGINAL | 0.297 | 0.894 | 0.871 | 65.9% | 768 |
| **dlib** | **EXCELLENT** | **0.000** | **1.000** | 0.952 | **100%** | 128 |

Identical master set, identical hard control, same run. dlib separates the
persona from 16 similar young women completely: no overlap, and every one of
her images clears the threshold.

This vindicates the fallback and confirms the diagnosis above. A purpose-built
face recogniser, being invariant to the styling the two sets share, is forced
onto facial geometry — the comparison we actually want. The general visual
embedder was distracted by everything else in the frame.

### Read this result with two reservations

**Perfect separation on a small sample warrants scrutiny, not celebration.**
28 master images and 16 controls. A degenerate result is ruled out — identical
embeddings would push overlap to 1.0, not 0.0 — but perfect separation is
easier to achieve on small samples than large ones. The worst-frame contact
sheet check still applies, and so does a larger control set.

**The discrimination test is not the whole job.** dlib proves it can tell her
from other people. It has not been shown to catch *her, drifted* — and its
invariance to pose, lighting and expression, which is exactly why it won here,
is exactly what might make it forgiving of the drift this system exists to
detect. DINOv2's sensitivity was a liability on this test and could be an asset
on that one.

The two models have opposite blind spots. That question cannot be settled until
there is video to score, in Phase 1.

## The DenseNet variant does not load — 2026-09-23

Measured to settle whether the cleaner-licensed dlib model could replace the
ResNet and retire the FaceScrub caveat. It cannot, at least not as a
configuration change:

```
RuntimeError: An error occurred while trying to read the first object from the
file 'face_recognition_densenet_model_v1.dat'.
ERROR: Unexpected version found while deserializing dlib::add_skip_layer.
```

`dlib.face_recognition_model_v1` expects the ResNet architecture. The DenseNet
uses skip layers and was serialised by BAREL's own dlib build, so loading it
needs BAREL's network definition rather than dlib's stock loader.

**Consequence for the licence question.** Adopting the MIT-licensed variant is
an integration project, not a config edit: BAREL's model-loading code would
have to be vendored, with its own maintenance and its own licence review. The
choice is therefore between

- the ResNet, on an informal public-domain statement with a training-data
  caveat (ADR 0002 Finding 1), usable today; and
- the DenseNet, cleanly MIT, costing integration work and carrying an
  undocumented recognition training set of its own.

The caveat is not resolved by the cheaper route. That is an owner decision, now
an informed one.

**Two things this exposed in the harness**, both fixed: `fetch-models` reported
a failed download on stderr and still exited 0, leaving a config field null and
the real reason invisible for three runs; and the bake-off caught only
`SpikeError`, so dlib's `RuntimeError` destroyed the results of candidates that
had already completed.

## Recommended next step

~~**Run the bake-off against dlib**~~ *(done — see above)*

1. **Switch the primary scorer to dlib** and revisit ADR 0002.
2. ~~**Add the MIT-licensed DenseNet variant to the next bake-off.**~~ *(done —
   it does not load; see above. The licence caveat stands and the cheap route
   to avoiding it does not exist.)*
3. **Keep DINOv2 wired up.** It may earn a place as a secondary drift signal
   precisely because it is sensitive to what dlib ignores.

Original recommendation follows.

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
