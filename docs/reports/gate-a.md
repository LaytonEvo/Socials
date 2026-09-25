# Gate A — Spike 0 report

**Date:** 2026-09-25 · **Recommendation: proceed, with four decisions attached**

> **Amended 2026-09-25**, after the report was written, by the second battery
> take: §5's headline usable rate and §6's discard rate are corrected below, and
> the ADR 0003 recommendation is withdrawn. Detail in
> `s07-battery-take2-2026-09-25.md`.

Spike 0 asked whether a recurring, openly-AI golf personality is technically
feasible. It is. Every element of the content chain has been built, measured
and chosen against real providers, and the owner has watched and judged the
output at each step.

This report is the §3.3 deliverable. Two of its eight sections are
incomplete and say so.

---

## 1. Threshold calibration

**Scorer:** dlib ResNet, 128-d, cosine against the L2-normalised centroid of
the master set. **Threshold 0.9609**, calibrated 2026-09-24.

| | n | mean | sd | min | p05 | median | max |
|---|---|---|---|---|---|---|---|
| Her (`master_v2`) | 105 | 0.98508 | 0.00819 | 0.95041 | 0.97096 | 0.98757 | 0.99445 |
| Controls (`control_v2`) | 92 | 0.93391 | 0.01402 | 0.88942 | 0.90966 | 0.93585 | 0.96676 |

| Statistic | Value |
|---|---|
| AUC | 0.9989 |
| d′ | 4.46 |
| **Overlap (1 − KS)** | **0.020** |
| FPR at threshold | 0.0109 (1 of 92) |
| TPR at threshold | 0.9905 (104 of 105) |

**How much the distributions overlap, explicitly.** Twelve of 197 images fall
in the crossing zone, and only two cause it: her lowest still at 0.95041 and
the closest control at 0.96676. Strip those two and there is a clean empty gap
from 0.95822 to 0.96094. Both are explained by face angle — a near-profile of
her, a frontal close-up of a genuine lookalike — not by the persona being
indistinct. Detail in `identity-threshold-correction-2026-09-24.md`.

The control set is condition-matched and synthetic throughout, as ADR 0002
Finding 4 requires: real faces would be Article 9 biometric data.

**Two corrections are load-bearing here.** The first calibration measured
positives pairwise while `score.py` scores against the centroid, making every
threshold too lenient; the second asked for a false-positive rate finer than
92 controls can express (1/92 = 1.09%), which forced FPR to 0 and pushed the
threshold to 0.9701 — rejecting 4.8% of her own stills instead of 1.0%, and
leaving the flagship clip passing by 0.000005.

---

## 2. Identity pass rate by condition axis

18 of 20 cells generated (`s06-condition-matrix-2026-09-25.md`). **11 passed,
7 indeterminate, 0 failed.**

| Axis | Level | Pass | Indeterminate |
|---|---|---|---|
| angle | front | **6/6 (100%)** | 0 |
| | profile | 3/6 (50%) | 3 |
| | three_quarter | **2/6 (33%)** | 4 |
| distance | close | 5/6 (83%) | 1 |
| | medium | 5/6 (83%) | 1 |
| | wide | **1/6 (17%)** | 5 |
| light | golden_hour | **4/4 (100%)** | 0 |
| | overcast | 4/5 (80%) | 1 |
| | indoor | 2/4 (50%) | 2 |
| | midday | **1/5 (20%)** | 4 |
| motion | turning | 5/6 (83%) | 1 |
| | static | 4/6 (67%) | 2 |
| | walking | **2/6 (33%)** | 4 |

**Nothing failed on identity.** Five of seven indeterminates are the same
shape: a face found in 3 of 8 sampled frames, under the coverage floor. The
finding is not that identity breaks in wide shots but that it **cannot be
measured** in them.

**The axes are confounded and these rates are not independent effects.** The
seven indeterminates are 5 wide, 4 walking, 4 midday, 4 three-quarter, and one
cell contributes to all four. The single mechanism consistent with every row
is apparent face size.

---

## 3. Contact sheet of worst frames

`spike/runs/matrix/contact_sheet.png` — 18 clips, worst frame first.

**The scorer has passed clips a human rejects, and this is the central finding
of the spike.** On 2026-09-24 the owner watched a clip the gate had marked
`pass` at identity 0.9757 and called it *"clearly AI"*. The gate was not wrong
about identity — her face is her face in every frame — it is blind to what was
wrong. Three structural reasons, the last decisive:

1. It scores a **face crop**: body, limbs and scene are outside the measurement.
2. It compares each frame to the master centroid, never to the frame before
   it, so a discontinuity is not measured coarsely but not at all.
3. dlib **aligns the face before embedding**, cancelling head roll. A face
   recogniser is built to be invariant to pose; that invariance is the blindness.
4. The defect fell inside a 0.625 s window with **no detectable face**.

