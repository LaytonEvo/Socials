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
