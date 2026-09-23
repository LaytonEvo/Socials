# ADR 0005 — fal.ai as the Spike 0 provider, and the order to test in

- **Status:** Accepted 2026-09-23 by the owner. Account to be created; no key held yet.
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