§3.3 says: *"If the scorer passes clips a human rejects, the scorer is the
finding, and Phase 3's auto-reject design needs rethinking before it is built
on top of this."* **That condition is met.** BUILD_PLAN task 3.4 assumes
identity scoring can decide publishability. It cannot, and no threshold makes
it able to.

---

## 4. Lip-sync score delta

`s08-lipsync-probe-2026-09-24.md`. Measured across four runs and three models.

| Model | $/4 s clip | Identity delta |
|---|---|---|
| `pixverse/lipsync` | $0.16 | −0.0037 to −0.0123 |
| `veed/lipsync/v2` | $0.28 | −0.0006 |
| **`heygen/v3/lipsync/precision`** | $0.40 | **+0.0041** |

On a controlled three-way — one source clip, one synthesis, three models —
the owner chose HeyGen (*"B is definitely the best"*), and it is the only one
that does not cost identity. Its `+0.0041` reproduced a `+0.0042` from a
separate clip.

**Amendment A5 is answered**, and with a consequence: with pixverse, one clip
in three that had passed fell below threshold after the pass. Choosing the
cheapest model would have cost margin on every clip.

**An open problem this exposes.** The threshold is calibrated on *stills*. If
the pipeline always lip-syncs, the gate judges production output against a
distribution it never belongs to — the calibration-space error one level up.
Not decided; see §8.

---

## 5. Golf format matrix

`s07-golf-battery-2026-09-24.md`. 13 of 13 formats generated, no refusals.

| Rated by the owner | Count |
|---|---|
| 5 — no defect noted | 6 |
| 4 — usable, club/ball detail off | 7 |
| below 4 | **0** |

Usable rate 13/13 on this take, including all seven formats ADR 0003 predicted
would break on club-and-ball physics. Dominant failure tags:
`club_distortion`, `ball`.

Caveat: **one take, one provider.** The acceptance criterion asks for two
takes on two providers. One good take does not prove a format is reliably
good.

> ### ⚠ CAUTION — superseded 2026-09-25
>
> **This section originally concluded "usable rate 13/13" and "ADR 0003 needs
> amending". The second take falsified the first claim and reversed the
> direction of the second.**
>
> 10 of 13 formats have a second take. The owner rejected two of them —
> `ball_flight` and `putting_stroke`, both on golf swing and ball physics.
> Both had been rated 4 in this take. **8 of 10 formats are usable twice; 2
> are not.**
>
> Both rejects are club-and-ball shots: 2 of 13 such takes rejected (15%,
> 95% CI 1.9–45.4%) against 0 of 10 face-forward takes (0%, CI 0–30.8%). The
> split falls on the axis ADR 0003 named, and the intervals overlap too
> heavily to establish it.
>
> **The ADR 0003 recommendation is withdrawn.** Its axis is right and its
> strength is still too high: 11 of 13 club-and-ball takes were usable, so
> these formats are not impossible, but the failure is a discarded clip
> rather than "detail a bit off". The constraint is a **yield penalty
> concentrated on swing content**, which is the content a golf persona most
> needs. The amendment should wait for the three missing formats rather than
> be rewritten twice on one take each.
>
> Detail, and a routing rule it offers D-A, in
> `s07-battery-take2-2026-09-25.md`.

---

## 6. Cost

| | |
|---|---|
| Ledger total, both days | **$75.94** |
| Billable calls | 97 |
| Refused calls (free) | 75 of 172 attempts (44%) |
| Owner-rated clips | 18, of which 16 usable (**89%**) |

By model:

| Spend | Model |
|---|---|
| $44.40 | `veo3.1/image-to-video` (flagship tier, superseded) |
| $26.40 | `veo3.1/fast/image-to-video` |
| $2.20 | first/last-frame variants |
| $2.89 | lip-sync across three models |
| $0.05 | ElevenLabs TTS, 16 calls |

**These are guard prices, not invoiced amounts.** The cost guard deliberately
records the higher of the published figures — $0.40/s where the audio-off rate
is $0.20/s — because a guard that understates lets a run pass the cap while
reporting it is inside it. **Actual charges are likely lower and are
unverified.** The budget model must not harden until an invoice settles it.

**Cost per identity-passing second** is reported by the harness but is an
**upper bound on usable**, not a usable rate: the gate cannot see motion,
anatomy or shot adherence, and passed a visibly bad clip.

**Discard rate.** `BUILD_PLAN` §9 assumes 3 in 5 discarded. Measured on
owner-reviewed output after the second take: **4 of 28 (14%)**. Still far
better than assumed, but the correction matters less than where the discards
sit — all four are club-and-ball shots, and the rate on that subset is 2 of 13
takes with a 95% interval running to 45%. A blended figure understates the cost
of swing content and overstates the cost of everything else.

Eight of those 28 carry "reviewed, not flagged" rather than a numeric score,
which is a weaker statement than a 4 or a 5. Treat 14% as a floor.

The tier decision matters more than any of this. Fast beat flagship on a
controlled comparison, at **$0.15/s against $0.40/s guard** — roughly £190 a
month against £520 on §9's two-pieces-a-week assumption.

