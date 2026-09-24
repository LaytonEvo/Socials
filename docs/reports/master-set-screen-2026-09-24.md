# Screening the master set against veo — 2026-09-24

22 of 28 stills screened before the budget stopped it. **The result is a list
of suspects, not a list of verdicts**, and the reason why is the more useful
finding.

**Model:** `fal-ai/veo3.1/fast/image-to-video` — a quarter the price of the
flagship, and valid to screen on because `m_004` fails identically on both
while `m_000` passes on both. The property being screened for transfers
between models.
**Method:** one attempt per still, bland prompt ("a person standing still,
static camera"), so the only variable is the image.

## Raw result

| Outcome | Count | Stills |
|---|---|---|
| Generated | 10 | — |
| `no_media_generated` | 6 | m_002, m_004, m_006, m_012, m_016, m_018 |
| `content_policy_violation` | 6 | m_003, m_007, m_008, m_013, m_017, m_019 |

Only 45% passed first time.

## Why these are suspects rather than verdicts

Listed in the order they ran, the failures cluster in time:

```
000 ok   001 ok   002 BAD  003 cp   004 BAD  005 ok
006 BAD  007 cp   008 cp   009 ok   010 ok   011 ok
012 BAD  013 cp   014 ok   015 ok   016 BAD  017 cp
018 BAD  019 cp   020 ok   021 ok
```

Runs of consecutive failures (002–006, 016–019) alternate with runs of
consecutive passes (009–011, 014–015, 020–021), and the clustering spans
*both* error classes. That is the signature of a service refusing more during
some periods than others, not of six particular images being unusable.

**This contradicts the design of the screen, which is my error.** The
one-attempt-per-still method assumed `no_media_generated` was deterministic
per image. The evidence for that assumption came almost entirely from `m_004`,
which genuinely is: six failures from six attempts, across two models and
several hours. One still does not license the generalisation, and the
clustering suggests the other five may be artefacts of when they were tried.

There is also an even/odd pattern — all six `no_media` stills are
even-numbered, and none of the eleven odd-numbered stills failed that way —
which has no explanation in the images themselves. File size, mean brightness,
contrast and EXIF are indistinguishable between the groups, and every still,
good or suspect, retains exactly one centred detectable face after cropping.
Recorded because it is striking and unexplained, not because it means
anything yet.

## The cost asymmetry that makes verification cheap

A refused call is never billed, so **verifying a suspect is free when the
suspicion is correct**. Re-testing the six `no_media` candidates three times
each costs nothing if they are all genuinely bad, and only costs money for the
ones that turn out to be fine — which is the right direction for the cost to
fall, and the reason the verification pass is worth doing before any of these
stills are discarded.

Discarding six of 28 stills on single-attempt evidence would be the expensive
mistake here: a master set is the reference the whole identity measurement
rests on, and it is already small.

## What this changes

- `content_policy_violation` refusals were already known to be stochastic and
  are now retried automatically (ADR 0006).
- `no_media_generated` is confirmed deterministic for `m_004` and **unproven
  for the rest**. The harness does not act on the other five.
- A screen of this kind needs repeats per still, not one attempt. Three
  attempts would cost the same for genuinely bad stills and would separate the
  two populations.

## Spend

$6.00 reserved for 22 stills, of which 10 generated. The ledger reserves at
$0.15/second while the run sends audio off at a lower rate, so the actual
charge is smaller — reconcile against the invoice rather than trusting this
figure (ADR 0006).
