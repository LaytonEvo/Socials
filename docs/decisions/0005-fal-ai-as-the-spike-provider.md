# ADR 0005 — fal.ai as the Spike 0 provider, and the order to test in

- **Status:** Accepted 2026-09-23 by the owner. **Its native-audio question is answered: no (2026-09-28).**
- **Date:** 2026-09-23
- **Deciders:** Layton (owner), supervising engineer
- **Relates to:** `CLAUDE.md` (cost guard, adapter boundary, secrets); `docs/BUILD_ORDER.md` S0.4–S0.5, amendment A7; `docs/reports/provider-decisions-2026-09-23.md`

## Context

`config/spike.yaml` has five empty provider slots. Two are due now — a LoRA
base model with somewhere to train it (S0.4), and a video model that can
animate a still without losing her face (S0.5). The rest depend on whether the
second one works.

The choice was made on the constraints in `CLAUDE.md` rather than on headline
price, because at Spike 0 volumes price is not the deciding factor: 20–40 clips
of five seconds is on the order of $75–150 even at a premium rate.

## Decision

**fal.ai**, pay-per-use, one account covering both due slots.

Three reasons, in the order they actually carry weight:

**1. The cost-guard rule selects it.** Every paid call must write a
`cost_ledger` row in USD in the same transaction. A published per-second rate
per model maps onto that directly. Providers selling **prepaid credit packs**
do not: credits-to-USD becomes a conversion maintained by hand, and a ledger
that can be wrong is worse than no ledger, because it is trusted. This
disqualifies the credit-pack providers for this build whatever their headline
rate.

**2. The adapter rule makes the comparison cheap.** "No vendor SDK outside
`app/providers/`" means one adapter behind one key reaches many models, so
"which model holds her face" becomes a config change rather than an
integration. That is the same shape as the dlib-vs-DINOv2 bake-off, which is
the pattern this project has already found works.

**3. It collapses both due decisions into one signup** — video models and FLUX
LoRA training on the same account, so S0.4 needs no separate GPU host.

Replicate was the close alternative and would have been accepted on the same
reasoning. The reasoning does **not** extend to going direct to a single
provider, which buys a lower rate at the cost of the comparison.

## Test order: most capable model first

Deliberately inverted from the usual instinct, and it follows from why Spike 0
exists.

**A failure on the best available model kills the concept for about $100. A
failure on a budget model establishes nothing** — you would never know whether
a better model would have held her face, so the run would have to be repeated
and the cheap answer was worthless.

So: start at the premium tier, ideally one that generates **audio and lip-sync
natively**, because that could remove the S0.7 lip-sync stage entirely — the
largest structural saving available. Drop to cheaper tiers once the ceiling is
known.

## Base model: FLUX.1 [schnell] first

Apache 2.0, commercial use permitted, free. **Do not buy a licence before
knowing one is needed** — the ADR 0002 pattern: measure the free options, keep
the paid one as a funded fallback, and buy with evidence rather than a guess.

**Caveat, unverified and to be watched in S0.4:** schnell is a distilled model
and LoRA training on it is generally reckoned harder than on `dev`. If likeness
fidelity is poor, that is the trigger to buy the BFL commercial licence for
`dev` — not a reason to start there. FLUX.1 [dev] is non-commercial and derived
LoRAs inherit the restriction, so training on it first would mean discarding
the run rather than relicensing it.

## Consequences

- One new paid service, approved by the owner under the `CLAUDE.md` rule
  requiring it.
- Prices still go in `config/spike.yaml` per model with a `verified_on` date,
  read from fal's own model pages. Nothing is configured from the estimates in
  the provider report.
- The environment must allow fal's domains, or the adapter cannot call it and
  the prices cannot be verified. Currently blocked.
- `providers.video.budget` and `providers.lipsync.primary` stay `null`. They
  are decisions that depend on the flagship result and are not due.
- **No TTS slot exists in the config.** Still flagged, still not added: if the
  video model produces audio natively it may never be needed.

## What would overturn this

fal's catalogue not carrying the model we want, in which case going direct to
that provider and paying for a second adapter is correct. The aggregator is a
means to a cheap comparison, not a principle.


---

# 2026-09-28 — the native-audio question, answered

This ADR named one structural saving worth chasing:

> start at the premium tier, ideally one that generates **audio and lip-sync
> natively**, because that could remove the S0.7 lip-sync stage entirely — the
> largest structural saving available.

**It cannot be removed.** Three mechanisms were tried on
`minimax/h3-max-turbo`, which generates audio unconditionally, for about 40p in
total.

| Attempt | Mechanism | Result |
|---|---|---|
| Pin a soundtrack | `target_audio_url` | Lands bit-exact (+1.000 correlation). **The mouth ignores it** — pinning muxes audio over a finished video. |
| Let it speak | dialogue written into the prompt | **Works.** *"Both are english."* Its own lip sync follows its own speech and is good. |
| Both together | speak the line, pin her voice over it | **Drifts.** *"Lip sync is off, drifts."* |

The third was the one worth trying and it fails for a reason no trim can fix.
Two independent renderings of the same sentence pace differently, so they begin
together and slide apart. A constant offset would have been rescuable; **drift
is not.**

## Why native speech alone is not enough either

The second row works. The model speaks English on request and syncs it
correctly. It still cannot carry the persona, for a reason this spike had no
instrument for: **the voice is not stable between takes** — *"second sounds a
little different"* — and one take opened with a few words of invented
non-English.

A recurring persona needs one voice the way it needs one face. That is an
identity property, and the ElevenLabs slot was chosen partly because a dedicated
provider is the only way to hold a voice constant across videos. That reasoning
survives this ADR's question being closed.

**Amended 2026-09-28, and I had overstated it.** Asked to compare two takes
generated on a pinned seed, the owner's verdict was *"they are a bit different
but close"* — not the wholesale instability "the voice is not stable" implies.
The variation is modest.

It is still disqualifying, for a reason about the product rather than the clip:
a single clip with a slightly-off voice is fine, and a back catalogue where the
voice drifts from video to video is not. Cross-video consistency is the
requirement, and "close" does not meet it when the alternative meets it exactly
and is already in the pipeline.

**The seed governs neither.** The same pair differed by 25.42/255 per pixel in
the picture, so the voice variation is inherent to the model rather than
something a seed could pin.

## What stands

**The lip-sync stage stays**, currently HeyGen precision at **$0.40/clip**, and
the chain remains three providers: video, speech, sync.

The saving this ADR hoped for did not arrive, but a larger one did from a
direction it did not anticipate: the **video** tier. `veo3.1 fast` at $0.15/s
against `h3-max-turbo` at $0.0125/s takes a talking-head clip from roughly $1.00
to $0.47 — and lip sync is now **six times the cost of the footage it is applied
to**, which inverts where the next optimisation should look. S0.8 chose HeyGen
over veed ($0.28) and pixverse ($0.16) on identity grounds when video dominated
the bill. That trade deserves re-measuring now that it does not. It belongs with
D-B.

**One thing to keep.** Pinning a soundtrack is still the only way to govern this
model's unconditional audio, which otherwise ships an unidentified language on
every clip. It is worth having for every clip that is not lip-synced afterwards.
