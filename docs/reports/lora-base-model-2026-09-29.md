# Task 1.4 is blocked, on a licence and on cost

**Checked 2026-09-29 against fal's live model listing, OpenAPI and pricing API**, as
CLAUDE.md requires before pulling in model weights. Nothing has been spent.

## The plan of record is not executable

ADR 0005 chose **FLUX.1 [schnell]** — Apache 2.0, commercial use permitted, free —
explicitly to avoid `dev`, and recorded why:

> FLUX.1 [dev] is non-commercial and derived LoRAs inherit the restriction, so training
> on it first would mean discarding the run rather than relicensing it.

**There is no schnell trainer on fal.** Searching its catalogue returns
`fal-ai/flux-1/schnell`, `fal-ai/flux/schnell` and their `redux` variants — all
inference, no training. The two FLUX trainers fal offers are:

| Endpoint | Price | Unit |
|---|---|---|
| `fal-ai/flux-lora-fast-training` | $0.02 | per step |
| `fal-ai/flux-lora-portrait-trainer` | $0.024 | per step |

Neither names its base model in its schema, and neither can plausibly be schnell given
none exists. So the route ADR 0005 chose to avoid is the only route fal offers.

## `licenseType: commercial` is not the answer it looks like

Both trainers carry `licenseType: commercial` in fal's listing. That is **fal's
statement about its own endpoint** — that you may use the service commercially — and
not a statement about the FLUX weights or about what you may do with the LoRA it hands
back.

Whether fal's arrangement with Black Forest Labs extends commercial rights to a LoRA
trained through their API is a legal question. ADR 0002 set the precedent for exactly
this shape of problem, with dlib's FaceScrub caveat: a licence grey area is recorded
and put to counsel, not resolved by reading a tag.

The stakes are concrete. A LoRA trained under a non-commercial licence has to be
discarded rather than relicensed, and it is the identity layer the whole persona rests
on.

## Cost is a different order from anything so far

Priced **per step**, not per run:

| Steps | Fast | Portrait |
|---|---|---|
| 250 | $5.00 | $6.00 |
| 500 | $10.00 | $12.00 |
| 1000 | $20.00 | $24.00 |
| 2000 | $40.00 | $48.00 |

A realistic identity LoRA is 1000–2000 steps. BUILD_ORDER budgeted "1–3 hosted GPU
runs", so $20 to $150 depending on how many attempts it takes.

**$6.08 remains of the $10 authorised**, which does not cover one run at a useful step
count. Everything spent so far has been in single dollars; this is not that, and
CLAUDE.md says to ask before adding a paid service rather than assume.

## What would unblock it

1. **The licence**, which is the one that matters. Either fal's terms are read and found
   to grant commercial use of derived LoRAs, or counsel confirms it, or a different
   base with an unambiguous licence is used. Options worth pricing if it comes to that
   include SDXL (CreativeML Open RAIL++-M, commercial permitted with use restrictions)
   and Qwen Image, both of which fal also trains.
2. **A training budget**, separately authorised, sized for 1–3 runs at 1000–2000 steps.

Neither is the build's to decide. Everything else in 1.4 — dataset preparation from the
121-still reference set, the versioned artefact in storage, evaluation against held-out
stills — is unblocked and can be built against a fake trainer in the meantime, so the
only thing waiting on a real run is the run itself.
