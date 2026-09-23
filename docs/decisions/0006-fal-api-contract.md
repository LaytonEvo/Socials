# ADR 0006 — fal.ai API contract, as verified

- **Status:** Accepted 2026-09-23
- **Date:** 2026-09-23
- **Verified against:** fal's own documentation, read 2026-09-23 —
  `https://fal.ai/docs/documentation/model-apis/overview` and
  `https://fal.ai/docs/documentation/model-apis/inference/queue.md`
- **Relates to:** [ADR 0005](0005-fal-ai-as-the-spike-provider.md); `CLAUDE.md`
  non-negotiable rule 1 (verify against official docs, record what you found)

## Why this exists

`scripts/spike/providers.py` says, in its own docstring, that implementing a
real backend means first verifying the provider's current API against its
official documentation, because *"a stub that guessed at an endpoint would
violate exactly the rule the project cares most about."* This is that record.
Everything below was read from fal's documentation on the date above, not
recalled.

## The contract

**Authentication.** Header `Authorization: Key $FAL_KEY`. The environment
variable name `FAL_KEY` is fal's own convention, confirmed in their examples —
not an assumption, which it was until this was read.

**Submit.** `POST https://queue.fal.run/{model_id}` with
`Content-Type: application/json`. Model ids look like `fal-ai/flux/schnell`.
The REST body is the arguments object directly; the `input:` wrapper is a
client-library shape, not the HTTP one.

Response:

```json
{
  "request_id": "764cabcf-...",
  "response_url": ".../requests/{id}/response",
  "status_url":   ".../requests/{id}/status",
  "cancel_url":   ".../requests/{id}/cancel",
  "queue_position": 0
}
```

**Poll.** `GET https://queue.fal.run/{model_id}/requests/{id}/status` (add
`?logs=1` for runner logs). Three states:

| Status | Carries |
|---|---|
| `IN_QUEUE` | `queue_position` |
| `IN_PROGRESS` | `logs` |
| `COMPLETED` | `logs`, `metrics.inference_time`, **and `error` / `error_type` if it failed** |

**Retrieve.** `GET https://queue.fal.run/{model_id}/requests/{id}`. Output
media comes back as **URLs on fal's CDN**, not as bytes.

There is also a synchronous `https://fal.run/{model_id}`, and a `subscribe`
helper in the client libraries that polls for you. The queue is what fal
recommends for production and is what the adapter uses.

## COMPLETED can also mean "never validated", and the status does not say so

Found by accident on 2026-09-23, by submitting a request with a missing
required field. The documented behaviour is that a failed request reaches
`COMPLETED` carrying `error` and `error_type`. This one reached `COMPLETED`
with **`error: None`**, `metrics.inference_time` of 0.049s, and nothing else to
suggest a problem. The validation failure appeared only when the *result* was
fetched:

```
GET .../requests/{id}   ->  422
{"detail":[{"type":"missing","loc":["body","image_url"],"msg":"Field required"}]}
```

So a clean-looking status is not sufficient to conclude a request worked.
`raise_if_failed` on the status remains necessary and is not sufficient; the
result fetch is the second gate, and the adapter treats **422 as free
everywhere** rather than only on submit, because a body fal rejected was never
run no matter which call reports it.

The near-zero `inference_time` is the tell, and it is worth remembering as a
smoke test: a five-second clip that took 0.05s to infer did not happen.

## Four things a guessed implementation would have got wrong

These are the reason rule 1 exists, and each is load-bearing:

1. **`COMPLETED` does not mean success.** A completed request can carry `error`
   and `error_type`. Treating the terminal state as success would silently
   record a failed generation as a good take — and, worse, would charge the
   cost ledger for it while producing no file.
2. **The result is a URL, not bytes.** Retrieving a clip is two calls: the
   result JSON, then a download from `v3.fal.media`. That download can fail on
   its own, after the money has already been spent.
3. **fal retries internally, up to 10 times**, on runner failure (503, 504,
   connection errors). Our own retry logic must not stack on top of that; doing
   so would multiply both latency and — possibly — spend.
4. **The response carries no price.** It reports `metrics.inference_time`, not
   a charge.

## Verified prices, read from each model's own page 2026-09-23

Attributed to a model id rather than lifted from the page, because a fal model
page carries several models' prices in the same payload and the first number
you find is often a different variant's.

| Model id | Price | Notes |
|---|---|---|
| `fal-ai/veo3.1/image-to-video` | **$0.20/s** no audio, **$0.40/s** with, at 720p/1080p | 4k is $0.40 / $0.60. fal's own worked example: 5s at 1080p with audio = $2.00 |
| `fal-ai/veo3.1/fast` | $0.10/s no audio, $0.15/s with | Draft tier of the same family |
| `fal-ai/kling-video/v2.5-turbo/pro/image-to-video` | $0.35 per 5s, then $0.07/s | ≈ $0.07/s |
| `fal-ai/kling-video/v2.5-turbo/standard/image-to-video` | $0.21 per 5s, then $0.042/s | ≈ $0.042/s |

