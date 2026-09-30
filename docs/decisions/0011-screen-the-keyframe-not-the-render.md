# ADR 0011 — Screen the keyframe, not just the finished render

- **Status**: accepted
- **Date**: 2026-09-30
- **Supersedes**: nothing. Extends Amendment A5 (re-score after lip sync).

## Context

Three days of work went into changing video models, lip-sync models and prompts because
the finished pieces did not look like Mollie. The owner's reading — *"the videos are
getting worse not better"* — was correct, and the cause was not any of the things being
changed.

With the acceptance gate in place, the chain was measured stage by stage for the first
time:

| stage | score (mean) | threshold | verdict |
| --- | --- | --- | --- |
| keyframe (still) | 0.94753 | 0.9619 still | **fails by 0.0144** |
| take (animated) | 0.94239 | 0.951 video | fails |
| synced | 0.93826 | 0.951 video | fails |
| final (disclosed) | 0.93811 | 0.951 video | fails |

Every stage below the keyframe behaved exactly as already calibrated: animation costs
about 0.005 and the sync about 0.004. Nothing downstream was broken. **The first frame
was already not her, and no later stage recovers identity that the first frame never
had.**

Face scale was ruled out as the explanation: the keyframe's face was 186px at 18.2% of
frame against training references at 222px and 15.2%, which score 0.961–0.985. The
generation itself simply drew an off-identity face.

Four candidates from the *same prompt and the same LoRA* were then screened:

```
kf_0: 0.95049  below 0.9619
kf_1: 0.96813  PASS
kf_2: 0.96162  below 0.9619
kf_3: 0.97841  PASS
```

A spread of 0.028 straddling the threshold. A single keyframe draw is a lottery, and the
first run lost it — then paid $0.755 animating and syncing the losing ticket.

## Decision

1. **Every keyframe is scored against the still threshold before anything downstream is
   paid for.** `screen_still` and `best_still` in `app/pipeline/acceptance.py`.
2. **Several candidates are generated and the best is chosen**, the same "shoot several
   and pick" rule already used for takes. A candidate costs $0.07 against $0.755 for the
   chain beneath it, so four candidates are cheaper than one wasted chain.
3. **If no candidate clears the threshold the run refuses there**, reporting the whole
   spread. The spread is the finding: four candidates near 0.947 means the prompt is
   off-identity, where one low draw among passes means that draw was unlucky.
4. **An unscorable candidate is not a low-scoring one.** No detectable face returns NaN
   and cannot win `best_still` by default.

## Consequences

- A run costs $0.21 more in keyframes and stops wasting $0.755 chains. On the first
  screened run the chain came back **ACCEPTED**: keyframe 0.97841, final 10/10 frames
  scorable, 0 below threshold, min 0.95457, mean 0.96285.
- Identity is now measured at both ends of the chain rather than only after it, so a
  refusal names the stage that caused it instead of the stage that revealed it.
- This does not relax Amendment A5. The post-sync score is still required; this adds a
  pre-generation one.

## Related

`steadiest()` gained a coverage floor in the same sitting, for the same reason. It had
picked a take with 3.43 degrees of head roll measured over **14 of 41 frames** (34%) over
one with 4.60 degrees over 37 of 41 (90%). The lower figure came from the detector losing
the face, not from a steadier head, and the take it chose was then refused by the sync
provider outright. Coverage is checked before the score, as it already is in `assess`.
Once the keyframe passed, all four takes came back at 100% coverage — the thin coverage
was itself a symptom of the bad keyframe.
