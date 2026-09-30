# Does her face survive being animated?

**Date:** 2026-09-30 · **Cost:** $0.1875 · **Clips:** 3 × 5 s on `minimax/h3-max-turbo`
**Answer: yes — and the gate is now the weaker half of the pair.**

Everything measured before today was stills. This is the question Phase 1 exists to
answer, and `BUILD_PLAN`'s Phase 1 gate says a failure here ends the project.

Method: three LoRA-generated keyframes, each animated for 5 s, every clip sampled at
**2 fps** and every frame scored against a centroid built from the **19 held-out stills
only**. Keyframes were reused from the LoRA evaluation rather than regenerated — they
only need to be her, and paying twice for that proves nothing.

## Results

| Clip | Frames | Coverage | Mean | **Min** | Verdict |
|---|---|---|---|---|---|
| `talking_head` | 10 | 1.00 | 0.96569 | **0.95487** | dips below 0.9619 twice |
| `walking` | 10 | 1.00 | 0.96677 | 0.96349 | holds every frame |
| `golf_swing` | 10 | **0.10** | 0.96355 | 0.96355 | **cannot say** — face in 1 frame of 10 |

Threshold 0.9619; the ceiling a perfect likeness reaches on this split is 0.98431.

**The minimum is the number that matters, not the mean.** A clip averaging 0.966 that
drops to 0.93 for four frames is a clip with a visible glitch in it. None of these do
that.

## 1. Identity survives animation

Both measurable clips are visibly her throughout — checked frame by frame on a contact
sheet, not inferred from the scores. `walking` holds above threshold in all ten frames,
which is notable because walking was the **worst motion axis** in the spike's condition
matrix (2 of 6 at the time, and five of the seven indeterminates were wide or walking).

On the evidence available, **the Phase 1 gate's central question has a positive answer.**

## 2. The gate produced two false negatives, and that is the finding

`talking_head` dropped below threshold at t=3.0 s (0.95864) and t=4.0 s (0.95487).

**Both frames are unmistakably her.** The lowest-scoring frame sits beside the
highest-scoring one in `docs/evidence/` and the difference is a slightly turned head and
a different expression — nothing a person would hesitate over.

I predicted the dips would be mouth-open frames, on the theory that speech distorts the
face. **That was wrong** — the lowest frame has a closed mouth. It is head pose and
expression, which is worse news, because those are unavoidable in any talking clip.

This is **D-B with evidence behind it at last**. The threshold was calibrated on still
photographs of a person holding still. Video frames are a different population: motion
blur, interpolated intermediate poses, compression. Judging them against a
stills-calibrated threshold rejects frames that are fine.

**Consequence for task 3.4.** An auto-reject wired to this threshold would discard
usable talking-head footage — the persona's core format — at roughly **2 frames in 10**.
Gate A's D-A already said identity scoring cannot decide publishability. This says the
same thing from the other direction: it is not only blind to non-face defects, it is
actively wrong about faces under motion.

## 3. The golf swing is unmeasurable, not failed

Nine of ten frames contain **no detectable face**. Looking at them, the reason is
mundane and correct: through a golf swing she looks down at the ball, the visor brim
covers her eyes, and her hair crosses her face on the follow-through. That is what a
golf swing looks like.

So the clip is not bad. **It is unjudgeable by this instrument**, which is exactly the
spike's central finding reproduced in a new place: *the gate is silent where it cannot
see a face*, and silence reads as consent.

**My own reporting got this wrong first.** The script's original verdict column called
this clip **"PASS every frame"** — true, over the single frame it could score, and
completely misleading. A coverage floor now runs *before* the score check, and the
verdict reads `CANNOT SAY — face found in 1/10 frames`. The bug was mine and it is the
same shape as the failure it was describing.

## 4. The trademark problem is worse in video

The Nike swoosh that appeared on the keyframe is present on the visor in **every frame**
of the golf clip, prominently, and nobody prompted it. A still can be discarded; a
five-second clip with a trademark on it for its whole duration is a publishing risk with
no cheap fix. This belongs with D7 (counsel) and task 3.2's policy guard.

## What this does not establish

- **Three clips.** One take each, one model, one duration. This is a signal, not a rate.
- **No audio.** Turbo generates a soundtrack unconditionally and none was listened to.
- **No lip sync.** The HeyGen pass costs identity `+0.0041` on stills; untested here.
- **Nothing about 9:16 or platform cuts**, which reframe and may crop the face further.

## What I would do next

1. **Recalibrate against video frames** (D-B). The data to do it now exists: 30 scored
   frames, of which two are known false negatives. A threshold set on generated video
   frames rather than on still photographs is the single highest-value fix, and it costs
   nothing to compute.
2. **Three more takes per condition**, $0.19, to turn this signal into a rate.
3. **A coverage rule, not a score rule, for swing content.** Face presence below ~0.6 on
   a clip means a human must watch it. Gate A already proposed this as routing rather
   than detection; this run is the first hard evidence for the number.
