# The video threshold, and the comparison that nearly got it wrong

**Date:** 2026-09-30 · **Cost:** $0.1875 · **Closes: D-B**
**Result:** a separate threshold for video frames, **0.951**, beside the stills threshold
of 0.9619.

The video identity test found two false negatives on her talking-head clip — frames
below threshold that are unmistakably her. That is D-B, the open decision from Gate A:
*"recalibrate for lip-synced output, or gate before the pass."* The same argument
applies to video frames generally, not just lip-synced ones.

## I said this would be free. It was not, and the reason matters

The plan was pure computation: 21 already-scored frames of her, no new spend. That is
half a calibration. **A threshold is a boundary between two distributions**, and I had
only one of them — frames of her. Nothing to measure the other side with.

The tempting shortcut was to reuse the existing control set. Doing that gives:

| | n | max |
|---|---|---|
| Her VIDEO frames | 21 | min **0.95487** |
| Control STILLS | 92 | max **0.96778** |

Which says the distributions **overlap** and no threshold separates them. That would
have been a serious finding, and it is **wrong**. It compares video frames against
photographs — the calibration-space error this project has already made twice, once in
the original threshold calibration and once in the lip-sync probe.

## Doing it properly: like against like

Three control faces from `control_v2` — synthetic throughout, as ADR 0002 Finding 4
requires — animated on the same model, at the same duration, sampled at the same 2 fps,
and scored against the same holdout centroid. $0.1875.

| | n | min | mean | max |
|---|---|---|---|---|
| **Her**, video frames | 21 | **0.95487** | 0.96610 | 0.97309 |
| **Controls**, video frames | 28 | 0.89766 | 0.93263 | **0.94724** |

**Clean separation.** An empty gap from 0.94724 to 0.95487 — nothing lands inside it.

| Threshold | False negatives | False positives |
|---|---|---|
| 0.9619 (stills) | **2 of 21** | 0 of 28 |
| **0.951** (midpoint of the gap) | **0** | **0** |

Set at 0.95106, rounded to **0.951**.

**Animating a face lowers its score, whoever it is.** Controls drop from a 0.96778 best
as stills to 0.94724 as video; her own frames drop from a 0.98431 mean as stills to
0.96610. That is why the cross-population comparison was pessimistic — it measured her
*after* the drop against controls *before* it. Same instrument, different population,
meaningless comparison.

## What this changes

- `config/persona.yaml` carries `identity_threshold_video: 0.951` beside the stills
  threshold. Two numbers, because there are two populations.
- `PersonaLook` declares the field rather than relying on the open model, so it is
  documented where it is read.
- `scripts/video_identity_test.py` uses the video threshold. Re-read at 0.951, both her
  clips **hold every frame** and all three control clips are rejected.
- Three tests: that the two thresholds exist and differ in the right direction, that the
  chosen figure separates its own calibration data with no errors either way, and that
  the gap is still narrow.

## How much to trust it

**Not much yet, and the tests say so.** 21 positives, 28 negatives, three control faces,
one video model, one duration. The gap is **0.00763** — real, but thin enough that a
handful of new clips could close it.

What it is good for: replacing a threshold that was measurably wrong for this population
with one measured on it. What it is not good for: wiring an automatic reject to. Gate
A's D-A stands — identity scoring cannot decide publishability — and this changes the
number, not that conclusion.

**The honest version:** this moves the false-negative rate on her core format from 2 in
10 to 0 in 21, on the evidence available. Re-measure before it carries weight.
