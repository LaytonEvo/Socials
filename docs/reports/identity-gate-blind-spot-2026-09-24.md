# A clip the gate passed and a human rejected — 2026-09-24

**The owner watched `coverage-approach_camera`, said it was clearly AI, and it
had been marked `pass`.** This report records why, because the reason is
structural and not fixable by tuning anything calibrated today.

## 1. Identifying the clip

The owner supplied a fal CDN URL and then a request id. Three independent
routes agree:

| Route | Result |
|---|---|
| MD5 of the downloaded file | `1a3231cc4fe5` = `coverage-approach_camera-flagship-0` |
| Request id `01a0d30e-cf23-71c0-a675-ec292bc0db29` | same ref in `run.jsonl` |
| Correlation of the clip's first frame against each keyframe | **0.9994** vs `master_024.png`, others 0.72–0.79 |

The third was needed because the keyframe was not recorded. It is now
(`keyframe_selected`, commit `1377d98`).

Scored verdict: **`pass`**, identity 0.9757, presence 87.5%.

## 2. The defect

Owner's description: *"when she turns all the way around to look at the
camera, the movement back isn't right ... her head position on the turn back
doesn't match the head position when she turns away ... her head is tilting
the other way on the return."*

The clip does not execute its prompt (`walking toward camera from the middle
distance`). Veo produced a turn away and back instead, from a close-up
keyframe that made an approach impossible.

## 3. Why the scorer said `pass`

Not a calibration error. The per-frame scores are honest: in every frame
sampled, her face **is** her face. Four separate reasons the gate cannot see
what the owner saw, in increasing order of how fundamental they are.

**(a) It scores a face crop.** Body, limbs, hands and scene are outside the
crop and therefore outside the measurement entirely.

**(b) It compares each frame to the master centroid, never to the frame
before it.** A discontinuity between two frames is invisible because that
comparison is never performed — not too coarsely, but not at all.

**(c) dlib aligns the face before embedding.** `compute_face_descriptor`
takes the 5-point landmarks and canonically aligns the chip, which cancels
roll. **Head tilt is mathematically absent from the descriptor.** A face
recogniser is *built* to be invariant to pose, because its job is "same
person regardless of how they hold their head" — and that invariance is
precisely what makes it blind to this defect.

**(d) The defect happens where there is no face at all.** Decisive:

```
1.375s   last frame before occlusion
1.50s ── no face
2.00s ── no face          the entire turn-back
2.125s   already facing camera
```

No face from 1.50s to 2.00s. By 2.125s the return is complete. Whatever goes
wrong, goes wrong in a window containing no face to measure.

## 4. An instrument that did not work

Roll is recoverable from the landmarks the embedder computes and discards, so
it was extracted at 8 fps to test the tilt-reversal hypothesis.

```
0.00s  -14.9deg        1.375s  +6.7deg   (rotating +3.5deg/frame)
                       [ no face 1.50-2.00s ]
2.125s  +4.7deg        3.875s  +6.2deg   (flat)
```

**It did not catch the defect.** Roll is continuous across the gap
(+6.7° → +4.7°): no jump, no reversal at the boundary. The whole-clip claim
holds — she starts tilted −14.9° and ends +4.7° — and angular velocity dies
across the gap (+3.5°/frame to ~0), but the deceleration happens inside the
occlusion, unobserved. Consistent with a teleport and equally consistent with
a normal turn. The measurement cannot separate them, per §3(d).

Recorded because a negative result on a plausible instrument is worth as much
as a positive one, and because roll-from-eye-landmarks also conflates roll
with yaw once the head turns, which limits it independently.

## 5. Sampling rate, and why `min` is the wrong statistic

I predicted faster sampling would not change the verdict. That was wrong, and
so was the recommendation I drew from it. Both are corrected here.

| Clip | Owner's judgement | 2 fps | 8 fps |
|---|---|---|---|
| `approach_camera` | **clearly AI** | 0.9757 pass | 0.9504 **fail** |
| `turn_away_hold` | **fine** | 0.9825 indeterminate | 0.9398 **fail** |
| `profile_to_camera` | not assessed | 0.9845 pass | 0.9823 pass |
| `glance_back` | not assessed | 0.9326 fail | 0.9534 fail |
| `look_down_and_up` | not assessed | 0.9465 fail | 0.9513 fail |

At 8 fps the bad clip fails — and so does a good one. One accidental catch
bought at the price of one false reject is not an improvement, and
**raising the sample rate is withdrawn as a recommendation.**

The mechanism is the same in both directions, and it is not about quality:

```
turn_away_hold at 8 fps
  0.875s   0.9687
  1.000s   0.9398   <- fails. Last frame before the face is lost
  1.125s   no face  ... and stays gone, as the shot intends
```

The failing frame is **the last frame before the detector loses the face**,
which is by construction the most extreme pose in which a face was still
found. Eyes closed, near-profile, mid-turn: good footage of the persona
turning away.

That generalises into the real finding:

> **The clip verdict is `min` across sampled frames, and `min` only decreases
> as you sample more.** Denser sampling gets closer to the instant the face
> disappears, which is the most extreme pose, which is the lowest score. So
> the verdict is decided by the single *least* informative frame in the clip,
> and which frame that is depends on the sampling rate rather than on the
> clip.

This is a defect in the rule, independent of the threshold and of the
embedder. Three measurements now point at one cause:

| Image | Score | What it is |
|---|---|---|
| `master_010` | 0.95041 | her lowest-scoring reference still — near-profile |
| `approach_camera` @8fps | 0.9504 | failing frame — near-profile |
| `turn_away_hold` @8fps | 0.9398 | failing frame — near-profile |

**Pose dominates the signal at the tails, and the gate cannot tell "she
turned her head" from "this is not her".** Same invariance problem as the
head-tilt finding in §3(c), seen from the other side.

`min` should be replaced by a statistic that is stable under sampling
density. The candidate worth measuring first is the **fraction of usable
frames below threshold**, which is stable, interpretable ("11% of the frames
we could read did not look like her"), and does not hand the verdict to one
frame. Weighting frames by frontality is a second option, since near-profile
frames carry the least identity information and currently carry the most
weight. Neither is implemented; both need the same treatment the threshold
got, on data rather than assertion.

## 6. What this means for the gate

`pass` is the wrong word, and that is the immediate fix. It means *"identity
verified in the frames sampled"* and it was read as *"this clip is good"* —
the reading it invites. Everywhere it surfaces it should say what it measures.

The human rating step is not optional. It is the only mechanism that caught
this, and the coverage probe's footer was written to skip the rating prompt
because the golf failure tags did not fit. That was backwards.

`BUILD_PLAN` task 3.4's auto-reject design is premised on identity scoring
being able to decide a clip is publishable. It cannot, and no threshold makes
it able to. A motion check is a different instrument — frame-to-frame
consistency or optical flow over the whole frame, not the face — and it has
to work across occlusions, which is the hard part.

## 7. Credit where due

This was found by a human watching the video. Every automated instrument
available, including two built specifically to look for it, said the clip was
fine.
