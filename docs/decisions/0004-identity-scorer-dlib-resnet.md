# ADR 0004 — Identity scorer: dlib ResNet, and what it costs us

- **Status:** Accepted 2026-09-23 by the owner ("switch to dlib and test the DenseNet variant too"). **Conditional on an unresolved licence question — see "The bill" below.**
- **Date:** 2026-09-23
- **Deciders:** Layton (owner), supervising engineer; the licence condition touches counsel under D7
- **Supersedes:** [ADR 0002](0002-face-embedding-model-licence.md), which chose DINOv2 on 2026-09-22
- **Evidence:** [`docs/reports/calibration-2026-09-23.md`](../reports/calibration-2026-09-23.md)
- **Relates to:** `docs/BUILD_ORDER.md` amendment A3 (an embedder change invalidates every calibrated threshold)

## Context

ADR 0002 chose DINOv2 on an argument, not a measurement. The argument was
Finding 2: face recognisers are trained to be invariant to pose, lighting,
expression, age and hairstyle, which are exactly the axes along which a persona
drifts, so a recogniser would say "same person" precisely where we need it to
say "she has drifted". A general visual embedder has no such invariance trained
into it.

That reasoning was available a day before any data was. Spike 0 exists to stop
arguments like it from surviving into the build, and it worked as intended: one
day later the measurement contradicted it.

## What the measurement said

Both scorers were calibrated on identical image sets — 28 master images of the
persona, 17 control images of *similar* young English women rather than random
strangers. Identical inputs matter here: the control set was prepared once with
a single embedder so that every candidate scored the same selection of images.

| Scorer | Overlap | AUC | TPR @ 1% FPR | Verdict |
|---|---|---|---|---|
| dlib ResNet (128-d) | 0.000 | 1.0000 | 1.000 | EXCELLENT |
| DINOv2 (768-d), hard control | 0.297 | — | 0.66 | MARGINAL |
| DINOv2 (768-d), easy control | 0.063 | — | 0.92 | ADEQUATE |
| dlib DenseNet (128-d) | — | — | — | did not load |

Two findings, and the second is the one that generalises.

**The face recogniser separates and the general embedder does not.** Finding 2
was wrong as applied here, and the reason is worth stating precisely rather than
quietly dropping: invariance to pose and lighting is a *cost* only when the
project needs to detect drift along those axes. It is a *benefit* when the
project needs to detect that a different person has been rendered under the same
pose and lighting — which is the failure mode that actually threatens this
pipeline. The invariance argument identified a real cost and missed the larger
benefit sitting next to it.

**Control-set difficulty dominated everything.** The same DINOv2 model reads
ADEQUATE against random people and MARGINAL against women who look like her —
a difference in the test set, not the scorer. Had the easy control been the only
one built, DINOv2 would have passed on evidence that a "92% true-positive rate"
figure would have carried into the gate report unchallenged. **Every future
identity number in this project is meaningless without the control set it was
measured against.** That is now a property of the harness: `prepare-set` records
which set was used and `CalibrationMismatch` refuses to score across a change.

## The bill

The dlib ResNet is not free of problems; it trades a measurement problem for a
licence problem.

Its weights are public domain by the author's explicit statement. Its training
corpus, roughly 3M faces, includes **FaceScrub, which is non-commercial**. The
permissive statement on the weights does not cure the corpus behind them — the
licence-stacking trap recorded as Finding 1 in ADR 0002.

`face_recognition_densenet_model_v1` (MIT via BAREL) was the route around this
and **it is not a drop-in**: it fails to deserialise under dlib's standard
loader (`Unexpected version found while deserializing dlib::add_skip_layer`)
because it needs BAREL's own network definition. Adopting it means vendoring
that definition, and its recognition-stage training data is undocumented
anyway — so it reshapes the provenance question rather than removing it. It is
still registered as `dlib-densenet` and the bake-off still reports it as a
DID NOT RUN row rather than silently omitting it.

**This is an owner decision and it is open.** Three ways it can go:

1. **Accept the FaceScrub caveat**, on the reading that the author's
   public-domain release governs the artefact we actually use. Cheapest, and
   a position counsel should be asked to confirm rather than an engineer.
2. **Buy a commercial licence** (InsightFace offers one). Clean, costs money
   and procurement time, and is now justifiable with numbers rather than a
   guess — which was the point of measuring first.
3. **Revert to DINOv2** and accept MARGINAL, with a manual review step behind
   every borderline take. This is the option a threshold cannot rescue: at
   0.297 overlap, no cut point exists that keeps good takes and rejects bad
   ones.

Until this resolves, dlib is the scorer for **spike measurement only**. It must
not carry into a published render, because a published render is the commercial
use the caveat is about.

## Consequences

- `config/spike.yaml` sets `embedder.backend: dlib`; all three backends stay
  registered and the bake-off compares them in one command.
- Every threshold measured under DINOv2 is void (amendment A3, enforced in
  code, not by discipline).
- **Perfect separation on 45 images is a claim under test, not a result.**
  `cli.py inspect` reports every image's similarity to the master centroid and
  names the two that decide it — her weakest frame and the closest stranger.
  A margin that rests on one image is not a separation.
- ADR 0002's Finding 4 is untouched and still outstanding: a control set of
  real faces is biometric data of real people. Ours is synthetic, which is why
  it does not arise — and that is a reason to keep it synthetic, not an
  accident to preserve by luck. **Still not in the D7 counsel scope.**

## What would overturn this

A larger hard control set that closes the gap, or per-image inspection showing
the margin rests on one or two images. Both are cheap. Neither has been run at
scale yet, and a result this clean on a sample this small deserves the scrutiny
before it earns the confidence.
