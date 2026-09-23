# Provider accounts and spend — what needs deciding, and why

Written 2026-09-23. **None of the prices below may be copied into
`config/spike.yaml`.** They come from secondary sources (comparison blogs and
search summaries), and `CLAUDE.md` requires every price to be verified against
the provider's own current documentation and stamped with a `verified_on`
date. They are here to size decisions, not to configure anything.

The environment's network policy blocks the provider domains, so I could search
but not read an official pricing page. See "What I need to finish this" at the
end.

## You need two accounts now, not five

`config/spike.yaml` has five empty provider slots. They are not all due at
once, and buying them all now would be spending ahead of the evidence.

| Slot | What it does | Needed at | Due now? |
|---|---|---|---|
| `lora.base_model` + GPU host | Trains her likeness into an image model | S0.4 | **Yes** |
| `providers.video.flagship` | Face-forward shots, the hard case | S0.5 | **Yes** |
| `providers.image.primary` | Stills from the trained model | S0.4 output | Not yet — Midjourney is covering this |
| `providers.video.budget` | B-roll, volume | After S0.5 proves the concept | No |
| `providers.lipsync.primary` | Mouth movement to audio | S0.7 | No |

The budget and lip-sync slots only matter if the flagship slot works. Deciding
them now is deciding on a question that has not been asked yet.

## Decision 1 — the LoRA base model, and it is a licence question

**This is the one that can quietly sink the project, and it is not about
price.**

The obvious choice for training a persona LoRA is FLUX.1 **[dev]**. It is
**non-commercial**, and Black Forest Labs' terms state that use for
revenue-generating activity, or to fine-tune a model for commercial use, is
outside the licence — **and that LoRAs derived from dev inherit the
restriction**.

That is the same trap as ADR 0002 Finding 1: a permissive-looking model with a
licence that does not reach the thing you actually want to do. Three routes:

1. **FLUX.1 [schnell]** — Apache 2.0, commercial use permitted. Free. Fewer
   steps, so generally lower fidelity than dev.
2. **A BFL commercial licence for dev** — costs money, removes the question.
3. **Another permissively-licensed base model** — needs the same licence check
   done properly before anything is trained on it.

**What I need from you:** a decision in principle on whether you are willing to
pay for a base-model licence, or whether this must stay on Apache-2.0 weights.
Everything in S0.4 depends on it, and training on the wrong base means throwing
the run away rather than relicensing it.

*(Sources are secondary; I have not read BFL's licence text directly because
the domain is blocked. Treat the above as the shape of the problem, not as
advice to rely on — it needs verifying before any weights are pulled.)*

## Decision 2 — the flagship video provider

This is the one real spend in Spike 0 and the one the whole concept rests on:
can a still of her be animated without her face drifting into someone else?

Indicative per-second figures, **unverified**, roughly grouped:

| Tier | Indicative | Note |
|---|---|---|
| Premium, audio included | ~$0.75/sec | Highest quality tier, native audio and lip-sync |
| Premium, fast tier | ~$0.15/sec | Same family, draft quality |
| Mid | ~$0.09–0.15/sec | The competitive middle |
| Budget | ~$0.05/sec | Cheapest credible tier |

**Why the figure matters less than it looks.** Spike 0 needs perhaps 20–40
clips of 5 seconds to answer the question. Even at the premium rate that is on
the order of $75–150, not thousands. The decision is not "which is cheapest" —
it is **which one holds a face**, and that is what the identity scorer now
exists to measure.

**What I need from you:** an account with one provider, keys in the
environment. I would rather test one properly than three badly.

One thing worth knowing before you choose: a provider whose top tier generates
**audio and lip-sync natively** may remove the need for the lip-sync slot
entirely. That is a real saving and a whole pipeline stage deleted — worth
weighting in the choice.

## Decision 3 — `SPIKE_BUDGET_USD`

A single number. The cost guard refuses to make any paid call outside a
budgeted run, so nothing in S0.4 onward executes until it is set. It is a cap,
not a commitment — unspent budget is not spent.

Given the sizing above, a few hundred dollars covers Spike 0 comfortably
including re-runs. You set the figure; I will not choose it for you.

## What is NOT on this list

- **Text-to-speech.** There is no slot for it in the config and there should
  be. Flagging it rather than adding it: it is a real gap, and if the flagship
  video provider generates audio natively it may never need one.
- **Publishing platform APIs.** Gated behind amendment A10 and the
  no-auto-posting rule. Not a Spike 0 concern.

## What I need to finish this properly

The prices above are not good enough for `config/spike.yaml` and I will not
write them there. To replace them with verified figures I need to read the
providers' own pricing pages, which the environment's network policy currently
blocks.

Either:

- **Add the provider domains to the environment's allowed domains** (cloud
  environment menu in the session title bar, then Edit → Network access), and I
  will verify each price against its official page and record it with a
  `verified_on` date; or
- **Paste the pricing pages to me** and I will work from what you paste, noting
  that as the source.

Until one of those happens, every provider slot in the config stays `null`,
which is the correct state for a number nobody has checked.
