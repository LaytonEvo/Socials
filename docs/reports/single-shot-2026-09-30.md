# Single shot, first accepted run — 2026-09-30

The deliverable the owner asked for after calling a halt: **one unbroken shot**, judged by
a gate rather than by me looking at it.

## Result

**ACCEPTED**, 0 blocking, 1 for review.

| measurement | value | threshold | |
| --- | --- | --- | --- |
| keyframe (still) | 0.97841 | 0.9619 | pass |
| take, animated | mean 0.96250, min 0.95249 | 0.951 | pass |
| after lip sync (A5) | mean 0.96224, min 0.95393 | 0.951 | pass |
| final, disclosed | mean 0.96285, min 0.95457 | 0.951 | pass |
| frames scorable | 10/10 | ≥60% coverage | pass |
| frames below threshold | 0 of 10 | 0 | pass |
| head roll, chosen take | 4.11° over 41/41 frames | — | 100% coverage |
| streams | video + audio, 5.208s | both | pass |
| disclosure | overlay + manifest | required | pass |

The one open item is honest and not closable by measurement:

> **[REVIEW] lip sync**: whether the mouth matches the words is not measurable here. A
> human must watch and listen.

That is for the owner to judge. I am not calling the sync good from a contact sheet again.

## What was actually wrong

Not the video model, not the lip-sync model, not the prompt's golf content — all of which
I changed in turn. The keyframe was off-identity at 0.94753 against a 0.9619 threshold,
and every stage below it behaved exactly as calibrated. Full reasoning in
`docs/decisions/0011-screen-the-keyframe-not-the-render.md`.

## Spend

| item | cost |
| --- | --- |
| 4 screened keyframes (diagnostic) | $0.2800 |
| 4 takes | $0.2500 |
| voice line (reused) | $0.0052 |
| lip sync | $0.5000 |
| failed sync attempts on the bad take | $0.0000 (not billed) |

## Still open

- The sync quality itself needs a human watch — the REVIEW item above.
- `MIN_TAKE_COVERAGE` is set to 0.6 by analogy with the gate's `MIN_COVERAGE`, not from
  measurement. It is a floor chosen to exclude a 34% take, not a calibrated number.
- D-C (dlib FaceScrub licence) still blocks publishing regardless of this result.
