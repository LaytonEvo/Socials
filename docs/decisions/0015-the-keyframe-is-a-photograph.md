# ADR 0015 — The keyframe is an edited photograph, not a rendering

- **Status**: accepted, 2026-10-01
- **Supersedes in part**: ADR 0011 and ADR 0014, which both assume the keyframe is generated
- **Implements**: the `image.keyframe` slot, configured 2026-09-28 and until now unused

## Context

A day spent making LoRA-generated keyframes better produced, in order: a keyframe bar of
0.978 that no draw in 80 could clear; `lora_scale` raised from 1.3 to 1.7 for a 17-fold
cheaper keyframe; a fidelity pass that doubled texture; and a bar revised back to 0.970
when the animation drop turned out to scale with `lora_scale`. Every step was a real
improvement and the owner's verdict never changed:

> *"It's her but almost a more AI version of her."*
> *"Could also not be fully her."*
> *"The back of the head is still too big."*

Shown nine generated keyframes beside four of her master stills, he said of the stills:
**"These images look right."**

The LoRA's rendition of her is the ceiling. Every parameter tested — scale 0.9 through 1.9,
28 and 50 inference steps, with and without a detail pass — moves within that ceiling.

## Decision

**Do not render her. Edit a photograph of her.**

The keyframe is now one of her 80 master stills, edited by `fal-ai/nano-banana-2/edit` to
carry the shot's content. `config/providers.yaml` had already decided this on 2026-09-28,
in words that describe exactly the problem above:

> Editing a master still rather than generating a new one, so the face the threshold was
> calibrated against survives by construction instead of by luck.

## Measured

| | keyframe identity | takes with 0 frames below | keyframe cost |
|---|---|---|---|
| LoRA-generated | 0.97444 | 0 of 6 | up to $7.54 of hunting |
| her master still, unedited | 0.99413 | 2 of 2 | nothing |
| **that still, edited for the shot** | **0.98373–0.98756** | **2 of 2, then 2 of 6** | **$0.08** |

The edit costs about 0.007–0.010 of identity. Generating her from scratch starts 0.019
*below* her own still before any content is added.

The first full run on this path was **ACCEPTED**: 13 of 13 frames scorable, zero below
threshold at every stage, minimum rising 0.95208 → 0.95984 through sync, disclosure and
captions. The owner's verdict: *"This is a much better video."*

## What this changes upstream

- **The keyframe hunt is gone.** ADR 0014's `identity_threshold_keyframe` still guards the
  generated path, which survives behind `--generate-keyframe` for shots no still can carry
  — an action mid-swing, a view from behind her. On the default path a keyframe clears the
  bar by construction.
- **The fidelity pass is unnecessary** and off by default (it also trips its own identity
  guard at `lora_scale` 1.7).
- **`lora_scale` 1.7 stands** for the generated path. It won on identity, fine detail, skin
  evenness and cranium proportion; it simply was not enough.

## What it does not change

**Head swing is the motion model's own behaviour**: 19–40 degrees whatever the keyframe
source. Six takes and ranking on swing bring the chosen one to 19.2 degrees, which is
selection working rather than the generator improving. Pinning the last frame (ADR 0007)
makes the head *end* where it started and makes the excursion larger.

## Limits

- **Only for shots a still can carry.** Her master set is already shot on a golf course at
  816x1456, within a hair of 9:16, which is why this works at all.
- **Eighty stills is the whole vocabulary.** Editing varies content, not pose or framing,
  so pieces built this way will repeat poses sooner than generated ones.
- **The source must come from the train split**, enforced in code: scoring a holdout still
  against a centroid built from the holdout is circular.

## A note on how this was found

Three of the measurements used to chase this were wrong, each caught by the owner's eye
rather than by another number: a texture metric confounded with face size at r=+0.872; a
cranium metric that read one clip's head as double and then half; and a contact sheet whose
crop stretched heads 3.5% wider, which produced a false report that the master set itself
was distorted. The master set is fine and ADR 0008 stands.

The lesson is not that measurement is useless — the pricing error, the gate accepting
unverifiable shots, and the swing hidden inside a standard deviation were all found by
measuring. It is that a metric invented to settle a disagreement should be validated before
it is believed, and that the owner's eye is the instrument of record for how she looks.
