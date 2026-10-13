# Hedra, Leonardo and Higgsfield, read against their own docs — 2026-10-13

**Status:** research only. No account created, no provider added, nothing billed.
Needs an owner decision. Filed here rather than in `docs/decisions/` on the
precedent of `motion-transfer-options-2026-09-25.md`: recording what was read is
not the same as deciding, and the decision in question is the owner's.

The owner asked whether three products were worth testing and opened the network
policy so they could be checked properly. All three are now reachable. Everything
below was read today from each vendor's own site — pricing pages, API docs, terms
of use — not from review sites, which on the first pass disagreed with each other
and, as it turns out, with the vendors.

## The finding that matters

**Every capability these three products would be bought for is already on fal,
and two of them were already costed on 2026-09-25.** The gap this project has is
not a missing vendor. It is an unanswered question from eighteen days ago.

`motion-transfer-options-2026-09-25.md` ends:

> **Not started.** Both are new paid providers on the account, which needs asking
> first.

They are not new providers. They are endpoints on the account this pipeline
already runs on, under the licence it already has.

### Prices re-verified today

`GET api.fal.ai/v1/models/pricing?endpoint_id=…`, 2026-10-13:

| Endpoint | $/s | Licence | What it gives us |
|---|---|---|---|
| `fal-ai/wan-motion` | **0.06** | commercial | motion transfer, `enhance_identity` |
| `blackforestlabs/flux-3/first-last-frame-to-video` | 0.085 | commercial | first/last frame pinning |
| `fal-ai/kling-video/v3/standard/motion-control` | **0.126** | commercial | motion transfer + facial element binding |
| `fal-ai/kling-video/v3/pro/motion-control` | 0.168 | commercial | the same, pro tier |
| `fal-ai/veo3.1/first-last-frame-to-video` | 0.40 | commercial | first/last frame pinning |

Unchanged from the 25 September reading, to three decimal places.

Note the unit price this API returns is **not qualified by resolution**. For
`minimax/h3-max-turbo/image-to-video` it reports $0.015/s while the guard holds
$0.04/s with `price_basis: {resolution: 768P}`. That is ADR 0013 exactly: the API
number is a price for some request, not for ours. Any new slot takes its price
from the model page's resolution tier, not from this endpoint.

### What the Kling v3 motion-control schema actually offers

Read from fal's queue OpenAPI today. Three things, each aimed at a live blocker:

- **`elements`** — `frontal_image_url` plus 1–3 further angles, referenced in the
  prompt as `@Element1`. fal's own description: *"Upload a facial element to
  enhance identity preservation in the generated video."* The master set has 105
  images to fill it from.
- **`video_url`** — the driving video. Swing mechanics and camera come from real
  footage, so the model is not asked to invent either. Up to **30 seconds** with
  `character_orientation: video`; 10 seconds with `image`.
- **`keep_original_sound`**, default true — the ambient and club sound the pieces
  currently have none of.

Camera drift through complex motion, identity through a long clip, and missing
sound are the three things on the unsolved list. This one endpoint is pointed at
all three.

**It still needs driving footage, and that remains the owner's decision**, framed
in the 25 September report and unchanged: the owner films roughly six seconds of
a real pitch on a phone. Free, no rights question, no Article 9 question, and
shootable in the framing the brief actually asks for. Stock footage needs its
licence read for an AI-conditioning prohibition; footage of real golfers is out
on copyright, likeness, and the fact that motion transfer carries mannerisms.

## The three products, as their own docs describe them

### Higgsfield — the one worth knowing about

A real, well-documented API: `api.higgsfield.ai`, key-pair auth, async submit and
poll, webhooks, idempotency keys, Python and TypeScript SDKs, a machine-readable
`llms.txt` and OpenAPI. Functionally a model aggregator, like fal — its catalogue
is Kling, Seedance, Wan, MiniMax, LTX, Grok, Pixverse, the same underlying models
we already reach.

Two things it has that are genuinely interesting:

- **`kling-video/o3/first-last-frame` with `multi_shots`.** First and last frame
  pinning, plus 1–6 per-shot prompts of 1–15s each, 9:16 supported, 3–15s total.
  **fal has no equivalent** — its first-last-frame endpoints are single-shot. The
  brief asks for a 15-second 9:16 piece in four shots; this endpoint takes that
  shape as one request, with continuity handled inside the model rather than by
  our stitching. That is the closest thing seen yet to the construction method
  `long-form-construction-2026-10-01.md` recommended.
- **`POST /v1/custom-references` (Soul ID)** — trains a reusable character
  reference from 1–100 images, returns an id to pass to generation. A hosted
  equivalent of the LoRA we already train on fal, so interesting but not new.

Pricing: **no public price list.** The pricing page is client-rendered and carries
no figures. Charging is credit-based pay-as-you-go, and there is an **estimate
endpoint** returning both credits and USD for the exact parameters you intend to
send. That is a better fit for our cost guard than any hardcoded number — it
prices the request rather than the endpoint, which is what ADR 0013 said a price
has to do. It needs an account and a key to call.

