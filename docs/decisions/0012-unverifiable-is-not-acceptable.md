# ADR 0012 — Unverifiable is not acceptable

- **Status**: accepted
- **Date**: 2026-10-01
- **Extends**: ADR 0011 (screen the keyframe, not the render)
- **Changes**: the severity doctrine in `app/pipeline/acceptance.py`, and take selection

## Context

The five-run pass-rate battery reported **4 of 5 accepted, an 80% pass rate**, and a cost
model was built on that number. Reading the verdicts rather than the exit codes showed what
those four acceptances were:

| run | verdict | why |
| --- | --- | --- |
| 1 | ACCEPTED | identity `[REVIEW]` — face in 4 of 11 frames (36%) |
| 2 | ACCEPTED | identity `[REVIEW]` — face in 3 of 11 frames (27%) |
| 3 | ACCEPTED | identity `[REVIEW]` — **no detectable face in any frame** |
| 4 | ACCEPTED | identity `[REVIEW]` — face in 5 of 11 frames (45%) |
| 5 | REFUSED | identity `[BLOCKING]` — 4 of 10 frames below threshold |

**The only run where identity could be measured is the one that failed.** The verified pass
rate was 0 of 1, not 4 of 5. Run 3 was accepted having never shown the gate a face.

The cause was a severity decision made when the gate was built: thin or absent coverage was
filed as `REVIEW`, on the reasoning that "cannot say" is not "wrong". That reasoning is
defensible in the abstract and wrong in practice, because `REVIEW` is non-blocking — so the
gate systematically accepted precisely the shots it could not vouch for, and reported a
pass rate for "cannot say".

A second finding came out of the same investigation. Take selection and the gate were
measuring different things:

- `takes.measure()` counted a frame as covered on a bare face detection. `embedder.read()`
  additionally refuses `TOO_SMALL` (under 80px) and `MULTI_FACE` ("which one is she is not
  answerable"). On run 5's takes `measure` reported 63–98% coverage where only 26–39% of
  frames could be embedded — median face 63–69px against the 80px floor.
- Identity was not scored on takes at all. Selection ran on head roll and coverage, and
  identity was first measured in the gate, *after* the $0.50 sync. Run 5's chosen take was
  already failing identity before the sync; the refusal was available for free beforehand.

## A third calibration-space error, recorded

The first attempt at the take rule sampled at 6 fps to "look harder". Every one of twenty
takes failed, including the four whose renders the gate passed at 2 fps.

The video threshold of 0.951 was calibrated as the **minimum of a 21-frame sample at 2 fps**
(`docs/reports/video-threshold-2026-09-30.md`), set just under an observed min of 0.95487.
A sample minimum is an order statistic: sampling three times as densely reaches further
into the tail and finds frames the calibration never saw. Comparing a dense sample against
a sparse-calibrated threshold is the same class of mistake this project made twice before —
once in the original threshold calibration, once in the lip-sync probe — and this is the
third. `GATE_SAMPLE_FPS` is now a named constant and take measurement defaults to it.

## Decision

1. **Unmeasurable identity is `BLOCKING`.** Zero coverage and coverage below
   `MIN_COVERAGE` both refuse. `REVIEW` is reserved for what no measurement could settle —
   lip sync, where mouth-to-word match is not recoverable from frames at any sampling
   rate — and is not a place to file a measurement that failed to happen.
2. **`measure()` counts coverage as frames the embedder could read**, given an embedder, so
   selection and the gate agree about what is scorable.
3. **Takes are scored for identity before the sync**, against the same reference and
   threshold the gate will apply, at the gate's own sampling rate.
4. **`best_take()` treats identity as a constraint and head roll as a preference.** Among
   takes the gate would accept, the steadiest wins. If none would be accepted it refuses,
   and the refusal names which constraint failed — thin coverage means she moved out of
   frame and the motion prompt is the lever; frames below threshold mean the generator
   drifted off her face.
5. **No margin is added for the sync.** The measured delta is a few thousandths in either
   direction (+0.0041 once, −0.003 another). A margin would be invented rather than
   calibrated.

## Consequences

Replaying the real takes through the new rule:

| run | new rule |
| --- | --- |
| the single shot the owner approved | **picks** take.mp4 — 100% coverage, 0 frames below, roll 4.75 |
| pass-rate run 1 | refuses — no take over the 60% coverage floor (best 50%) |
| pass-rate run 2 | refuses — best take 1 of 10 frames below |
| pass-rate run 3 | refuses — no take over the coverage floor (best 50%) |
| pass-rate run 4 | refuses — best take 2 of 6 frames below |
| pass-rate run 5 | refuses — best take 2 of 10 frames below |

It accepts the one genuinely verified shot and refuses the five whose acceptance was an
artefact, **before** the sync. That is $2.50 of sync spend the battery would have wasted.

- **The honest pass rate is about 1 in 6** (the approved shot, of six full runs), not 80%.
  `docs/reports/pass-rate-2026-10-01.md` carries the correction.
- **The pipeline will now refuse often.** That is the state of the pipeline being reported
  rather than a new fault. The lever is the shot: she moves out of frame or turns away
  during the five seconds, which is a motion-prompt and shot-design problem, not a
  threshold problem.
- **Task 3.4's retry cap cannot be set from this.** At roughly 1 in 6 a cap of 3 is a coin
  flip. The cap needs either a better shot design or a measured rate after one.

## What this does not establish

Whether a *different* take would have saved run 5 is still unknown. Its three losing takes
are 26–39% scorable — too thin to compare — and claiming the pick was wrong on those
numbers would repeat the error of reading one scorable frame in ten as "passes every
frame". The defensible claim is that no take in run 5 was acceptable, not that a better one
was passed over.
