# S0.5 — what animating her stills actually established

Two findings, and neither is the one the spike set out to measure. The
identity question is **not answered**; what was learned is why it could not be
answered this way, which is worth more than a number would have been.

**Scorer:** dlib ResNet, threshold 0.9748 (ADR 0004)
**Provider:** `fal-ai/veo3.1/image-to-video`, 4s, 720p, audio off (ADR 0006)
**Evidence:** 26 clips generated, 24 scored, ~$19 spent across the day

## Finding 1 — the threshold has no headroom for motion

Grouping every scored clip by how it was produced:

| Production | n | min | median | max |
|---|---|---|---|---|
| Static, bland prompt ("a person standing still") | 11 | 0.9795 | 0.9834 | 0.9887 |
| Real shots — talking, walking, turning | 13 | 0.8440 | 0.9797 | 0.9851 |

And the two golf-battery shots, which are what the product would actually
publish:

| Shot | Score | Threshold | |
|---|---|---|---|
| `talking_head_course` | 0.9680 | 0.9748 | **fail** by 0.0068 |
| `walking_fairway` | 0.9754 | 0.9748 | pass by 0.0006 |

**Motion and expression cost roughly 0.01–0.015 of similarity, and the
threshold sits 0.0018 below her weakest master still.** There is no room in
that gap for the variation the product requires. A clean talking-head clip
fails; a walking shot passes by six ten-thousandths.

A calibration that reads EXCELLENT and rejects good footage is not a working
gate. The verdict was never wrong — 0.000 overlap and AUC 1.0000 are true of
the master and control sets — but those sets are 28 stills of near-identical
framing, so "her" is defined far too narrowly to survive being animated.

**The fix is not a lower threshold.** Moving the cut point by hand would
discard the only principled thing about it. The fix is a master set that
covers the variation she will actually exhibit — more angles, expressions and
framings — so the positive distribution widens honestly and the threshold
lands somewhere a moving clip can clear. That is a re-calibration under
amendment A3, and it needs new stills first.

## Finding 2 — a fixed portrait cannot produce most of the battery

Four of the first six golf-battery shots could not be generated at all:

| Shot | Outcome |
|---|---|
| `equipment_closeup` — close-up handling a golf club | `no_media_generated` |
| `apparel` — presenting golf apparel | `no_media_generated` |
| `clubhouse` — seated, talking | `no_media_generated` |
| `reaction` — reacting to a shot | `no_media_generated` |

The prompt describes a frame that is not a portrait; the keyframe is a
portrait; the model produces nothing. The seven remaining shots are swing
mechanics and ball flight, which would fail the same way.

**This is structural.** Animating a fixed still can only produce shots close
to that still's framing. The battery assumes a pipeline where S0.4's LoRA
generates a keyframe *per shot* — and substituting one portrait for all of
them was my workaround for S0.4 not existing, which makes most of the battery
unanswerable rather than merely harder.

So S0.5-from-existing-stills can speak only about talking-head footage. That
is a narrower claim than "does the concept survive", and the spike order
should have anticipated it: **the format question depends on S0.4 in a way the
build order did not record.**

## What this means for the identity question

It is still open, and the honest position is that this route cannot close it:

- Static clips pass comfortably (0.979–0.989), but static clips are not the
  product.
- The two real shots straddle the threshold, which measures the calibration's
  narrowness more than her likeness.
- The negative control worked: two clips generated from a synthetic landscape,
  showing a woman the model invented, scored 0.844 and 0.858 and were rejected,
  with face presence flagged at 0.88. **The instrument does distinguish her
  from someone else.** It is the pass/fail line that is mis-set, not the
  measurement.

That last point is worth separating out, because it is the good news: the
scorer works. It caught a different woman on real video, which is the thing it
exists to do.

## What to do next, in order

1. **Widen the master set** with varied stills — angles, expressions,
   framings, lighting — then re-prepare and re-calibrate. Nothing else is
   worth measuring until the gate can pass footage that a human would accept.
2. **Re-run the two battery shots** against the new threshold. If a clean
   talking-head clip still fails, the problem is the persona's consistency
   rather than the calibration, and that is a different and more serious
   finding.
3. **Defer the rest of the battery to S0.4.** Swing, apparel, equipment and
   clubhouse shots need per-shot keyframes. Attempting them from a portrait
   spends money to rediscover finding 2.

## Cost of learning this

About $19 across the day, of which roughly $4 was lost to two bugs of mine
that charged for nothing before the billing classification was fixed. 26 clips
exist and are viewable; 24 were recovered from fal's request history after
diagnostic scripts discarded them, which is now guarded against.
