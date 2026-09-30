# ADR 0010 — FLUX.1 [dev] via fal, and the identity layer is rented not owned

- **Status:** accepted by the owner, 2026-09-29, on their own reading of fal's terms
- **Decides:** the LoRA base model (task 1.4), and a constraint on where inference may run
- **Supersedes in part:** ADR 0005's "Base model: FLUX.1 [schnell] first"

## Context

ADR 0005 chose FLUX.1 [schnell] — Apache 2.0, commercial, free — specifically to avoid
`dev`, whose licence is non-commercial and whose restriction derived LoRAs inherit.

Checked at implementation time on 2026-09-29: **fal has no schnell trainer.** Its
catalogue offers schnell for inference only. Both FLUX trainers target `dev`, so the
route ADR 0005 chose to avoid is the only route available.

The owner reviewed fal's terms and the FLUX licence directly, which the build could not
do — huggingface.co is unreachable from the development container.

## Decision

**Train on `fal-ai/flux-lora-portrait-trainer` or `fal-ai/flux-lora-fast-training`, and
generate through fal's API.**

The owner's finding, recorded because the reasoning matters more than the conclusion:

> fal can offer commercial use because it pays BFL for a commercial licence. So if you
> train on fal and run your LoRA through fal's API, commercial use is covered.

## The constraint this creates, which is the point of this ADR

**The trained weights may not be run anywhere but fal.** Also the owner's finding:

> If you download the LoRA and put it on your own FLUX.1 [dev] setup, it falls under
> BFL's non-commercial licence, not fal's. Using that commercially would need your own
> licence from BFL. Nothing I read on fal says its commercial rights go with the weights
> once you take them off the platform.

So `lora_version.storage_key` is a **backup and a version record, not a deployment
artefact**. Keeping a copy is prudent; running it elsewhere is a licence breach. If
self-hosting ever becomes attractive — for cost, latency or independence — it needs
either written confirmation from fal or a licence from Black Forest Labs, obtained
first.

## This corrects a premise the project was built on

`docs/BUILD_ORDER.md` §6 states:

> The two-stage identity pipeline. The flagship video models do not accept custom LoRAs;
> keyframe-then-animate is the way to **own** the identity layer rather than rent it.

**Under this licence the identity layer is rented.** The two-stage pipeline still buys
what it was chosen for — control over the face, rather than hoping a video model holds
it — but not ownership. The distinction has consequences that were not priced in:

- **fal becomes a hard dependency for keyframe generation**, not a swappable provider.
  Everything else in `config/providers.yaml` can be changed by editing a model id. This
  cannot: moving the identity layer means retraining on another base and recalibrating
  against a new master centroid.
- **A price rise or a terms change at fal is a business risk**, not a procurement
  annoyance, because the alternative is retraining rather than reconfiguring.
- **Kill criteria (D5) should carry this**, since "fal withdraws commercial rights"
  belongs in the absolute-stops list alongside the existing entries.

None of this argues against proceeding. It argues for knowing which supplier the
persona's face depends on, and recording it where someone will find it.

## The outputs are not protectable, and that is separate

Also from the owner's review:

> fal doesn't promise the outputs are original, non-infringing, or protected by
> copyright. You may not own them in any enforceable way, and similar images could be
> generated for other users.

Mollie's likeness is therefore **not defensible property**. Somebody else could generate
a face close enough to be confusing, and there is no obvious remedy. For a persona whose
whole value is recognisability, that is a standing commercial risk rather than a legal
blocker, and it is worth the owner knowing before the brand is built on it.

## What does not apply here, and why

The owner's review flagged publicity, privacy and consent exposure over training photos.
**Those do not bite, because she is synthetic.** `persona.yaml` records
`production_mode: synthetic`, ADR 0002 Finding 4 required control sets stay synthetic to
avoid Article 9 biometric data, and every still in the 121-image reference set was
generated rather than photographed. No real person's likeness is in the training data,
so there is no release to obtain and no lawful basis to establish.

That holds only while it stays true. D2's contracted-performer route, if it is ever
taken, puts a real person's face into the pipeline and every one of those obligations
arrives with them.

The ASA/FCA disclosure point likewise does not apply: financial products are permanently
out of scope (D4), and disclosure is already mandatory in code rather than optional.

## Outstanding

**Written confirmation from fal** that commercial rights cover LoRAs trained and run on
their platform. The owner's own note: "the commercial-rights point rests on one line on
fal's marketing page. It isn't spelled out in the terms, so ask fal to confirm it in
writing before a large campaign." Not a blocker for training; a blocker for scale.


---

## Amendment, 2026-09-30 — the inference endpoint, verified

The LoRA was trained and evaluated, so the endpoint it runs on is now settled rather
than assumed. Verified against `fal.ai/models/fal-ai/flux-lora`, read 2026-09-30:

| | |
|---|---|
| Endpoint | `fal-ai/flux-lora` |
| Price | **$0.035 per megapixel**, "billed by rounding up to the nearest megapixel" |
| LoRA input | a `loras` array of `{path, scale}`, where `path` is the weights URL |

Recorded in `config/providers.yaml` as `image.lora_inference` with
`price_usd_per_image: 0.07` rather than a per-megapixel figure. Two reasons, both
deliberate: the cost guard prices one unit per slot, and a 1024x1024 image is 1.05 MP,
which rounds **up** to 2 MP and therefore bills 0.07. Taking the higher reading is the
house rule — a guard that understates lets a run pass the cap while reporting it is
inside it.

This endpoint is not a preference. **It is where the weights are permitted to run**, per
this ADR's main finding, and `LoraArtefact.require_inference_host` is what makes that
checkable rather than remembered.

Note that fal's page states "All generated images are cleared for commercial use". That
is consistent with the reading recorded above — fal's own licence covers work run on fal
— and it is still marketing copy rather than a contract.
`commercial_grant_confirmed_in_writing` stays `false`.
