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

`min` has been replaced. Candidates were measured across 31 clips scored at
both 2 and 8 fps:

| Rule | Verdict flips 2→8 fps | Different woman caught | Owner-confirmed good failed |
|---|---|---|---|
| `min < T` (old) | **3** | 2/2 | **2/2** |
| `p25 < T` | 1 | 2/2 | 0/2 |
| `mean < T` | 0 | 2/2 | 0/2 |
| `frac_below > 50%` | 0 | 2/2 | 0/2 |
| **`run_below > 40%`** | **0** | **2/2** | **0/2** |

`mean < T` scores as well as the winners and was rejected anyway: the
threshold is calibrated on the distribution of *individual* image-to-centroid
similarities, and the mean of several frames has a different, narrower
distribution. Comparing it to that threshold repeats the calibration-space
error of `calibration-2026-09-23-corrected.md`. Counting frames against the
threshold uses it in the space it was measured in.

The chosen rule is the **longest contiguous run of readable frames below the
threshold**, as a share of readable frames, allowed up to 40%. On this data it
is indistinguishable from the plain fraction — the below-threshold frames in
these clips are contiguous anyway — and the preference rests on two things
the data does not settle. It stays stable down to 0.4 where the fraction flips
at 0.33, so it is stricter at equal stability; and contiguity is the
distinction everything else in this report turns on, since scattered dips are
a head passing through an extreme pose and recovering, while a sustained run
is the identity going and not returning. The synthetic drift fixture, which
models gradual drift the real clips do not contain, is caught by the run rule
and missed by `frac_below > 50%`.

Effect on the 31 clips: **7 verdicts change, every one from fail to pass**, on
clips whose lowest frame was a brief pose dip of 4–33%. No verdict now differs
between 2 and 8 fps. Both different-woman clips still fail at both rates.
`turn_away_hold` passes at both rates, which was the false reject that
prompted the change.

The allowance rests on two confirmed-bad clips and is correspondingly
provisional; it is recorded in the code as a bracket rather than a derived
value.

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
