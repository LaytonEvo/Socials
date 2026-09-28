# Setting the wardrobe where it can be set

**Date:** 2026-09-28 · `restyle`, `fal-ai/nano-banana-2/edit`, **$0.24 for 3**.

The previous report established that clothing cannot be set in a video prompt:
the model cuts at about 0.3 s and re-renders her, and the person after the cut
fails identity. So it has to be set in the keyframe. This tests whether a master
still can be re-dressed without losing her.

## It can, and by a wide margin

| Source still | Identity vs master centroid |
|---|---|
| `kf_0_master_017` | **0.9917** |
| `kf_1_master_060` | **0.9926** |
| `kf_2_master_024` | **0.9903** |

Threshold is **0.9609**. The master set's own median is 0.98757, so **the edited
stills score above the median of the images the threshold was built from.**

Face, hair, pose, background and lighting are visually unchanged; only the
garment differs. No invented branding this time, after the negative prompt.

**Generating fresh stills was never the alternative worth trying.** An edit
preserves the face by construction; a new generation only hopes for it, and
would have to clear the threshold on luck. That is why the command scores every
output and prints it: an edit that drifted below 0.9609 would not be a keyframe,
it would be a different woman in the right polo.

## Three of six never ran

`403 User is locked. Reason: Exhausted` on the last three. **The balance is out
again.** Correctly billed as free — $0.24 for three images, nothing for the
refusals — which is the 2026-09-25 billing fix doing its job.

## What this unlocks, and what it does not

**Spec v1 §5's clothing rule is now enforceable**, at the only place it can be:
keyframe generation. A wardrobe becomes a set of master stills rather than a
line in a video prompt, and each one is threshold-checked like any other master
image.

**It also makes the master set a wardrobe.** The same mechanism gives seasonal
kit, a rain jacket, the Florida polo against the English jumper — each a cheap
edit of an existing still at $0.08, each verifiable.

**Untested, and it is the actual point:** whether a video generated *from* one
of these keyframes still opens with a cut. The theory says no, because there is
nothing left for the prompt and the keyframe to disagree about. The theory has
been wrong before. **Two clips, about 13p, settles it** — and until it is run,
this report has only shown that a still can be re-dressed, not that the defect
it was aimed at is gone.