---

## 7. Operator time

**Not logged, and that is a gap in this report.** Amendment A1 requires
wall-clock operator time recorded per run and it was never done.

Reconstructed from run-log timestamps, which is not the same measurement:

| | |
|---|---|
| First event | 2026-09-23 11:11 |
| Last event | 2026-09-25 07:07 |
| Elapsed | 43.9 h |
| Active (gaps >30 min excluded) | **~6.9 h in 11 blocks** |

This counts harness activity, not human attention, and the two differ in both
directions. **The real input to §9's viability question — operator minutes per
finished piece — has not been measured**, because no finished piece has been
made.

---

## 8. Recommendation

**Proceed.** The technique holds. Every stage is chosen, measured and
reproducible:

```
Veo 3.1 fast          $0.15/s guard   (+ first/last-frame for occlusion returns)
ElevenLabs turbo-v2.5 $0.05/1k chars  voice sWsBiV…, speed 0.9, stability 0.3, style 0.4
HeyGen precision      $0.40/clip      lip sync
dlib ResNet           threshold 0.9609, three-valued verdict
```

The persona's look is decided (ADR 0008) and the calibration carries forward
rather than needing a Phase 1 re-run.

### Four decisions before Phase 1

**D-A. Task 3.4's auto-reject design must be rethought.** It assumes identity
scoring can decide publishability. §3 shows it cannot. A motion check is a
different instrument — frame-to-frame consistency or optical flow, not the
face — and it must work across occlusions, which is the hard part. **The human
approver is currently the only thing that has caught a bad clip; the gate has
caught none.**

One cheap thing the data does offer, as routing rather than detection: every
clip that has ever lost a frame of face was a club-and-ball shot, 10 of 10, so
**face presence below 1.0 flags the clips where a human must watch the golf and
not just the face.** It cannot see a bad swing. It identifies where one is
possible.

**D-B. Recalibrate for lip-synced output, or gate before the pass.** §4.
Cheapest option is a margin; correct option is a calibration run.

**D-C. ADR 0002 — the dlib licence.** Part of its training data (FaceScrub) is
non-commercial. Everything measured here rests on it. Accept, buy InsightFace,
or revert to DINOv2.

**D-D. Is S0.4's LoRA still wanted?** It is no longer on the critical path —
the finding that a fixed portrait could not produce the battery was wrong, and
Midjourney stills cover keyframes. Skipping it saves GPU spend and the FLUX
licence question entirely.

> **Reopened 2026-09-25.** Midjourney stills cover *portrait* keyframes. Frame
> inspection of the two rejected clips shows both failures begin at the moment
> the model leaves the portrait composition the keyframe anchors it to: shots
> that can be posed inside a portrait all succeed, and shots needing a wide
> action framing pan away and fabricate the golf. There is no source of an
> action-framed still of this persona — at address, at the top, at impact — and
> the club-and-ball formats are failing for want of one. **The question is
> sourcing, not the LoRA specifically**; pose-conditioned Midjourney prompts may
> answer it more cheaply. Detail in `s07-battery-take2-2026-09-25.md`.

### Evidence still missing, and what it costs

| | Cost |
|---|---|
| ~~Second battery take~~ — run 2026-09-25, 10 of 13 formats, $6.00. **Two failed.** Three formats outstanding | $1.80 |
| ~~First/last-frame on `ball_flight` and `putting_stroke`~~ — hypothesis withdrawn 2026-09-25 on frame inspection | — |
| Action-framed keyframe on `putting_stroke`, 2 takes | $1.20 |
| A source of action-framed stills of the persona — see D-D | unknown |
| Two matrix cells that never ran (balance exhausted) | $1.20 |
| First/last-frame on the two rejected shots | $1.20 |
| Operator time on a real end-to-end piece | time, not money |

### What the spike changed about the plan

- **ADR 0003** — *withdrawn 2026-09-25.* Take 0 gave 13/13 usable; take 2
  rejected two club-and-ball formats. See the caution in §5.
- **BUILD_ORDER §3.1**'s throwaway-look premise is void (ADR 0008).
- **`BUILD_PLAN` §9**'s 3-in-5 discard rate looks pessimistic at 11%, and its
  cost model is 2.7× too high at the Fast tier.
- **The format question never depended on S0.4.** That was a keyframe-handling
  bug of mine, corrected in `s05-gate-finding-2026-09-24.md`.

### A note on this report's reliability

Five of my own conclusions were wrong and were corrected on measurement: the
calibration space, "the distributions cross", the S0.4 dependency, that turning
would be the worst motion, and — added 2026-09-25 — that ADR 0003 had
over-constrained the formats, a conclusion drawn from one take that a second
take reversed. Each was caught by checking rather than by reasoning. **The owner's eye caught every bad clip; the automated gate caught
none of them.** That asymmetry is the most important thing in this report and
it should shape how much the Phase 3 automation is trusted.
