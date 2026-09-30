# LoRA training — first attempt, and why it failed

**Date:** 2026-09-30
**Outcome:** no LoRA. Blocked on hosting for the training archive.
**Spend:** one 1000-step submission and one 10-step diagnostic, both billed by our own
accounting, both producing nothing. See *Cost* below — the amount is not certain.

## What happened

Gate A passed, the budget was topped up, and the first real training run was submitted:
102 training stills, 19 held out, 1000 steps, $24.000 estimated at the
`price_usd_per_step` in `config/providers.yaml`.

fal accepted it, queued it, ran it for about two and a half minutes and returned
**COMPLETED with no weights file**. That is ADR 0006's trap — a clean status with a
validation error in the body — at training prices rather than image prices.

Reproduced at 10 steps rather than debugging at $24 a look. The response body:

```
Failed to download archive: Invalid URL: URL too long
```

**The archive was passed as a data URI and fal fetches that URL itself.** At 102 stills
and 1024px the archive is 16.73 MB, which is **22.31 MB** base64-encoded. The queue
accepts the submission — the POST body is not the limit — and the fetcher rejects it
afterwards, which is why it arrives as a billed completion rather than a free 4xx.

## Why it was a data URI at all

Because the bucket is not configured. `TrainingRequest.archive_url` is documented to
carry *"a presigned URL from our own bucket"*; `S3_BUCKET` is unset, so the only private
option left was a data URI — the same mechanism `app/providers/fal.py` uses to keep her
stills off fal's public CDN (ADR 0006).

That mechanism is right for a single still and wrong for a 16 MB archive. The size is
the whole difference, and nothing had established where the line was.

## The fix, and the fix that is not available

**Now in the code:** `_refuse_oversized_data_uri` refuses before the POST, so this
failure is free from here on. The cap is 2 MB — deliberately far below the 22.31 MB that
was measured to fail. The real ceiling is unpublished and is not worth probing at roughly
$0.24 and three minutes an attempt.

**Needed, and only the owner can do it:** the `persona-media` bucket exists in the
Railway project but its credentials are not exposed through Railway's API, so they have
to be copied from the dashboard into the environment — `S3_BUCKET`, `S3_ENDPOINT_URL`,
`S3_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. With those set, the archive
uploads once and the trainer receives a short presigned URL.

**The alternative, and why it was not taken:** fal's own upload endpoint would work
today. It is a public CDN — anyone with the URL can download — and this archive is the
persona's entire reference set. Publishing it to get past a blocker is a decision about
her identity, not a workaround, so it is the owner's to take rather than mine.

## Cost

| | |
|---|---|
| 1000-step submission | $24.000 by our accounting |
| 10-step diagnostic | $0.240 by our accounting |

**Both figures are our own guard prices and neither is an invoiced amount.** The adapter
marks a run billed from the moment fal accepts it, on the reasoning that a GPU which
started and then failed is still spend. Both runs failed *validation* rather than
training, having occupied a worker for about two and a half minutes each. fal may well
charge nothing for them. **Check the fal dashboard against these numbers** — if it
charged nothing, our accounting is pessimistic by $24.24 and that is worth knowing
before the budget model hardens.

## A bug this found before it could do harm

Preparing the run surfaced a real defect in `app/identity/dataset.py`, unrelated to the
failure above and more serious than it.

`split()` ranked stills by hashing `path.as_posix()`, so an absolute path and a relative
path to the same file ranked differently: **the same 121 images produced a different
train/holdout split depending on where the repository was checked out.** 102/19 either
way, but not the same 102. `dataset_hash()` had the same flaw, which is worse — it is the
provenance recorded on the artefact, and it was identifying the checkout rather than the
data.

Both now key on `Still.name`, which is checkout-independent. Two tests pin it.

Nothing had been trained, so no recorded artefact is invalidated. Had the run succeeded,
the artefact would have carried a hash that nobody could reproduce and a holdout that
could not be reconstructed — and the evaluation, whose entire point is that the holdout
is excluded, would have been unverifiable.

**The order of events was lucky, not careful.** The bug would have been found by the
first person who ran the pipeline from a different directory, after the evidence had been
built on it.

## State

- Dataset prep, split, archive, pricing, budget guard and the refusal path: all working,
  all exercised.
- Training: never completed. No artefact exists.
- Holdout evaluation: not reached.
- `dataset_hash` for the current split: `f724a17950ede69a144c0cbe705a676d80ce48f752aadda4ca8fbace86a14392`

The run is one environment variable away from repeating, and the pipeline either side of
the upload is proven.
