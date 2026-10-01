# Edit a real still, don't generate one — 2026-10-01

The owner was shown nine LoRA-generated keyframes beside four of her real training stills
and said of the real ones: *"These images look right."* The generated ones, across three
separate messages, were *"a more AI version of her"*, *"could also not be fully her"* and
*"the back of the head is still too big"*.

## What this is not

Two hypotheses tested and refuted before landing on the obvious one.

**It is not `lora_scale`.** 1.7 is the closest of every scale measured to her real stills on
cranium height (+7.8%, within noise; 1.9 is +36.9% and significant), and it already wins on
identity, fine detail and skin evenness. Four axes, same answer.

**It is not pose.** The worry was that the prompt asks for a face-on shot the LoRA was never
trained on. Measured head turn: training stills 0.084, generated keyframes 0.091, both about
55% near face-on. The distributions match.

**And the measurement that was supposed to settle it does not work.** Cranium height above
the face box reads 0.619 for her stills, 1.193 for a keyframe and 0.282 for video frames of
the clip that keyframe produced — the same head, measured as double and then half. The
background-distance threshold reacts to grass and compression. Reported here as a failed
instrument rather than as evidence; the owner's eye was right three times today where two
of mine were wrong.

## What it is

The LoRA's rendition of her is the ceiling. So do not render her.

`config/providers.yaml` already carried the answer, decided 2026-09-28 and never wired into
this path:

> `image.keyframe` — Editing a master still rather than generating a new one, so the face
> the threshold was calibrated against survives by construction instead of by luck.

That is the second accepted decision found unwired today; ADR 0007's last-frame conditioning
was the first.

## Measured

A master still from the TRAIN split, scored against the HOLDOUT centroid so the comparison
is not circular:

| | identity | takes with 0 frames below | worst frame | keyframe cost |
|---|---|---|---|---|
| LoRA-generated keyframe | 0.97444 | 0 of 6 | — | $0.035–$7.54 of hunting |
| **her real still, unedited** | **0.99413** | **2 of 2** | 0.97382 | **nothing** |
| **the same still, edited for the brief** | **0.98373** | **2 of 2** | 0.96488 | **$0.08** |

The edit added a sand wedge in her lead hand, a ball on the fairway and a green with a flag
behind her shoulder, and cost **0.0104** of identity. The generated keyframe it replaces was
0.0193 *below* the unedited still before any content was added.

So the edited path is cheaper, better on identity by a factor of four in margin over the
video threshold, and starts from the face the owner says looks right.

## What it does not fix

**Head swing is unchanged**: 35.8 and 45.0 degrees from the edited still, against about 31
from a generated keyframe and 12 from an unpinned one. Swing is the motion model's own
behaviour and is independent of where the keyframe came from. Both takes end within 1 degree
of where they started, so the *ending* is right and the excursion is not.

## Limits worth stating

- **Only for shots a still can carry.** This works because her master set is already shot on
  a golf course at 816x1456, which is within a hair of 9:16. A shot needing an action no
  still contains — mid-swing, down-the-line from behind — still needs generation or a
  different still.
- **80 master stills is the whole vocabulary.** Editing varies the content, not her pose or
  framing, so a piece built this way will repeat poses sooner than one built from
  generation. That is a content question, not a technical one.
- **The holdout discipline has to hold.** A still used as a keyframe must come from the
  train split, or scoring it against a centroid built from the same images is circular and
  the number means nothing.
