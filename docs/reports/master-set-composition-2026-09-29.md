# What the master set actually contains — 2026-09-29

**Measured before starting task 1.1**, because that task's acceptance criteria say
"stills tagged face / body / outfit / lighting" and it was not clear the existing set
could satisfy that. It cannot, and the reason is worth recording.

## The set

| | |
|---|---|
| Images | 108 |
| Exactly one detectable face | **105** |
| No detectable face | 3 (`b1_11`, `b2_04`, `b4_10`) |
| Resolutions | 816×1456 and 928×1232, both portrait |

The 105 matches `persona.yaml` exactly and was arrived at independently here, so the
figure the threshold is calibrated against is confirmed rather than assumed.

## Framing, by face area as a fraction of the frame

| Band | Fraction | Count |
|---|---|---|
| Close | ≥ 0.08 | 12 |
| Medium | 0.02 – 0.08 | 88 |
| Wide | < 0.02 | 5 |

Minimum 0.0068, median 0.0605, maximum 0.1254.

**The set is not a pile of headshots.** A median face area of 6% means the frame is
overwhelmingly *not* face, so these stills show her at medium distance with torso and
clothing visible. That is the reason a wardrobe change could be made by editing a
master still at all.

## What this means for task 1.1, and it is a real limitation

`reference_asset.kind` is `face / body / outfit / lighting`. **The spike never tagged
by kind.** Its `ingest()` takes a set name, filters on face presence — rejecting
no-face, multi-face and too-small — and copies to `master_NNN`. There is no manifest
to draw tags from because no tagging ever happened.

So of the four kinds:

- **`face`** — all 105 qualify, guaranteed by the filter that produced them.
- **`body`, `outfit`, `lighting`** — present *in* the images, as the framing above
  shows, but unlabelled. Which still is a good body reference, or demonstrates a
  lighting condition, is a visual judgement. It is not something to infer from a face
  bounding box, and guessing it would put fabricated metadata into the provenance
  backbone.

BUILD_PLAN's vocabulary presumes a set curated *for* those purposes. This set was
generated and filtered for one detectable face, which is a different thing.

## The question this raises for task 1.4

A LoRA trained on 105 stills that are all tagged `face` is being trained on whatever
those images happen to contain, with no control over the balance. The framing spread
above suggests the content is more varied than the tags would say — 88 medium shots
is a reasonable spread — but "probably fine" is not a measurement, and task 1.4 is
where it would be discovered otherwise.

**This is an owner decision, not a build one.** Either the 105 are ingested as `face`
and the other three kinds stay empty, or the master set is extended with stills
generated for body, outfit and lighting coverage — which means new generation spend
and, because ADR 0008 makes her look a hard dependency, recalibrating the threshold
against the widened set.

Not recommending one. The first is free and may be sufficient; the second costs money
and a recalibration to remove a doubt that is currently unquantified.