### The page and the API disagree, so the guard takes the higher number

Queried `api.fal.ai/v1/models/pricing` on 2026-09-23, now that the host is
reachable:

| Endpoint | API `unit_price` | Model page |
|---|---|---|
| `fal-ai/veo3.1/image-to-video` | **0.40 / second** | $0.20 without audio, $0.40 with |
| `fal-ai/veo3.1/fast/image-to-video` | 0.15 / second | $0.10 without audio, $0.15 with |
| `fal-ai/kling-video/v2.5-turbo/pro/image-to-video` | 0.07 / second | ~$0.07/s |

The API reports what looks like the with-audio rate as the single unit price.
Whether turning audio off actually halves the bill is not something either
source states outright.

**`config/spike.yaml` therefore carries the API figure, not the page figure.**
A cost guard that understates is worse than no cost guard: it lets a run pass
the cap while reporting it is inside one. Over-reserving means spending less
than budgeted, which is the safe direction to be wrong in. The open question —
does audio-off halve it — resolves against a real invoice, not against a
marketing page.

**Audio is off for the S0.5 identity run.** It doubles the rate and the
question being asked is whether her face survives, which no soundtrack
affects. Whether native audio can replace the lip-sync stage is a separate
question, worth a handful of clips at $0.40/s once identity is settled — not
worth paying double across the whole matrix to find out early.

## Getting a keyframe to fal, and the two things that came with it

Read from `https://fal.ai/docs/documentation/model-apis/fal-cdn.md`, 2026-09-23.

Models take file inputs as **URLs**. There are exactly three documented ways to
give fal a local file, and **raw REST upload is not one of them** — the CDN page
says auth is "handled automatically by the SDK", and no plain-HTTP upload
endpoint is documented. (`POST /assets/uploads` on the platform API takes a
`url`: it imports from somewhere else, it does not upload bytes.) Implementing
one would mean reverse-engineering the client library, which is the guess this
project refuses to make.

| Route | Verdict |
|---|---|
| `fal_client` SDK upload | Documented and supported. Adds a vendor dependency, which `CLAUDE.md` permits inside the provider seam. The production answer if data URIs stop being enough. |
| **Data URI** (`data:image/jpeg;base64,...`) | **Chosen.** Documented, no dependency, no infrastructure. fal discourages it above "a few KB", which a keyframe exceeds — accepted deliberately: at spike volumes the inefficiency costs nothing, and `MAX_DATA_URI_BYTES` keeps the trade small. |
| A URL you already host | Best of the three once something hosts keyframes, because fal's runner fetches it and nothing is inlined. Nothing hosts them yet. `_require_hosted_keyframe` is the resolver for that day. |

Two things on that page that are not about uploading and matter more:

**CDN files are public by default.** "Anyone with the URL can download." Any
keyframe or generated clip that lands on fal's CDN is publicly retrievable by
URL. The persona is synthetic so this is not a personal-data problem, but it
does mean unreleased renders of her are world-readable to anyone holding the
link. fal provides File ACLs and a per-request
`X-Fal-Object-Lifecycle-Preference` header for retention. **Neither is
configured, and this belongs in the D7 counsel scope alongside ADR 0002
Finding 4.** Choosing the data URI route sidesteps it for inputs — nothing of
hers is uploaded — but outputs still land there.

**The CDN host is not one hostname.** Uploads return `v3b.fal.media`; queue
results in fal's own examples use `v3.fal.media`; the SDK falls back to
`fal.media`. Anything allow-listing fal's egress needs all three, plus
`queue.fal.run` and `api.fal.ai`. Allow-listing the apex domains alone does not
cover them, which this environment demonstrated.

## The queue contract is shared; the arguments are not

Read from the model's own API reference, 2026-09-23, after a 422 rejected a
submission that looked fine against the queue documentation.

`fal-ai/veo3.1/image-to-video` takes:

| Field | Allowed | Default |
|---|---|---|
| `duration` | `4s`, `6s`, `8s` — **string literals, not numbers** | `8s` |
| `resolution` | `720p`, `1080p`, `4k` | `720p` |
| `generate_audio` | boolean | **`true`** |
| `image_url` | required; 720p+, 16:9 or 9:16 or it is cropped | — |

