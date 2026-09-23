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

## The cost-ledger consequence, which needs a decision later

`CLAUDE.md` requires every paid call to write a `cost_ledger` row in USD in the
same transaction. fal does not return a cost, so **the ledger figure is our own
computation** — configured price per second × duration — and not fal's billed
amount.

That is an estimate wearing the clothes of a record. It is acceptable for Spike
0, where the point is to stay inside a cap rather than to reconcile a bill, but
it must not silently become the production accounting. Two follow-ups, neither
due now:

- Check whether fal's platform API exposes per-request billing that could be
  reconciled against the ledger.
- Until then, the ledger should be read as "what we believe we spent", and the
  spike report should compare it against the actual invoice once one exists.

Recorded here rather than fixed, because fixing it means either a second API or
a reconciliation step, and neither is a Spike 0 concern.

## Not verified

- Per-model pricing. Each model's page carries its own rate; those go into
  `config/spike.yaml` per model with their own `verified_on`, read at the time
  the model is chosen.
- Whether an internally-retried request is billed once or per attempt.
- Rate limits and concurrency caps.