Terms, §4.4, verified today: *"Company does not claim ownership of any of your
Inputs or Outputs, nor does it restrict your commercial use of Outputs"*, rights
survive cancellation and are transferable and sublicensable. Good.

**But, same section:** *"Your Content, Inputs, and Outputs may be used by Company
to train, develop, enhance, evolve, and improve its … AI models"* — exempted only
under an Enterprise Agreement. Our inputs are her master stills. On a standard
plan, uploading them grants a training licence over her face. §4.3 also requires
we hold all consents for any identifiable individual's likeness, and §4.4 points
at a Biometric Information clause in the privacy policy. Outputs are explicitly
**not guaranteed unique or exclusive** across users.

For a project whose single asset is one consistent face, that is a real cost, not
a footnote.

### Hedra — aimed at the part that already works

Pricing read from `hedra.com/pricing` today: Basic $20/mo (2,000 credits), Pro
$50/mo (7,200), Ultra $100/mo (18,000), Teams $75/mo (14,400), Enterprise custom.
Every tier states commercial use. Subscription, not pay-as-you-go. The credits-to-
seconds conversion for video is behind a client-rendered FAQ and was **not
verifiable**.

None of these figures match what the review sites claimed on the first pass.

Hedra's product is audio-driven talking heads: still plus audio, out comes a
character speaking. That is shot 1 — accepted, approved, 6.58s, zero frames below
threshold. It might collapse our keyframe → animate → HeyGen-sync chain into one
call, which is worth something, but it does not address golf mechanics, camera
drift, or a shot with no face in it.

Terms: *"Hedra does not claim ownership of any Inputs or Outputs"* — but the
content licence granted to Hedra is **perpetual, irrevocable, transferable,
sublicensable, worldwide, and includes the right to "derive revenue or other
remuneration from Your Content."** Higgsfield's equivalent licence is limited to
operating the service, ends when content is deleted, and is assignable only on a
merger or sale. On the terms alone, Hedra is the worst of the three to hand a
persona's face to.

### Leonardo — my earlier read was out of date

I told the owner Leonardo was image generation plus a short Motion clip. That was
wrong as of today. Its API docs list Kling 3.0 and o3, Seedance 2.0 and 2.5, Veo
3.1, Wan 2.6 and 2.7, Hailuo, FLUX 3 Video, Grok Imagine — the same aggregator
catalogue as fal and Higgsfield, plus its own Motion 2.0.

It has moved to pay-as-you-go with real-time balance deduction, auto top-ups, and
an `apiCreditCost` field on every response. Per-model prices are behind a
calculator in the signed-in app and were **not verifiable** from the docs.

`www.leonardo.ai` serves a Cloudflare managed challenge to non-browser clients —
403 with `cf-mitigated: challenge` — so the marketing and pricing pages could not
be read even with the domain allowed. `docs.leonardo.ai` is open. Nothing there
offers a capability fal lacks.

## What I would do

1. **Nothing with these three yet.** Two offer less than what we already pay for;
   the third's one real advantage is a shot-sequencing endpoint we have not yet
   earned the right to need, since we cannot currently render shot 2.
2. **Answer the 25 September question.** Six seconds of phone footage of a real
   pitch, then `wan-motion` at ~$0.36 and `kling-video/v3/standard/motion-control`
   at ~$0.76 against the same still — about **$1.15** to learn whether real motion
   transfers, whether her face survives it, and whether a portrait master set is
   enough character reference. No new provider, no new licence, no new account.
3. **If that works and the four-shot piece is next**, revisit Higgsfield's
   `kling-o3/first-last-frame` multi-shot specifically, and only on an Enterprise
   agreement or with the training clause accepted deliberately. Worth an ADR at
   that point, not before.

## Sources

Read 2026-10-13, each from the vendor's own domain:

- `docs.higgsfield.ai/docs/llms.txt`, `/docs/concepts/billing-and-retention.md`,
  `/docs/help/faq.md`, `/docs/sitemap.xml`,
  `/docs/models/kling-3-motion-control/std.md`,
  `/docs/models/kling-o3/first-last-frame.md`,
  `/docs/models/soul-id/create-character.md`,
  `/docs/models/seedance-2-5/video-extend.md`
- `higgsfield.ai/terms-of-use-agreement` (§4.3, §4.4, §11), `higgsfield.ai/pricing`
- `hedra.com/pricing`, `hedra.com/terms`
- `docs.leonardo.ai/llms.txt`, `/docs/pricing-and-plans-faq`
- `api.fal.ai/v1/models/pricing?endpoint_id=…`, `fal.ai/api/models?keywords=…`,
  `fal.ai/api/openapi/queue/openapi.json?endpoint_id=…`

Not verifiable: Higgsfield per-model prices, Leonardo per-model prices, Hedra's
credits-per-second for video. All three sit behind a signed-in app.
