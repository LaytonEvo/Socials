# Identity threshold correction — 2026-09-24

**The scorer works. The gate was mis-set by a sampling artefact in the
calibration harness, not by any property of the persona.**

Feeds item 1 of the Gate A report contents (`docs/BUILD_ORDER.md` §3.3);
it is not the Gate A report, which is S0.9 and still outstanding.

Corrected threshold: **0.9609** (was 0.9701). The flagship talking-head clip
now clears it by 0.0092 — more than one standard deviation of the persona's
own distribution — where it previously "passed" by 0.000005.

This report supersedes the conclusion of `recalibration-2026-09-24.md`, and
corrects a claim I made in the course of reaching it. Both are recorded below.

## 1. What was measured

First calibration where the master and control sets span the same conditions:
both generated at `--ar 9:16` across the same poses, framings, lighting and
settings, so nothing separates them but the face.

| | Master | Control |
|---|---|---|
| Images | 108 candidates, **105 usable** | 94 candidates, **92 usable** |
| Source | `spike/data/master_v2` | `spike/data/control_v2` |
| Rejected | 3, no face detected | 2, no face detected |

Separation, which does not depend on the threshold:

| Metric | Value |
|---|---|
| AUC | 0.9989 |
| d′ | 4.46 |
| Overlap (1 − KS) | 0.020 |
| Verdict | EXCELLENT |

| | n | mean | sd | min | p05 | median | p95 | max |
|---|---|---|---|---|---|---|---|---|
| Her | 105 | 0.98508 | 0.00819 | 0.95041 | 0.97096 | 0.98757 | 0.99300 | 0.99445 |
| Strangers | 92 | 0.93391 | 0.01402 | 0.88942 | 0.90966 | 0.93585 | 0.95264 | 0.96676 |

## 2. The bug

An FPR estimated from *n* different-face samples moves in steps of **1/n**.
With 92 controls the achievable rates are 0, 1.09%, 2.17%, and so on.

The configured target was `target_fpr: 0.01`. **There is no threshold with an
FPR between 0% and 1.09%**, so "FPR ≤ 1%" was satisfiable only at FPR = 0 —
which forces the threshold above the single highest-scoring control image.

| Target | Threshold | Her rejected | Strangers accepted |
|---|---|---|---|
| 0.0100 (requested, unresolvable) | 0.9701 | 5 (4.8%) | 0 (0.0%) |
| 0.0109 (1/92, the finest expressible) | **0.9609** | **1 (1.0%)** | **1 (1.1%)** |

The gate was set by one control image and a target the sample size cannot
express. Every threshold in 0.9583–0.9609 gives the identical 1-and-1 result,
so the corrected value is not finely balanced.

**Nothing warned.** The existing check fires only when the target is *missed
from above* (`fpr > target_fpr`); here granularity over-achieved it — 0.0 is
comfortably inside 0.01 — so the record came back `warnings: []`. A number that
looks principled and is an artefact, which is the same failure mode as the
pairwise/centroid mismatch in `calibration-2026-09-23-corrected.md`.

Fixed in `8c649e6`: `calibrate()` clamps an unresolvable target to 1/n, warns,
and quantifies the recall the clamp saved. It now reports:

> target_fpr 0.0100 is finer than 92 different-face samples can express
> (resolution 1/92 = 0.0109); calibrated at 0.0109 instead. Holding the finer
> target would have cost 2.9% of the same-face images for no measurable gain
> in false accepts.

## 3. A claim I got wrong

On first reading the matched-set numbers I reported that *"her worst image
(0.95041) now scores below the closest stranger (0.96676) — the distributions
genuinely cross"*, and treated it as a finding about how distinctive the
persona is. **That overstated it.** Here is every image in the crossing zone:

```
0.95041  HER        <- her single lowest still
0.95050  stranger
0.95121  stranger
0.95121  stranger
0.95438  stranger
0.95438  stranger
0.95502  stranger
0.95822  stranger
0.96094  HER
0.96305  HER
0.96641  HER
0.96676  stranger   <- reviewed by the owner: "Not her, keep it in"
```

The crossing is **two images out of 197**. Remove those two and there is a
clean, empty gap from 0.95822 to 0.96094. At p02/p98 the two distributions do
not overlap at all. The persona is distinctive enough; the threshold was wrong.

## 4. Why those two images — a face-angle effect

