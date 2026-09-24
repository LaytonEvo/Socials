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

## 5. Sampling rate: a prediction I got wrong

I predicted faster sampling would not change the verdict, on the grounds that
each frame would still score ~0.98. That was wrong.

| Clip | 2 fps | 8 fps |
|---|---|---|
| `approach_camera` | 0.9757 **pass** | 0.9504 **fail** |
| `glance_back` | 0.9326 fail | 0.9534 fail |
| `look_down_and_up` | 0.9465 fail | 0.9513 fail |
| `profile_to_camera` | 0.9845 pass | 0.9823 **pass** |
| `turn_away_hold` | 0.9825 indeterminate | 0.9398 **fail** |

At 8 fps the bad clip fails. But it fails **on pose, not motion**: the 0.9504
frame is at 1.375s, mid-turn and near-profile — the same pose penalty that
makes `master_010`, a near-profile still, her lowest-scoring reference image
at 0.95041. Nearly the same number, for the same reason.

The worry that this would also reject good turning footage is not borne out
on this sample: `profile_to_camera` turns through the same range and still
passes at 0.9823, because its turn is gradual and the face stays detectable
throughout. `turn_away_hold` changed to a fail and has not been assessed by
eye, so whether that is correct is unknown.

So: raise the sample rate — it is local compute and costs nothing — but it is
**not** a motion detector and must not be described as one. n=5.

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
