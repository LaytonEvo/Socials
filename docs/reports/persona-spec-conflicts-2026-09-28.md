# Persona spec v1 against what the spike measured

**Date:** 2026-09-28 · Spec: `docs/spec/persona-spec-v1.md`, folded into
`config/persona.yaml`.

D1 is answered apart from the name. The spec is internally coherent and its
central instinct — *"her stated ability is the ceiling for anything rendered"* —
is exactly the constraint this project needed someone to write down.

Five things it collides with. None is fatal; all are cheaper to resolve now than
after a master set is built against them.

## 1. "Hybrid" means something else in this codebase

Spec §1 says **"Hybrid, personality-led"**, meaning she plays on camera while the
personality is the product.

`BUILD_PLAN` D2 uses *hybrid* for one specific thing: **a contracted human
performer supplying real swing footage, disclosed.** `production.mode` takes
`synthetic` or `hybrid` and choosing the latter changes the operation into one
with contracts, scheduling and a second disclosure surface.

Recorded in `persona.yaml` as `positioning: personality_led_who_plays` with
`production_mode: synthetic` and a comment, so nobody reads the spec's word and
sets the config value. **No performer is implied by spec v1.**

## 2. The bio says 25; the master set was generated at 23

Every image in `master_v2` came from a prompt beginning *"photo of a 23 year old
English woman"*. Spec §3 states 25 explicitly in the bio.

Two years is not much, but the look is locked (ADR 0008) and the identity
threshold is calibrated against those images, so the look cannot be regenerated
at 25 without recalibrating. **The cheap fix is the bio.**

## 3. She lives in Florida. Everything generated so far is English parkland.

Spec §3 puts her in Jupiter/Naples, and §3's content strands lean on it: *heat,
alligators, buggy culture, tipping, "y'all"*.

**No clip generated in this spike is set in Florida.** The model invents the
background from a portrait keyframe, and left to itself it has produced English
parkland every time — trees, overcast and golden-hour light, links-ish fairways.
That is ideal for the "trips back home" strand and wrong for the main setting.

**Untested and material.** Whether the model renders a convincing Florida course —
palms, Bermuda grass, harder light, different sky — from the same portrait
keyframes is unknown, and it is the everyday setting rather than an occasional
one. Two clips, about 13p.

## 4. The voice needs checking against the accent

Spec §3 requires **Southern English, warm, not posh**. The chosen ElevenLabs
voice (`sWsBiVcjjowceAScTnu3`) was selected on sound rather than against a
written accent spec, and earlier in the same session the owner said of a previous
candidate *"looking for a british voice long term but that's fine for now"*.

Listen once against the spec before the master set is built on it. If it is
wrong, changing it is cheap **now** and expensive after a back catalogue exists —
a voice is an identity property, which is the whole reason the ElevenLabs slot
exists (ADR 0005, 2026-09-28).

## 5. The clothing rule cannot currently be enforced

Spec §5's test — *would a strict members' club let her on the first tee* — is a
good rule and goes in the locked fragment.

**Nothing can hold the model to it.** Wardrobe changes mid-clip: white skirt to
black shorts inside four seconds on 2026-09-25, and an outfit change the owner
flagged again on 2026-09-28. The rule constrains the prompt; the model changes
her clothes anyway; no check sees it.

This is the same missing instrument as D-A's second half, and spec §9's long-form
plan raises the stakes — a 6–8 minute piece is an assembly of many clips, and
inter-clip continuity is the binding constraint on long form, not swing quality.
The spec already flags long-form as a continuity risk, correctly.

## Cadence: the cost is fine, the time is not

Phase one is **five Shorts a week** against `BUILD_PLAN` §9's two pieces.

Generation cost is no longer the constraint — at turbo's $0.0125/s the clips are
pennies and lip sync dominates. **Operator time is**, and Gate A §7 records that
it was never measured. Every clip needs a human, because the gate routes rather
than rejects and catches 1 defect in 7. Five Shorts a week is a standing review
load nobody has timed, and it is the number most likely to decide whether this is
sustainable.

Measuring it needs one thing the spike never did: **make one finished piece,
end to end, and time it.**

## One thing the spec gets right that is worth naming

*"Bad shots are content, not continuity errors."* That converts a whole class of
generation defect into material, and it is the single most useful line in the
document.

It does not cover everything. A bad **shot** is content. A bad **club** is a
broken render — the owner rejected a driver and a putter as *"not real"* on
2026-09-28, and no amount of framing makes an unreal club a joke about her
handicap.

---

## Florida: resolved. The setting is a prompt-level choice.

Four clips, `talking_head_course` and `walking_fairway`, two takes each, from the
**same English keyframe**. **$0.25.**

The keyframe is unambiguously England: deciduous woodland, low soft sun, rolling
parkland. The prompt named Florida — tall palms, Bermuda grass, hard subtropical
light, flat sandy terrain — and the model rendered it: palms, white sand
bunkers, water, flat ground, the light to match.

**So collision 3 dissolves.** No Florida keyframes are needed, the master set
covers both worlds, and the England/Florida contrast in spec §3's content strands
costs nothing. That is the good case and it was not the likeliest one.

### Two qualifications

**The setting changes over during the clip.** The opening second still carries
the keyframe's English background and the palms arrive after it. Read as a
transition it is fine; read as a mistake it is not, and that is the owner's call
rather than a measurement. It matters most for very short cuts, where a clip may
end before the setting has fully turned over.

**Identity sits lower than the English equivalents.** All four scored
`indeterminate`:

| Clip | Face presence | Identity min |
|---|---|---|
| `talking_head_course` take 1 | 0.900 | 0.9559 |
| `talking_head_course` take 2 | 1.000 | 0.9549 |
| `walking_fairway` take 1 | 0.700 | 0.9478 |
| `walking_fairway` take 2 | 0.600 | **0.9163** |

Against the same two formats in the English setting, which returned 0.9725,
0.9748, 0.9634 and 0.9571. Every Florida clip is below every English one, and
the worst is well under the 0.9609 threshold.

**The owner rated all four usable — *"all look ok"* — so the gap is not visible,
and the concern above was most likely a false alarm.** It is recorded because it
was raised, and because the gate scoring every Florida clip `indeterminate` has a
cost even when the picture is fine: at five Shorts a week, a setting that
systematically scores lower sends every clip of it to a human. That is a review
load argument rather than a quality one, and it is the better reason to spend the
50p below.

The only other note was *"still strange language in the 3rd"* — the model's
unconditional soundtrack, since this run used neither `--pin-audio` nor `--say`.
Expected, already governed, and nothing to do with Florida.

**Four clips against four is not a finding**, and the gate's failures have been
right one time in three, so this may be nothing. But the mechanism is plausible:
the persona was generated under soft English light and the identity centroid is
built from those images, so hard subtropical light is a lighting condition the
master set never saw. The condition matrix already found light to be the second
strongest axis after apparent face size, with midday the worst level at 1 of 5.

**Worth one cheap check before the content calendar leans on Florida**: the same
two formats, more takes, English against Florida, purely to see whether the gap
survives a larger sample. Roughly 50p. If it does, it argues for adding
Florida-lit stills to the master set — not to replace the keyframes, which work,
but to widen the distribution the threshold is calibrated against.