| Image | Score | Character |
|---|---|---|
| `master_010` (`b1_10.png`) | 0.95041 | Near-profile, face turned down and away, largely obscured by hair |
| `control_073` (`c7_06.png`) | 0.96676 | Tight frontal close-up, face filling the frame, genuinely similar colouring |

Both outliers are the same mechanism in opposite directions: **at the tails,
face angle and face size move the score more than identity does.** dlib reads
frontal geometry, so a near-profile of her scores low and a frontal close-up of
someone similar scores high.

**`master_010` stays in the master set.** Removing it would raise the floor and
bias the gate toward frontal stills — which would then reject exactly the
turned-away footage that `walking_fairway` consists of. The low tail is a real
operating condition, not a bad image.

## 5. Validation of the operating point

Leave-one-out, so no image is judged against a boundary drawn from itself:

| Band definition | Floor | Ceiling | Her auto-rejected | Strangers auto-accepted | Sent to review |
|---|---|---|---|---|---|
| min / max | 0.95041 | 0.96676 | 1 (1.0%) | 1 (1.1%) | 5.1% |
| p01 / p99 | 0.96103 | 0.95898 | 2 (1.9%) | 2 (2.2%) | 0.0% |
| p02 / p98 | 0.96332 | 0.95559 | 3 (2.9%) | 2 (2.2%) | 0.0% |

The quantile floors sit *above* the ceilings — the inversion is the clean gap
from §3. A single threshold at 0.9609 is therefore sufficient; a three-band
gate would buy roughly half the error rate for 5% human review volume, and is
recorded here as available rather than adopted.

Note the first row is only meaningful under leave-one-out. Scored against
bands drawn from the same data it reports zero errors, which is circular:
the boundaries *are* `min(positives)` and `max(negatives)`.

## 6. Clips re-scored at 0.9609

| Clip | Identity | Face presence | Verdict at 0.9701 | Verdict at 0.9609 |
|---|---|---|---|---|
| `battery-talking_head_course` | 0.970085 | 1.00 | PASS by 0.000005 | **PASS by 0.0092** |
| `battery-walking_fairway` | 0.976068 | 0.38 | fail (presence) | fail (presence) |
| `matrix-000-front-medium-golden_hour` | 0.980644 | 1.00 | PASS | PASS |
| `matrix-003-three_quarter-wide-midday` | 0.918114 | 1.00 | fail | fail |
| `01a0cef9` | 0.977673 | — | PASS | PASS |
| `01a0ceff` | 0.982236 | — | PASS | PASS |
| `01a0cf00` | 0.965656 | — | fail | **PASS** |
| `01a0cf2a` | 0.980644 | — | PASS | PASS |

**7 of 8 pass on identity; 6 of 8 overall.** The negative controls — the woman
Veo invented over a synthetic landscape — still score 0.846 and 0.863, far
below the line. The gate did not become permissive; it stopped being
needlessly strict.

## 7. Still open

- **`face_presence >= 0.9` has never been justified by any measurement.** It is
  now the *only* thing failing `walking_fairway` (0.38), and it was chosen by
  assertion. It needs the same treatment this threshold just received.
- **The control set is a proxy.** Midjourney lookalikes are not the negative
  this gate will face in production — Veo drifting off-model from her keyframe
  is. Calibrating against owner-labelled Veo output is the measurement that
  would make the threshold operationally meaningful. Not urgent now that
  nothing is broken, but it is the honest yardstick.
- **dlib FaceScrub licence** (ADR 0002) — owner decision, unchanged.
- **Eleven battery shots** still need S0.4's per-shot keyframes.
- **Five unverified `no_media` suspects** (`m_002`, `m_006`, `m_012`, `m_016`,
  `m_018`); only `m_004` is confirmed.

## 8. Rejected on the evidence

- **Redesigning the persona** to give her a distinguishing feature. Raised when
  the crossing looked structural; §3 shows it is two images. 105 stills stay.
- **Buying an InsightFace licence.** AUC 0.9989 says the scorer is not the
  bottleneck — and a *better* face recogniser is a *more invariant* one, which
  on synthetic lookalikes could score them higher, not lower.
- **DINOv2.** Already measured MARGINAL (overlap 0.297) because it keys on
  styling; the matched control set shares styling deliberately, so it would
  do worse here, not better.
