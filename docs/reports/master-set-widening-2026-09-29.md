# Widening the master set: outfit and lighting work, body does not

**24 edits, $1.92.** Option 2 as approved: extend `body`, `outfit` and `lighting`
coverage by editing existing master stills, scoring each against the existing centroid
at the 0.9609 threshold. Nothing has been ingested — these are measurements.

## Yield

| Kind | Usable | Scores |
|---|---|---|
| `lighting` | **7/8** | 0.9519 – 0.9866 |
| `outfit` | **6/8** | 0.9583 – 0.9903 |
| `body` | **3/8** | 0.9716 – 0.9797 |

## One bad source explains every outfit and lighting failure

`b4_09` failed all three kinds — outfit 0.9583, lighting 0.9519, body unusable. Its
face area is **0.0068**, against 0.042 to 0.063 for every other source. Six times
smaller.

Excluding it, outfit is 6/7 and **lighting is 7/7**. The one remaining outfit failure is
a `no_face` on `b7_04`, not a low score.

**The rule this gives:** an edit preserves identity when the source face is large
enough, and degrades past the threshold when it is not. Sources were deliberately drawn
across the framing bands to test exactly this, and the wide band is where it breaks.
Editing should draw from stills with a face area above roughly 0.04.

## Body fails for a different reason, and it is inherent

Five of eight were unusable, and the failure modes are the tell:

- **three `too_small`** — widening the frame shrinks the face below the descriptor's
  useful size. The image may be fine; it is no longer a usable identity reference.
- **two `multi_face`** — the model *invented additional people* in the space it was
  asked to fill.

This is what was predicted before spending: an edit cannot see a body outside the
original crop, so a wider frame means inventing it. The three that did pass all came
from mid-range sources, and 3/8 is not a basis for a reference kind.

`multi_face` is worth more than an identity note. A generated still containing a second
invented person is a content problem in its own right, and nothing but the face
detector caught it.

## What this leaves open

**13 usable stills** across outfit and lighting, none ingested yet. Ingesting them moves
the centroid the 0.9609 threshold is defined against (ADR 0008), so the threshold must
be recalibrated against the widened set and every pass rate measured so far becomes
historical. That is inherent in option 2 and was accepted when it was chosen, but it is
a step rather than a consequence and it should be taken deliberately.

For `body`, the options are to leave the kind empty with this recorded as the reason, or
to source body references some other way — the LoRA (task 1.4) could generate them once
trained, which inverts the dependency rather than removing it, since the LoRA trains on
this set.

## Cost

| | |
|---|---|
| First batch, lost to a URL bug of mine | $1.92 |
| Live verification of the fix | $0.08 |
| This batch | $1.92 |
| **Total** | **$3.92** of the $10 authorised |

The first batch submitted and generated 24 images that were then unreachable, because
the adapter built its poll URL instead of using the one fal returned. Detail in the
commit; there is now a test that fails if that is ever done again.


---

## Ingested and recalibrated

*Added 2026-09-29, on the owner's approval after reviewing all 24 edits.*

All 16 that passed are in, under `spike/data/outfit`, `spike/data/lighting` and
`spike/data/body`, tracked like the master set. Body's three are included rather than
dropped: the recommendation was to leave the kind empty, and three stills that
legitimately cleared the threshold are worth more than none. It is still thin coverage
from a 38% technique, not the kind being properly filled.

**The reference set is now 121 stills.** Recalibrated with the spike's own
`calibrate()`, at a 1% false-positive target against 92 controls, so the new number is
comparable with the old rather than computed a different way.

| | Old, 105 | New, 121 |
|---|---|---|
| Threshold | 0.9617 | **0.9619** |
| AUC | 0.9993 | 0.9994 |
| Overlap | 0.0204 | **0.0191** |
| EER | 0.0102 | **0.0096** |
| TPR at threshold | 0.9905 | **0.9917** |
| FPR at threshold | 0.0109 | 0.0109 |
| Verdict | EXCELLENT | EXCELLENT |

**Adding 16 stills changed almost nothing, and what it changed, it improved.** The
cosine between the old centroid and the new is **0.99995**. Overlap fell, equal error
rate fell, true-positive rate rose. The threshold moved by 0.0002.

That is the reassuring answer to the risk this work carried: widening the set was
supposed to force a recalibration that made every previous measurement historical. In
practice the centroid did not move enough for that to bite, so the Gate A identity
figures remain usable rather than being invalidated.

### Two caveats worth stating

**The old calibration reproduces as 0.9617, not the 0.9609 on record.** A 0.0008
difference, consistent with dlib's jitter — the same jitter that made the reproduced
master median 0.98781 against a recorded 0.98757. Nobody should treat a fourth decimal
place here as meaningful.

**The 1% target was clamped to 1.09%.** Ninety-two controls cannot express a
false-positive rate finer than 1/92. Holding the finer target would have cost 1.7% of
her own stills for no measurable reduction in false accepts. A larger control set is
the only way to calibrate finer, and nothing so far suggests it is worth buying.

`config/persona.yaml` carries the new threshold, the four reference directories and the
evidence path. One still in 121 still reads below threshold, lowest 0.9524 — the
documented residual, unchanged.
