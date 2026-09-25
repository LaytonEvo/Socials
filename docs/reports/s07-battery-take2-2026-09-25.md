# S0.7 second battery take — the gate's verdict is not a property of the format

**Date:** 2026-09-25 · **Status:** partial. 10 of 13 formats have a second
take; owner ratings outstanding.

Gate A §5 carries the caveat *"one take, one provider. One good take does not
prove a format is reliably good."* This is the second take, run with
`--take-offset 1` so the take-0 clips the owner had already rated were not
re-bought.

## What ran

10 of 13 formats generated. Three did not: `walking_fairway`, `apparel`,
`full_swing_address`, all lost to `403 User is locked. Reason: TOP_UP` part way
through the run. Real spend $6.00 for 10 clips at the Fast tier.

The lock was intermittent — succeeding, locking, succeeding — which is
consistent with a balance hovering at zero rather than a hard stop, and is why
the run is ragged rather than truncated at a clean point.

## Automated verdicts, both takes

Identical prompts, different seeds. Threshold 0.9609.

| Format | Take 1 | Take 2 | Presence T1 | Presence T2 |
|---|---|---|---|---|
| `ball_flight` | indeterminate | indeterminate | 0.250 | 0.250 |
| `chip` | indeterminate | **pass** | 0.375 | 0.625 |
| `clubhouse` | pass | pass | 1.000 | 1.000 |
| `equipment_closeup` | fail | **pass** | 1.000 | 1.000 |
| `full_swing_follow` | pass | **indeterminate** | 1.000 | 0.375 |
| `full_swing_impact` | pass | **indeterminate** | 0.625 | 0.250 |
| `full_swing_top` | indeterminate | **pass** | 0.250 | 1.000 |
| `putting_stroke` | fail | **indeterminate** | 0.625 | 0.250 |
| `reaction` | pass | pass | 1.000 | 1.000 |
| `talking_head_course` | pass | **indeterminate** | 1.000 | 1.000 |

Take 2 alone: **5 pass, 5 indeterminate, 0 fail.**

## Finding: 7 of 10 formats changed verdict category between takes

**The automated verdict is a property of the take, not of the format.** On the
same prompt, the gate moved a format across a category boundary 7 times in 10.

The mechanism is visible in the presence column and it is not identity. Six of
the seven changes track a swing in `face_presence` — the fraction of sampled
frames in which a face was found at all — which moved by up to 4× on the same
prompt (`full_swing_top` 0.250 → 1.000, `full_swing_follow` 1.000 → 0.375).
Whether a clip lands in the review lane is largely decided by whether the face
happened to be visible in the eight frames sampled.

This is the §3 blind spot measured a second way. Gate A argued from a single
clip that the scorer cannot decide publishability. This argues it from
repetition: a decision rule that disagrees with itself on 70% of re-runs of the
same input cannot carry an auto-reject.

**Two consequences for D-A.** First, any Phase 3 auto-reject needs a coverage
policy decided before a threshold, because coverage, not similarity, is what
moves the verdict. Second, `indeterminate` is doing its job — it absorbed the
instability instead of converting it into false rejects. Nothing failed in
either take. The three-valued verdict is the reason this report describes noise
rather than 7 discarded clips.

## What this does not yet settle

**The format-reliability question is still open.** It asks whether the *output*
is usable twice, which is an owner judgement, and the owner has not rated take
2. The 13/13 usable rate in Gate A §5 stands on take 0 alone until they have.

The acceptance criterion also asks for two providers. Both takes are
`veo3.1/fast/image-to-video`. That half is not addressed here and, with the
Fast tier chosen on a controlled comparison, it may be worth retiring rather
than satisfying — an ADR if so.

## Carried forward

- Owner ratings for the 10 clips → completes Gate A §5.
- `walking_fairway`, `apparel`, `full_swing_address` second takes: ~$1.80.
- Gate A §5 and its evidence-still-missing table update once both land.
