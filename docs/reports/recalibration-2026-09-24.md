# Re-calibration on a widened master set — 2026-09-24

The gate now passes a clean talking-head clip and still rejects a woman the
model invented. That was the open question from
`s05-gate-finding-2026-09-24.md`, and it is answered.

**Master set:** 108 stills (the original 28 plus 80 new), 105 usable
**Control:** the same 16 hard controls, unchanged, so the comparison is honest
**Scorer:** dlib ResNet, unchanged

## The calibration moved the way it should

| | 28 stills | 105 stills |
|---|---|---|
| Threshold | 0.9748 | **0.9609** |
| Overlap | 0.000 | 0.010 |
| AUC | 1.0000 | 0.9994 |
| d′ | 5.79 | 4.88 |
| TPR at 1% FPR | 1.000 | 0.9905 |
| Verdict | EXCELLENT | EXCELLENT |

The threshold fell 0.0139 — more than the 0.01–0.015 that motion and
expression were costing — while separation held. Overlap rose from 0.000 to
0.010, which was the predicted and desired outcome: **0.000 was never a sign
of quality, it was a sign that "her" was defined by 28 near-identical
images.** A definition wide enough to include her talking, turning and lit
differently is an honest one, and it still separates.

The new stills were generated at `--ar 9:16`, which also removes the crop
confound at source: veo takes them unmodified rather than discarding a quarter
of the frame.

## Every clip re-scored against the new centroid

The centroid moved, so old scores could not simply be compared against the new
line — all 28 clips were re-embedded and re-scored.

| Clip | Score | Verdict |
|---|---|---|
| `talking_head_course` | 0.9701 | **PASS** (was a fail at 0.9680/0.9748) |
| `matrix-000` front · medium · golden hour · walking | 0.9806 | PASS |
| 21 further clips from her stills | 0.966 – 0.990 | PASS |
| `matrix-003` three-quarter · **wide** · turning | 0.9181 | **fail** |
| Negative control ×2 (woman invented over a blank landscape) | 0.8626, 0.8457 | **fail** ✓ |
| `walking_fairway` | 0.9761 | **fail — face presence 0.38** |

23 of 28 pass.

## Three things this establishes

**1. The gate is usable.** A talking-head clip — the format the product is
actually built on — now passes, and the margin over the negative controls is
about 0.10 rather than the 0.0018 of headroom the old threshold had.

**2. Widening did not cost separation.** The controls sit at 0.846 and 0.863
against a 0.9609 threshold. The worry that a broader definition of her would
start admitting other women did not materialise, and it was the right thing to
check before trusting the new number.

**3. Wide shots fail for a real reason, not a calibration artefact.** The
three-quarter wide turning shot scores 0.9181 under both calibrations —
essentially unchanged by a threshold that moved 0.0139. Less face in frame,
less to recognise. That is a genuine constraint on shot selection.

## The new finding: face presence, not similarity

`walking_fairway` scores 0.9761, comfortably above the threshold, and **still
fails** — because her face is detectable in only 38% of sampled frames against
a 90% requirement.

This is the second pass condition doing exactly what it exists for. Similarity
is a minimum over *usable* frames, so a clip where she turns away for two
seconds would otherwise report a confident pass on the handful of frames that
happened to show her. The rule catches it.

It also says something real about walking shots: she walks, her head turns,
and for most of the clip there is no face to score. That is a shot-design
constraint rather than an identity failure, and the two must not be conflated
— the clip may be perfectly good footage of her.

## What is still not established

- **Only two battery shots have run.** The other eleven need per-shot
  keyframes from S0.4 and cannot be answered from a fixed portrait.
- **The control set is still 16 images** against 105 master. The harness's
  small-sample warning now applies to the controls alone, and a wider control
  set is the obvious next cheap improvement.
- **The face-presence threshold of 0.9 has never been justified by
  measurement.** It is a sensible default that has now rejected one clip; it
  deserves a deliberate choice rather than inheritance.
