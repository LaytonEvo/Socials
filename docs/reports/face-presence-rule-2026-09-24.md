# The face-presence rule — 2026-09-24

**`face_presence >= 0.9` was rejecting good footage.** It has been replaced by
a three-valued verdict in which low coverage makes a clip *indeterminate*
rather than failed.

Companion to `identity-threshold-correction-2026-09-24.md`. Same shape of
defect: a number that had never been derived from anything, doing a job it was
not measured for.

## 1. What the rule was

A clip passed only if **both** held: its lowest per-frame similarity cleared
the calibrated threshold, **and** a face was found in at least 90% of sampled
frames. The 0.9 was set by assertion. It was never calibrated, and after the
threshold correction it was the only thing still failing a good clip.

## 2. The clip that exposed it

`battery-walking_fairway-flagship-0`, sampled at 2 fps:

| Frame | Time | Status | Similarity |
|---|---|---|---|
| 0 | 0.0s | ok | 0.9914 |
| 1 | 0.5s | ok | 0.9899 |
| 2 | 1.0s | ok | 0.9761 |
| 3–7 | 1.5–3.5s | **no face** | — |

Every frame that showed her face cleared the threshold comfortably. Frames 3–7
show her **from behind, walking away down the fairway** — which is the shot the
prompt asked for. The footage is good. The old rule failed it at 37.5%
presence.

Note the shape: a **contiguous tail**, not a hole. The rule's original
rationale was a clip "with a two-second hole in it" — but a hole implies the
face returns. This is a camera move that completes.

## 3. Why coverage cannot be a pass mark

**A missing face is uninformative.** When the detector finds nothing, we cannot
distinguish:

- she turned away from camera (good footage), from
- her face melted or morphed so the detector could not lock on (bad footage).

Both produce zero vectors. Nothing in an embedding can separate them. So
absence is *missing evidence*, not evidence of a problem, and a rule that fails
on absence discards good clips at whatever rate the shot list turns people
away from camera — which for golf is often.

Seeing a bad frame is different. That is positive evidence, and it still fails
the clip outright whatever the coverage.

## 4. The rule now

| Verdict | Meaning | Action |
|---|---|---|
| **fail** | A frame we looked at scored below the threshold | Regenerate |
| **indeterminate** | Nothing we looked at failed, but too little was seen to certify | Human looks |
| **pass** | Enough was seen, and all of it cleared | Proceed |

This keeps what the old condition was actually protecting — a clip is never
silently certified on the frames where it happened to behave — and stops
calling that certification a failure. It also fits the pipeline the plan
already requires: `CLAUDE.md` mandates a named human approver before anything
publishes, so an indeterminate lane costs nothing new. It only separates
"regenerate this automatically" from "someone glance at this".

Coverage is sufficient when **either** every sampled frame was usable (nothing
went unseen, so clip length is irrelevant) **or** presence ≥ `min_face_presence`
and at least `MIN_USABLE_FRAMES` frames were usable.

## 5. Choosing the floor, and being clear about what the evidence supports

All 30 clips generated in the spike were scored:

| Presence | Clips |
|---|---|
| 100% | 26 |
| 87.5% | 3 |
| 37.5% | 1 (`walking_fairway`) |

The evidence **brackets** the floor to `(0.375, 0.875]` and does not pin it
further: every value in that range gives identical verdicts on all 30 clips.
`0.5` is chosen within the bracket on the principle that a verdict should rest
on a majority of the frames sampled. That is a judgement, not a measurement,
and it is recorded as such in the code.

`MIN_USABLE_FRAMES = 4` is a second, absolute floor: at 2 fps a ratio alone can
be satisfied by two adjacent frames, which is one moment seen twice. It applies
only when coverage is partial, because it exists to bound *unseen* frames.

Being wrong here is cheap in a way the old rule was not: it costs a human
glance, not a discarded clip.

## 6. Effect

| | Old rule | New rule |
|---|---|---|
| pass | 24 | 24 |
| fail | 6 | 5 |
| indeterminate | — | 1 |

**Exactly one clip changes verdict**, and it is the one that was wrongly
failed. No clip that should fail now passes. The three clips at 87.5% still
fail — on identity (0.8626, 0.8457), which is the different-woman clip and its
copies, exactly as they should.

## 7. Still open

- The floor rests on 30 clips from one provider, 29 of which had near-total
  face coverage. A shot list with more wide and turned-away footage would
  populate the middle of the range and could pin it properly.
- `pass_rate_by_condition` now reports `pass_rate` and `pass_rate_of_judged`
  side by side. Which denominator is right depends on whether the
  indeterminates are a property of the shot or of the model, and that is not
  yet known.