**`generate_audio` defaults to true, and that resolves the pricing question
from earlier in this ADR.** fal's pricing API reports 0.40/second flat because
that is the with-audio rate for the default configuration. Setting the flag
false is what makes the model page's $0.20/s apply. The config keeps 0.40 as
the reserve anyway: over-reserving is the safe direction, and being pleasantly
surprised by an invoice is better than the reverse.

Two lessons worth keeping:

**Duration is not rounded.** `veo_duration` refuses a value the model does not
accept rather than snapping to the nearest one, because silently turning a
requested 5 seconds into 4 changes both what is measured and what is billed.

**The keyframe aspect ratio matters, and it bit us.** Inputs outside 16:9 or
9:16 are cropped to fit. **All 28 master stills are 928x1232 — a ratio of
0.753, which is neither.** Reaching 9:16 means cropping the width from 928 to
693: a quarter of the frame discarded by the provider, blind to where she is
in it.

That is a confound in the worst possible place. The master centroid is built
from the uncropped originals while the clips are generated from cropped ones,
so any reframing shifts the embedding and reads as identity drift without
being any such thing. It is a candidate explanation for the first near-miss
measured (0.9638 against a 0.9748 threshold).

`data_uri_keyframe` now crops to 9:16 itself, so the crop is deliberate,
reproducible, and ours. `crop_to_aspect` takes an optional face box and keeps
it centred, clamped so a subject near an edge still yields a full-size window
rather than a smaller one — a shrunken crop would change her scale in frame,
which moves the embedding for a second unrelated reason.

**Still open, and larger:** the master set is embedded uncropped while what
gets animated is cropped. The honest fix is to calibrate on the same framing
that gets sent, which means re-preparing the master set at 9:16 and
re-calibrating — amendment A3 territory, and not a change to make in the
middle of a run.

## The content checker blocks legitimate prompts, and not consistently

2026-09-23. A request generated a clip successfully, and the **identical**
request — same prompt, same keyframe, same cell — was refused minutes later:

```
422 content_policy_violation
"The content could not be processed because it contained material flagged
 by a content checker."
prompt: "a 25 year old english woman on a golf course, medium shot from the
         waist up, facing the camera straight on, walking steadily, warm low
         golden hour light"
```

Nothing in that prompt is objectionable, and the same input passed minutes
earlier, so the checker is either non-deterministic or stateful. **This is a
material risk to the concept, not a nuisance**: a pipeline that depends on
animating a photo of a woman will meet this repeatedly, and a production run
that silently loses cells to it produces a biased matrix — the conditions that
survive are not a random sample of the conditions attempted.

Two relevant parameters, both now stated explicitly rather than inherited:

**`auto_fix` is off and must stay off.** fal offers to "fix prompts that fail
content policy by rewriting them" and run the rewrite. In a condition matrix
the prompt *is* the variable, so a silent rewrite means the cell recorded is
not the cell that ran. That is the same class of error as calibrating in a
space the scorer does not read: self-consistent, plausible, and measuring
something other than what it claims.

**`safety_tolerance` is left at fal's default of 4** (range 1–6, 6 loosest).
Loosening a provider's moderation setting is an owner decision, not an
engineering convenience, and it is exactly the kind of choice this project
expects to be made deliberately and written down. Flagged for the owner; not
changed.

Both are sent explicitly so that a change to fal's defaults cannot silently
change what a run measured.

## The cost-ledger consequence, which needs a decision later

`CLAUDE.md` requires every paid call to write a `cost_ledger` row in USD in the
same transaction. fal does not return a cost, so **the ledger figure is our own
computation** — configured price per second × duration — and not fal's billed
amount.

That is an estimate wearing the clothes of a record. It is acceptable for Spike
0, where the point is to stay inside a cap rather than to reconcile a bill, but
it must not silently become the production accounting. Two follow-ups, neither
due now:

- fal **does** expose pricing programmatically:
  `GET https://api.fal.ai/v1/models/pricing?endpoint_id=...` returns unit
  pricing per endpoint id, and there is a cost-estimate endpoint alongside it.
  That is a better source than a config figure a human transcribed, and it
  could check config against the provider at run time rather than trusting a
  `verified_on` date not to go stale. Not used yet: `api.fal.ai` is blocked by
  this environment's network policy, and the ledger's correctness is not a
  Spike 0 blocker.
- Until then, the ledger should be read as "what we believe we spent", and the
  spike report should compare it against the actual invoice once one exists.

Recorded here rather than fixed, because fixing it means either a second API or
a reconciliation step, and neither is a Spike 0 concern.

## Not verified

- Whether an internally-retried request is billed once or per attempt.
- The upload API, needed to send a local keyframe. Until it is read,
  `FalVideoProvider.resolve_keyframe` refuses rather than guesses.
- Rate limits and concurrency caps.
