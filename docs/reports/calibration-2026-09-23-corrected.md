# Calibration on real images, corrected — 2026-09-23

Supersedes [`calibration-2026-09-23.md`](calibration-2026-09-23.md) **in full**.
Every number in that report was measured in the wrong space. See "The bug that
invalidated the first report" below; the qualitative findings mostly survived,
one did not, and the one that did not changes an owner decision.

Run on a GitHub runner (`.github/workflows/calibrate.yml`), because the
development environment blocks huggingface.co and cannot load DINOv2.

**Master set:** 28 Midjourney stills of one invented persona, all 28 usable
**Controls:** two sets, same master both times — only the definition of
"a different person" changes.

## Result — does control difficulty matter?

Scorer `dinov2:facebook/dinov2-base:crop0.25-yunet:d768`, both controls:

| Control | Verdict | Overlap | AUC | Threshold | TPR | Neg mean |
|---|---|---|---|---|---|---|
| Easy — mixed ages and sexes, 16 faces | EXCELLENT | 0.036 | 0.998 | 0.800 | 96.4% | 0.457 |
| Hard — young women of the same type, 16 faces | ADEQUATE | 0.107 | 0.951 | 0.878 | 89.3% | 0.769 |

Yes, it matters, and this is the finding that survived the correction intact.
Nothing changed but the negatives: overlap triples, and the mean similarity of
"a different person" jumps from 0.457 to 0.769. The easy set was mostly
middle-aged men and children, separable on age, sex and hair length without
reference to facial identity at all.

**Every identity number this project reports is meaningless without the control
set it was measured against.** Running both was worth more than running either.

## Result — the bake-off, on the hard control

| Backend | Verdict | Overlap | AUC | Threshold | TPR | Dim |
|---|---|---|---|---|---|---|
| `dlib` ResNet | EXCELLENT | 0.000 | 1.0000 | 0.9748 | 100% | 128 |
| `dinov2` | ADEQUATE | 0.107 | 0.9509 | 0.8779 | 89.3% | 768 |
| `dlib-densenet` | **DID NOT RUN** | — | — | — | — | — |

`dlib-densenet` fails to deserialise under dlib's standard loader
(`Unexpected version found while deserializing dlib::add_skip_layer`); it needs
BAREL's own network definition. It is reported as a row rather than omitted,
because a candidate that vanishes from a comparison table is a candidate nobody
remembers to reconsider.

## Is dlib's perfect separation real?

Aggregates cannot answer that, so `cli.py inspect` scores every image against
the master centroid and names the two that decide it:

```
her weakest    0.9766  master_026.jpg
closest other  0.9523  control_005.jpg
margin         +0.0243        → Narrow
```

**Narrow, not clean.** `overlap 0.000 / AUC 1.0000` is true and reads far more
comfortable than the underlying picture: 0.0243 between her worst image and the
nearest stranger, on 28 + 15 images.

Three things follow, and they are the caveats that matter more than the verdict:

1. **The threshold sits 0.0018 below her weakest image.** 0.9748 against
   0.9766. The 100% true-positive rate is achieved with almost no headroom, so
   any genuine image slightly worse-lit or worse-angled than `master_026.jpg`
   will be rejected. Expect real rejections in production; that is the
   instrument being strict, not broken.
2. **dlib found no face at all in `control_012.jpg`,** so it scored 15 controls
   where DINOv2 scored 16. The bake-off's "identical image selection" was not
   quite identical. An image that cannot be embedded cannot be a false accept,
   which flatters the negatives very slightly.
3. **The same images under DINOv2 cross outright:** her weakest 0.7050 against
   a stranger at 0.8665, margin **−0.1615**. No threshold separates them.

## The bug that invalidated the first report

`score.py` compares every frame to the master **centroid**. `calibrate` built
its distributions from **pairwise** similarities. Two different scales.
Centroid similarity runs systematically higher — averaging cancels noise a
single other image still carries — so every threshold sat below where the
scorer reads. Too lenient, by the size of that gap.

Not theoretical. The first pass put dlib's threshold at 0.9521 while the
closest stranger scores 0.9523 against her centroid: **that control image, a
different woman, would have passed as her.** Corrected, the threshold is 0.9748
and she does not.

**No statistic caught it and none could have.** Overlap, AUC, d′ and TPR were
all computed inside the pairwise space, all internally consistent, and all
meaningless outside it. A self-consistent instrument reading off the wrong
scale. It surfaced only because `inspect` printed per-image centroid scores
next to a threshold from the other space and the two numbers nearly touched.

Fixed in `_calibration_distributions`: positives are now leave-one-out
centroid similarities, negatives are control-against-master-centroid, and both
calibration paths go through one helper. The regression test asserts the
invariant end to end rather than checking which function gets called.

### What the correction changed

| | First pass (wrong space) | Corrected |
|---|---|---|
| dlib, hard control | EXCELLENT, thr 0.9521 | EXCELLENT, thr **0.9748** |
| DINOv2, hard control | **MARGINAL**, overlap 0.297, TPR 65.9% | **ADEQUATE**, overlap 0.107, TPR 89.3% |
| DINOv2, easy control | ADEQUATE, overlap 0.063 | EXCELLENT, overlap 0.036 |
| Reported sample size | 378 positive "pairs" | 28 positives |

Two consequences beyond the numbers:

**The ranking held.** Both scorers were mismeasured the same way, so dlib still
wins decisively. The decision to switch to dlib was not made on a broken
comparison — but that is a fact established after the fact, not a defence of
having made it.

**DINOv2 is a materially better fallback than ADR 0004 recorded.** It reads
ADEQUATE, not MARGINAL: TPR 89.3% rather than 65.9%. ADR 0004's option 3
("revert to DINOv2 and accept MARGINAL") was described as the one no threshold
can rescue. That is no longer true, and it changes the owner's licence
decision: reverting is now a real option rather than a fig leaf.

**The sample-size warning became honest.** The first pass counted 378 positive
pairs from 28 images and reported that as the sample. Those pairs were never
independent observations. The corrected run reports 28, and the small-sample
warning now fires where it should.

## Caveats that still stand

- **Small sample.** 28 master, 16 control. The harness says so on every run.
- **The master set is synthetic,** so within-set similarity partly measures the
  generator's consistency, not identity (ADR 0002 Finding 3).
- **Stills, not video.** No temporal drift, no lip-sync, no compression.
- **The decisive control image has now been checked by eye.** The owner
  confirmed 2026-09-23 that `h_005.jpg` — the stranger scoring 0.9523, closest
  of the 15 — is clearly a different woman. That is the check the statistics
  could not do: the scorer and the eye agree on the hardest case, so the
  0.0243 margin is measuring identity rather than an artefact of how the two
  sets were built.
- **The master side of that pair has not been checked.** `m_026.jpg` is her
  weakest image at 0.9766 and the threshold sits 0.0018 under it. If that
  render is slightly off-model, the threshold is anchored to a bad image and
  should be higher; if it is a good likeness, the anchor is honest. Worth two
  minutes before the threshold is written to config.

## What would change the verdict

A larger hard control set, or a master set with more variation. Both are cheap
and neither has been run. `master_026.jpg` and `control_005.jpg` are the two
files to open first — the whole margin rests on them.
